import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime, add_to_date
#from transport_management.whatsapp import send_whatsapp_message
from frappe import _
 
class CabRequest(Document):
 
    def validate(self):
        self.validate_dates()
        self.validate_booking_one_hour_before()
        self.prevent_employee_status_change()
        self.validate_driver_status_change()
        self.handle_allocation()
        self.validate_employee_active_booking()
        self.validate_driver_not_in_trip()
        self.validate_cab_not_in_trip()

    # ==========================================
    # Called whenever document is updated
    # ==========================================
    # def on_update(self):
    #      self.send_status_mail()


    # ==========================================
    # 📧 Email + 📱 WhatsApp Notifications
    # ==========================================    
    def send_status_mail(self):

        # Only trigger when status actually changes
        if self.is_new() or self.db_get("status") == self.status:
            return

        employee_email = frappe.db.get_value(
            "Employee", self.employee_id, "personal_email"
        )
        employee_phone = frappe.db.get_value(
            "Employee", self.employee_id, "cell_number"
        )

        driver_email = None
        driver_phone = None

        # Get Driver Email & Phone
        if self.driver_id:
            driver_employee = frappe.db.get_value(
                "Driver", self.driver_id, "employee"
            )
            if driver_employee:
                driver_email = frappe.db.get_value(
                    "Employee", driver_employee, "personal_email"
                )
                driver_phone = frappe.db.get_value(
                    "Employee", driver_employee, "cell_number"
                )

        # ================================
        # ✅ ASSIGNED
        # ================================
        if self.status == "Assigned":

            if employee_email:
                frappe.sendmail(
                    recipients=[employee_email],
                    subject="Cab Request Assigned",
                    message=f"""
                    Hello {self.employee_name},<br><br>
                    Your cab request is Assigned.<br>
                    Driver: {self.assigned_driver}<br>
                    Cab: {self.assigned_cab}<br>
                    Pickup: {self.pickup_location}<br>
                    Drop: {self.drop_location}<br><br>
                    Regards
                    """
                )

            if employee_phone:
                send_whatsapp_message(
                    employee_phone,
                    f"""Your Cab Request {self.name} is Assigned.

Driver: {self.assigned_driver}
Cab: {self.assigned_cab}
Pickup: {self.pickup_location}
Drop: {self.drop_location}
"""
                )

            if driver_email:
                frappe.sendmail(
                    recipients=[driver_email],
                    subject="New Cab Assignment",
                    message=f"""
                    You have been assigned a trip.<br><br>
                    Employee: {self.employee_name}<br>
                    Pickup: {self.pickup_location}<br>
                    Drop: {self.drop_location}<br>
                    Contact: {self.contact_no}
                    """
                )

            if driver_phone:
                send_whatsapp_message(
                    driver_phone,
                    f"""New Trip Assigned!

Employee: {self.employee_name}
Pickup: {self.pickup_location}
Drop: {self.drop_location}
Contact: {self.contact_no}
"""
                )

        # ================================
        # 🚗 IN TRIP
        # ================================
        if self.status == "In Trip":

            if employee_email:
                frappe.sendmail(
                    recipients=[employee_email],
                    subject="Your Cab is On the Way",
                    message=f"""
                    Hello {self.employee_name},<br><br>
                    Your driver has started the trip.<br>
                    Driver: {self.assigned_driver}<br>
                    Cab: {self.assigned_cab}<br>
                    Pickup: {self.pickup_location}<br><br>
                    Regards
                    """
                )

            if employee_phone:
                send_whatsapp_message(
                    employee_phone,
                    f"""Your driver has started the trip.

Driver: {self.assigned_driver}
Cab: {self.assigned_cab}
Pickup: {self.pickup_location}
"""
                )

        # ================================
        # ✅ COMPLETED
        # ================================
        if self.status == "Completed":

            if employee_email:
                frappe.sendmail(
                    recipients=[employee_email],
                    subject="Trip Completed",
                    message=f"""
                    Hello {self.employee_name},<br><br>
                    Your trip has been completed successfully.<br>
                    You may now book a new cab request.<br><br>
                    Regards
                    """
                )

            if employee_phone:
                send_whatsapp_message(
                    employee_phone,
                    f"""Trip Completed Successfully!

Cab Request: {self.name}
You can now book a new cab.
"""
                )

        # ================================
        # ❌ REJECTED
        # ================================
        if self.status == "Rejected":

            if employee_email:
                frappe.sendmail(
                    recipients=[employee_email],
                    subject="Cab Request Rejected",
                    message=f"""
                    Hello {self.employee_name},<br><br>
                    Your cab request was rejected.<br>
                    Reason: {self.rejection_reason}<br><br>
                    Regards
                    """
                )

            if employee_phone:
                send_whatsapp_message(
                    employee_phone,
                    f"""Cab Request Rejected.

Reason: {self.rejection_reason}
"""
                )

        # ================================
        # 🚫 CANCELLED
        # ================================
        if self.status == "Cancelled":

            if driver_phone:
                send_whatsapp_message(
                    driver_phone,
                    f"""Trip Cancelled by Employee.

Request: {self.name}
Pickup: {self.pickup_location}
Drop: {self.drop_location}
"""
                )
 
    # 1. 🔒 DATE & TIME VALIDATION
    def validate_dates(self):
        if self.booking_datetime:
            if get_datetime(self.booking_datetime) < now_datetime():
                frappe.throw(_("Booking cannot be in the past. Please select a future time."))

    # 2. 🕐 Cab must be booked at least 1 hour before shift/booking time
    def validate_booking_one_hour_before(self):
        if self.booking_datetime:
            booking_dt = get_datetime(self.booking_datetime)
            # Booking must be submitted at least 1 hour before the scheduled trip time
            if booking_dt < add_to_date(now_datetime(), hours=1):
                frappe.throw(_(
                    "Cab must be booked at least <b>1 hour</b> before the trip time. "
                    "Please select a time that is at least 1 hour from now."
                ))
 
    # 3. 🚫 Prevent Employee from changing status directly
    def prevent_employee_status_change(self):
        if self.is_new(): return
        
        roles = frappe.get_roles()
        allowed_roles = ["Fleet Manager", "System Manager", "Driver"]
        if "Employee" in roles and not any(role in roles for role in allowed_roles):
            old_status = self.db_get("status")
            # Allow Employee only to change to "Cancelled" (handled via whitelisted method)
            # Block any direct status change from the form
            if old_status != self.status and self.status != "Cancelled":
                frappe.throw(_("Employees are not allowed to change the status."))

    # 4. 🚖 Validate Driver status transitions — only allowed via whitelisted buttons
    def validate_driver_status_change(self):
        if self.is_new(): return

        roles = frappe.get_roles()
        old_status = self.db_get("status")

        if old_status == self.status:
            return  # No change, skip

        # Only drivers can move status to "In Trip" or "Completed"
        if self.status in ["In Trip", "Completed"]:
            if "Driver" not in roles and "Fleet Manager" not in roles and "System Manager" not in roles:
                frappe.throw(_("Only the assigned Driver can update the trip status to In Trip or Completed."))
 
    # 5. 🔁 Copy Allocation → Trip Details when Assigned
    def handle_allocation(self):
        if self.status == "Assigned":
            if not self.driver_id or not self.cab:
                frappe.throw(_("Please select a Driver and Cab in the Allocation section before approving."))
            
            self.assigned_driver = self.driver_id
            self.assigned_cab = self.cab

    # 6. 🚫 Prevent Employee from booking if they already have an active trip
    #       Active = Pending, Assigned, or In Trip
    def validate_employee_active_booking(self):
        if not self.is_new():
            return  # Only block on new bookings

        roles = frappe.get_roles()
        # Only apply this check for pure employees (not managers/drivers)
        if "Fleet Manager" in roles or "System Manager" in roles or "Driver" in roles:
            return

        existing = frappe.db.get_value(
            "Cab Request",
            {
                "employee_id": self.employee_id,
                "status": ["in", ["Pending", "Assigned", "In Trip"]],
                "name": ["!=", self.name]
            },
            ["name", "status"],
            as_dict=True
        )

        if existing:
            frappe.throw(
                _(
                    f"You already have an active Cab Request <b>{existing['name']}</b> "
                    f"with status <b>{existing['status']}</b>. "
                    f"You can only book a new cab after your current trip is marked as <b>Completed</b>."
                ),
                title=_("Booking Not Allowed")
            )

    # 7. 🚫 Prevent assigning a Driver who is currently In Trip
    def validate_driver_not_in_trip(self):
        if self.status != "Assigned" or not self.driver_id:
            return

        in_trip = frappe.db.get_value(
            "Cab Request",
            {
                "driver_id": self.driver_id,
                "status": "In Trip",
                "name": ["!=", self.name]
            },
            "name"
        )

        if in_trip:
            frappe.throw(_(
                f"Driver <b>{self.driver_id}</b> is currently on an active trip "
                f"(<b>{in_trip}</b>). Please assign a different driver or wait until "
                f"the current trip is Completed."
            ), title=_("Driver Unavailable"))

    # 8. 🚫 Prevent assigning a Cab that is currently In Trip
    def validate_cab_not_in_trip(self):
        if self.status != "Assigned" or not self.cab:
            return

        in_trip = frappe.db.get_value(
            "Cab Request",
            {
                "cab": self.cab,
                "status": "In Trip",
                "name": ["!=", self.name]
            },
            "name"
        )

        if in_trip:
            frappe.throw(_(
                f"Cab <b>{self.cab}</b> is currently on an active trip "
                f"(<b>{in_trip}</b>). Please assign a different cab or wait until "
                f"the current trip is Completed."
            ), title=_("Cab Unavailable"))

    # 9. 📧 Send Mail on status changes
    def send_status_mail(self):
        if self.is_new() or self.db_get("status") == self.status:
            return
 
        employee_email = frappe.db.get_value("Employee", self.employee_id, "personal_email")
        driver_email = None
        
        # Get Driver Email
        if self.driver_id:
            driver_employee = frappe.db.get_value("Driver", self.driver_id, "employee")
            if driver_employee:
                driver_email = frappe.db.get_value("Employee", driver_employee, "personal_email")
 
        # ✅ Assigned — notify Employee and Driver
        if self.status == "Assigned" and employee_email:
            frappe.sendmail(
                recipients=[employee_email],
                subject="Cab Request Assigned",
                message=f"""
                Hello {self.employee_name},<br><br>
                Your cab request is Assigned.<br>
                Driver: {self.assigned_driver}<br>
                Cab: {self.assigned_cab}<br>
                Pickup: {self.pickup_location}<br>
                Drop: {self.drop_location}<br><br>
                Regards
                """
            )
            
            if driver_email:
                frappe.sendmail(
                    recipients=[driver_email],
                    subject="New Cab Assignment",
                    message=f"""
                    You have been assigned a trip.<br><br>
                    Employee: {self.employee_name}<br>
                    Pickup: {self.pickup_location}<br>
                    Drop: {self.drop_location}<br>
                    Contact: {self.contact_no}
                    """
                )

        # 🚗 In Trip — notify Employee that driver has started
        if self.status == "In Trip" and employee_email:
            frappe.sendmail(
                recipients=[employee_email],
                subject="Your Cab is On the Way",
                message=f"""
                Hello {self.employee_name},<br><br>
                Your driver has started the trip.<br>
                Driver: {self.assigned_driver}<br>
                Cab: {self.assigned_cab}<br>
                Pickup: {self.pickup_location}<br><br>
                Regards
                """
            )

        # ✅ Completed — notify Employee trip is done
        if self.status == "Completed" and employee_email:
            frappe.sendmail(
                recipients=[employee_email],
                subject="Trip Completed",
                message=f"""
                Hello {self.employee_name},<br><br>
                Your trip has been completed successfully.<br>
                You may now book a new cab request if needed.<br><br>
                Regards
                """
            )

        # ❌ Rejected — notify Employee
        if self.status == "Rejected" and employee_email:
            frappe.sendmail(
                recipients=[employee_email],
                subject="Cab Request Rejected",
                message=f"""
                Hello {self.employee_name},<br><br>
                Your cab request was rejected.<br>
                Reason: {self.rejection_reason}<br><br>
                Regards
                """
            )

        # 🚫 Cancelled — notify Manager and Driver
        if self.status == "Cancelled":
            managers = frappe.get_all(
                "Has Role",
                filters={"role": "Fleet Manager", "parenttype": "User"},
                fields=["parent"]
            )
            manager_emails = [m["parent"] for m in managers]

            if manager_emails:
                frappe.sendmail(
                    recipients=manager_emails,
                    subject=f"Cab Request Cancelled - {self.name}",
                    message=f"""
                    Cab Request <b>{self.name}</b> has been cancelled by the employee.<br><br>
                    Employee: {self.employee_name}<br>
                    Driver: {self.assigned_driver}<br>
                    Cab: {self.assigned_cab}<br>
                    Pickup: {self.pickup_location}<br>
                    Drop: {self.drop_location}<br><br>
                    Please reassign the driver and cab as needed.
                    """
                )

            if driver_email:
                frappe.sendmail(
                    recipients=[driver_email],
                    subject=f"Trip Cancelled - {self.name}",
                    message=f"""
                    The trip <b>{self.name}</b> assigned to you has been cancelled by the employee.<br><br>
                    Employee: {self.employee_name}<br>
                    Pickup: {self.pickup_location}<br>
                    Drop: {self.drop_location}<br><br>
                    Please contact your manager for further instructions.
                    """
                )
 
 
# =========================================================
#  WHITELISTED METHODS (Outside the class)
# =========================================================

@frappe.whitelist()
def driver_start_trip(docname):
    """
    Called by the Driver's 'Start Trip' button.
    Changes status from Assigned → In Trip.
    Validates the caller is the assigned driver.
    """
    roles = frappe.get_roles()
    if "Driver" not in roles:
        frappe.throw(_("Only a Driver can start a trip."))

    doc = frappe.get_doc("Cab Request", docname)

    if doc.status != "Assigned":
        frappe.throw(_("Only an Assigned trip can be started."))

    # Verify the calling driver is the assigned driver for this trip
    current_user = frappe.session.user
    employee_id = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
    if employee_id:
        driver_name = frappe.db.get_value("Driver", {"employee": employee_id}, "name")
        if driver_name != doc.driver_id:
            frappe.throw(_("You are not the assigned driver for this trip."))

    doc.status = "In Trip"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return "success"


@frappe.whitelist()
def driver_complete_trip(docname):
    """
    Called by the Driver's 'Complete Trip' button.
    Changes status from In Trip → Completed.
    Validates the caller is the assigned driver.
    """
    roles = frappe.get_roles()
    if "Driver" not in roles:
        frappe.throw(_("Only a Driver can mark a trip as Completed."))

    doc = frappe.get_doc("Cab Request", docname)

    if doc.status != "In Trip":
        frappe.throw(_("Only a trip that is 'In Trip' can be marked as Completed."))

    # Verify the calling driver is the assigned driver for this trip
    current_user = frappe.session.user
    employee_id = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
    if employee_id:
        driver_name = frappe.db.get_value("Driver", {"employee": employee_id}, "name")
        if driver_name != doc.driver_id:
            frappe.throw(_("You are not the assigned driver for this trip."))

    doc.status = "Completed"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return "success"


@frappe.whitelist()
def employee_cancel_trip(docname):
    """
    Called by the Employee's 'Cancel Trip' button.
    Employee can cancel ONLY when status is Assigned (not once In Trip has started).
    """
    roles = frappe.get_roles()
    # Only pure employees (not managers/drivers) use this method
    if "Fleet Manager" in roles or "System Manager" in roles or "Driver" in roles:
        frappe.throw(_("This action is only for Employees."))

    doc = frappe.get_doc("Cab Request", docname)

    # Validate ownership — employee can only cancel their own request
    current_user = frappe.session.user
    employee_id = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
    if doc.employee_id != employee_id:
        frappe.throw(_("You can only cancel your own cab request."))

    if doc.status != "Assigned":
        frappe.throw(_(
            "You can only cancel a trip that is in <b>Assigned</b> status. "
            "Once the driver has started the trip (In Trip), cancellation is not allowed."
        ))

    doc.status = "Cancelled"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return "success"


@frappe.whitelist()
def get_employee_basic_details():
    employee = frappe.db.get_value(
        "Employee",
        {"user_id": frappe.session.user},
        ["name", "employee_name", "department", "cell_number"],
        as_dict=True,
    )
    return employee


# =========================================================
#  PERMISSION CODE (Outside the class)
# =========================================================
 
def get_permission_query_conditions(user):
    if not user: user = frappe.session.user
    roles = frappe.get_roles(user)
 
    # 1. Managers see everything
    if "Fleet Manager" in roles or "System Manager" in roles:
        return ""
 
    # 2. Drivers see only trips assigned to them
    if "Driver" in roles:
        employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if employee_id:
            driver_name = frappe.db.get_value("Driver", {"employee": employee_id}, "name")
            if driver_name:
                return f"`tabCab Request`.driver_id = '{driver_name}'"
        
        return "1=0" # If no driver found, show nothing
 
    # 3. Employees see their own requests only
    if "Employee" in roles:
        employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if employee_id:
            return f"`tabCab Request`.employee_id = '{employee_id}'"
 
    return ""
 
def has_permission(doc, user):
    if not user: user = frappe.session.user
    roles = frappe.get_roles(user)
 
    if "Fleet Manager" in roles or "System Manager" in roles:
        return True
 
    if "Driver" in roles:
        employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if employee_id:
            driver_name = frappe.db.get_value("Driver", {"employee": employee_id}, "name")
            return doc.driver_id == driver_name
            
    if "Employee" in roles:
        employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
        return doc.employee_id == employee_id
 
    return doc.owner == user


# =========================================================
#  ROUTE MATCHING & CAB BOOKING  (OpenStreetMap / Leaflet)
#  Added below — existing code above is untouched
# =========================================================

import math
import json


# ─── Geometry Helpers ────────────────────────────────────────────────────────

def _haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km between two lat/lng points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi   = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_to_segment_km(px, py, ax, ay, bx, by):
    """Shortest distance (km) from point P to line segment A→B."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-12:
        return _haversine_km(px, py, ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return _haversine_km(px, py, ax + t * dx, ay + t * dy)


def _nearest_stop_on_route(emp_lat, emp_lng, waypoints):
    """
    Returns (min_stop_dist_km, nearest_stop_dict, min_segment_dist_km)
    Checks distance to every stop AND every segment between stops.
    """
    min_stop_dist = float("inf")
    nearest_stop  = None

    for wp in waypoints:
        d = _haversine_km(emp_lat, emp_lng, wp["latitude"], wp["longitude"])
        if d < min_stop_dist:
            min_stop_dist = d
            nearest_stop  = wp

    # Also check perpendicular distance to each route segment
    min_seg_dist = min_stop_dist
    sorted_wps   = sorted(waypoints, key=lambda w: w.get("sequence", 0))
    for i in range(len(sorted_wps) - 1):
        a, b = sorted_wps[i], sorted_wps[i + 1]
        d = _point_to_segment_km(
            emp_lat, emp_lng,
            a["latitude"], a["longitude"],
            b["latitude"], b["longitude"],
        )
        if d < min_seg_dist:
            min_seg_dist = d

    return min_stop_dist, nearest_stop, min_seg_dist


# ─── Seat Availability ───────────────────────────────────────────────────────

def _get_booked_seat_count(route_name, travel_date, shift_type):
    """Count confirmed bookings for a route on a given date + shift."""
    return frappe.db.count(
        "Cab Request",
        filters={
            "assigned_route": route_name,
            "travel_date":    travel_date,
            "shift_type":     shift_type,
            "status":         ["in", ["Assigned", "In Trip", "Completed"]],
        },
    )


# ─── Find Matching Cabs ──────────────────────────────────────────────────────

@frappe.whitelist()
def find_matching_cabs(employee_lat, employee_lng, travel_date, shift_type, threshold_km=1.5):
    """
    Find all Active Cab Routes whose path passes within threshold_km of
    the employee's pickup point AND still have available seats.
    Returns list sorted by distance (nearest first).
    Called from cab_request.js Leaflet dialog.
    """
    emp_lat   = float(employee_lat)
    emp_lng   = float(employee_lng)
    threshold = float(threshold_km)

    routes = frappe.get_all(
        "Cab Route",
        filters={"status": "Active", "shift_type": shift_type},
        fields=[
            "name", "route_name", "route_code",
            "vehicle", "license_plate",
            "driver_name", "driver_contact",
            "total_seats", "shift_time",
            "start_location", "start_lat", "start_lng",
            "end_location",   "end_lat",   "end_lng",
        ],
    )

    results = []

    for route in routes:
        waypoints_raw = frappe.get_all(
            "Route Waypoint",
            filters={"parent": route["name"]},
            fields=["stop_name", "landmark", "latitude", "longitude",
                    "sequence", "pickup_time", "stop_type", "address"],
        )

        # Build full path: start → waypoints → end
        all_points = (
            [{
                "stop_name":   route["start_location"],
                "latitude":    route["start_lat"],
                "longitude":   route["start_lng"],
                "sequence":    0,
                "pickup_time": str(route.get("shift_time") or ""),
                "stop_type":   "Pickup",
                "landmark":    "",
            }]
            + waypoints_raw
            + [{
                "stop_name":   route["end_location"],
                "latitude":    route["end_lat"],
                "longitude":   route["end_lng"],
                "sequence":    9999,
                "pickup_time": "",
                "stop_type":   "Drop",
                "landmark":    "",
            }]
        )

        if len(all_points) < 2:
            continue

        min_stop_dist, nearest_stop, min_seg_dist = _nearest_stop_on_route(
            emp_lat, emp_lng, all_points
        )
        effective_dist = min(min_stop_dist, min_seg_dist)

        if effective_dist > threshold:
            continue

        booked    = _get_booked_seat_count(route["name"], travel_date, shift_type)
        available = route["total_seats"] - booked

        if available <= 0:
            continue

        results.append({
            "route":               route["name"],
            "route_name":          route["route_name"],
            "route_code":          route.get("route_code", ""),
            "vehicle":             route["vehicle"],
            "license_plate":       route.get("license_plate", ""),
            "driver_name":         route.get("driver_name", ""),
            "driver_contact":      route.get("driver_contact", ""),
            "total_seats":         route["total_seats"],
            "booked_seats":        booked,
            "available_seats":     available,
            "shift_time":          str(route.get("shift_time") or ""),
            "shift_type":          shift_type,
            "distance_from_route": round(effective_dist, 2),
            "nearest_stop":        nearest_stop.get("stop_name", "") if nearest_stop else "",
            "nearest_stop_lat":    nearest_stop.get("latitude")      if nearest_stop else None,
            "nearest_stop_lng":    nearest_stop.get("longitude")     if nearest_stop else None,
            "nearest_pickup_time": nearest_stop.get("pickup_time", "") if nearest_stop else "",
            "start_location":      route["start_location"],
            "end_location":        route["end_location"],
            "waypoints":           all_points,
        })

    results.sort(key=lambda x: x["distance_from_route"])
    return results


# ─── Book Cab ────────────────────────────────────────────────────────────────

@frappe.whitelist()
def book_route_cab(cab_request_name, route_name,
                   pickup_lat=None, pickup_lng=None, pickup_address=None,
                   nearest_stop=None, nearest_pickup_time=None, distance_from_route=None):
    """
    Confirm route-based cab booking on a Cab Request.
    Updates assignment fields and sends confirmation email.
    Named book_route_cab to avoid any conflict with existing booking logic.
    """
    doc   = frappe.get_doc("Cab Request", cab_request_name)
    route = frappe.get_doc("Cab Route", route_name)

    # Re-check seat availability (race-condition safe)
    booked = _get_booked_seat_count(route_name, doc.travel_date, doc.shift_type)
    if booked >= route.total_seats:
        frappe.throw(_("No seats available on this route. Please choose another cab."))

    # Update assignment fields on the Cab Request
    doc.assigned_route    = route_name
    doc.assigned_cab      = route.vehicle          # maps to your existing assigned_cab field
    doc.assigned_driver   = route.driver_name      # maps to your existing assigned_driver field

    if pickup_lat:            doc.pickup_lat            = float(pickup_lat)
    if pickup_lng:            doc.pickup_lng            = float(pickup_lng)
    if pickup_address:        doc.pickup_location       = pickup_address   # your existing pickup_location field
    if nearest_stop:          doc.nearest_stop          = nearest_stop
    if distance_from_route:   doc.distance_from_route   = float(distance_from_route)
    if nearest_pickup_time:   doc.estimated_pickup_time = nearest_pickup_time

    doc.status    = "Assigned"   # use your existing status flow
    doc.booked_on = now_datetime()
    doc.save(ignore_permissions=True)

    # Send confirmation email using existing employee email lookup
    _send_route_booking_email(doc, route)

    frappe.db.commit()

    return {
        "status":  "success",
        "message": f"Cab booked! Vehicle: {route.vehicle} | Route: {route.route_name}",
    }


def _send_route_booking_email(cab_request_doc, route_doc):
    """Send booking confirmation — reuses same email style as existing send_status_mail."""
    try:
        employee_email = frappe.db.get_value(
            "Employee", cab_request_doc.employee_id, "personal_email"
        )
        if not employee_email:
            return

        frappe.sendmail(
            recipients=[employee_email],
            subject="Cab Booking Confirmed",
            message=f"""
            Hello {cab_request_doc.employee_name},<br><br>
            Your cab has been booked successfully via route matching.<br><br>
            Route: {route_doc.route_name}<br>
            Vehicle: {route_doc.vehicle} ({route_doc.license_plate or ''})<br>
            Driver: {route_doc.driver_name or 'TBD'} | {route_doc.driver_contact or ''}<br>
            Nearest Stop: {cab_request_doc.nearest_stop or 'On Route'}<br>
            Est. Pickup Time: {cab_request_doc.estimated_pickup_time or route_doc.shift_time}<br>
            Travel Date: {cab_request_doc.travel_date}<br>
            Shift: {cab_request_doc.shift_type}<br><br>
            Regards
            """
        )
    except Exception as e:
        frappe.log_error(str(e), "Route Cab Booking Email Error")


# ─── Cancel Route Booking ────────────────────────────────────────────────────

@frappe.whitelist()
def cancel_route_booking(cab_request_name):
    """Cancel a route-based cab booking and reset assignment fields."""
    doc = frappe.get_doc("Cab Request", cab_request_name)

    if doc.status not in ("Assigned",):
        frappe.throw(_("Only Assigned bookings can be cancelled."))

    doc.status          = "Cancelled"
    doc.assigned_route  = None
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"status": "success", "message": "Booking cancelled successfully."}


# ─── GeoJSON Generator (called from hooks.py on Cab Route save) ─────────────

def generate_route_geojson(doc, method=None):
    """
    Build GeoJSON LineString from start → waypoints → end
    and store in route_polyline field. Hooked via hooks.py before_save.
    """
    waypoints = sorted(doc.waypoints or [], key=lambda w: w.sequence)

    coords = [[doc.start_lng, doc.start_lat]]
    for wp in waypoints:
        coords.append([wp.longitude, wp.latitude])
    coords.append([doc.end_lng, doc.end_lat])

    doc.route_polyline = json.dumps({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "route_name": doc.route_name,
            "shift_type": doc.shift_type,
        },
    })
