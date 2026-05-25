import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime, add_to_date, flt
from frappe import _
from transport_management.transport_management.cab_status import (
    apply_status_transition,
    is_valid_transition,
)
import math
import json


class CabRequest(Document):

    def validate(self):
        self.validate_dates()
        # Skip the 1-hour cutoff check when auto-booking sets status to Assigned
        # (book_route_cab calls save with ignore_permissions and sets status directly)
        if self.status not in ("Assigned", "In Trip", "Completed", "Cancelled"):
            self.validate_booking_one_hour_before()
        self.prevent_employee_status_change()
        self.validate_driver_status_change()
        self.validate_employee_active_booking()
        self.validate_driver_not_in_trip()
        self.validate_cab_not_in_trip()
        self.set_total_distance()
        self.validate_status_transition()

    # ─────────────────────────────────────────
    # TRIP DISTANCE (from odometer readings)
    # ─────────────────────────────────────────
    def set_total_distance(self):
        """Derive total_distance from the recorded odometer readings.

        Odometer fields are integers, so 0 means "not recorded" — distance is
        only computed once BOTH readings are entered. This runs on every normal
        save, so the driver simply records start/end odometer and saves.
        """
        start = flt(self.start_odometer)
        end = flt(self.end_odometer)

        if not start or not end:
            return

        if end < start:
            frappe.throw(_(
                "End Odometer ({0}) cannot be less than Start Odometer ({1})."
            ).format(int(end), int(start)), title=_("Invalid Odometer Reading"))

        self.total_distance = end - start

    # ─────────────────────────────────────────
    # STATUS STATE MACHINE & AUDIT (Phase 4)
    # ─────────────────────────────────────────
    def validate_status_transition(self):
        """Gate manual (form) status edits against the allowed-transitions map.

        API status changes go through cab_status.apply_status_transition and
        bypass validate(); this guards only desk-form edits. System Managers
        keep an override so admins can correct data.
        """
        if self.is_new():
            return
        before = self.get_doc_before_save()
        if not before or before.status == self.status:
            return
        if "System Manager" in frappe.get_roles():
            return
        if not is_valid_transition(before.status, self.status):
            frappe.throw(
                _("Status change {0} → {1} is not allowed.").format(
                    before.status or _("(none)"), self.status),
                title=_("Invalid Status Transition"),
            )

    def on_update(self):
        self._log_manual_status_change()

    def _log_manual_status_change(self):
        """Audit a status change made through a normal form save.

        API transitions are logged by apply_status_transition itself — those
        use db.set_value, which does not trigger on_update — so there is no
        double-logging here.
        """
        before = self.get_doc_before_save()
        if not before or before.status == self.status:
            return
        from transport_management.transport_management.cab_status import log_status_change
        log_status_change(self.name, before.status, self.status, source="Manual Edit")

    # ─────────────────────────────────────────
    # 1. DATE & TIME VALIDATION
    # ─────────────────────────────────────────
    def validate_dates(self):
        # Only enforce the future-date rule while the booking is still being
        # placed (new or Pending). Never block edits of in-progress/closed trips.
        if not (self.is_new() or self.status == "Pending"):
            return
        if self.booking_datetime:
            if get_datetime(self.booking_datetime) < now_datetime():
                frappe.throw(_("Booking cannot be in the past. Please select a future time."))

    # ─────────────────────────────────────────
    # 2. Must book at least 1 hour before
    #    (skipped for already-assigned/in-progress bookings)
    # ─────────────────────────────────────────
    def validate_booking_one_hour_before(self):
        if self.booking_datetime:
            booking_dt = get_datetime(self.booking_datetime)
            if booking_dt < add_to_date(now_datetime(), hours=1):
                frappe.throw(_(
                    "Cab must be booked at least <b>1 hour</b> before the trip time. "
                    "Please select a time that is at least 1 hour from now."
                ))

    # ─────────────────────────────────────────
    # 3. Prevent Employee from changing status directly
    # ─────────────────────────────────────────
    def prevent_employee_status_change(self):
        if self.is_new():
            return

        roles = frappe.get_roles()
        allowed_roles = ["Fleet Manager", "System Manager", "Driver"]
        if "Employee" in roles and not any(role in roles for role in allowed_roles):
            old_status = self.db_get("status")
            if old_status != self.status and self.status != "Cancelled":
                frappe.throw(_("Employees are not allowed to change the status directly."))

    # ─────────────────────────────────────────
    # 4. Validate Driver status transitions
    # ─────────────────────────────────────────
    def validate_driver_status_change(self):
        if self.is_new():
            return

        roles = frappe.get_roles()
        old_status = self.db_get("status")

        if old_status == self.status:
            return

        if self.status in ["In Trip", "Completed"]:
            if "Driver" not in roles and "Fleet Manager" not in roles and "System Manager" not in roles:
                frappe.throw(_("Only the assigned Driver can update the trip status to In Trip or Completed."))

    # ─────────────────────────────────────────
    # 5. Prevent double-booking
    # ─────────────────────────────────────────
    def validate_employee_active_booking(self):
        if not self.is_new():
            return

        if not self.employee_id:
            return

        roles = frappe.get_roles()
        if "Fleet Manager" in roles or "System Manager" in roles or "Driver" in roles:
            return

        existing = frappe.db.get_value(
            "Cab Request",
            {
                "employee_id": self.employee_id,
                "status": ["in", ["Assigned", "In Trip"]],
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
                    f"You can only book a new cab after your current trip is <b>Completed</b>."
                ),
                title=_("Booking Not Allowed")
            )

    # ─────────────────────────────────────────
    # 6. Prevent assigning a Driver who is In Trip
    # ─────────────────────────────────────────
    def validate_driver_not_in_trip(self):
        if not self.assigned_driver:
            return

        in_trip = frappe.db.get_value(
            "Cab Request",
            {
                "assigned_driver": self.assigned_driver,
                "status": "In Trip",
                "name": ["!=", self.name]
            },
            "name"
        )

        if in_trip:
            frappe.throw(_(
                f"Driver <b>{self.assigned_driver}</b> is currently on an active trip "
                f"(<b>{in_trip}</b>). Please wait until the current trip is Completed."
            ), title=_("Driver Unavailable"))

    # ─────────────────────────────────────────
    # 7. Prevent assigning a Cab that is In Trip
    # ─────────────────────────────────────────
    def validate_cab_not_in_trip(self):
        if not self.assigned_cab:
            return

        in_trip = frappe.db.get_value(
            "Cab Request",
            {
                "assigned_cab": self.assigned_cab,
                "status": "In Trip",
                "name": ["!=", self.name]
            },
            "name"
        )

        if in_trip:
            frappe.throw(_(
                f"Vehicle <b>{self.assigned_cab}</b> is currently on an active trip "
                f"(<b>{in_trip}</b>). Please wait until the current trip is Completed."
            ), title=_("Vehicle Unavailable"))


# =========================================================
#  PERMISSION QUERY
# =========================================================

def get_permission_query_conditions(user):
    if not user:
        user = frappe.session.user
    roles = frappe.get_roles(user)

    if "Fleet Manager" in roles or "System Manager" in roles:
        return ""

    conditions = []

    if "Driver" in roles:
        driver_candidates = _get_driver_identity_candidates(user)
        if driver_candidates:
            escaped = ", ".join(frappe.db.escape(v) for v in sorted(driver_candidates))
            conditions.append(f"`tabCab Request`.assigned_driver IN ({escaped})")
        else:
            conditions.append("1=0")

    if "Employee" in roles:
        employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if employee_id:
            conditions.append(
                f"`tabCab Request`.employee_id = {frappe.db.escape(employee_id)}"
            )

    if conditions:
        return "( " + " OR ".join(conditions) + " )"

    # No role-based condition matched — deny by default.
    # (Previously returned "" which Frappe treats as NO filter = full access.)
    return "1=0"


def has_permission(doc, ptype=None, user=None):
    if not user:
        user = frappe.session.user
    roles = frappe.get_roles(user)

    if "Fleet Manager" in roles or "System Manager" in roles:
        return True

    if "Driver" in roles:
        driver_candidates = _get_driver_identity_candidates(user)
        if getattr(doc, "assigned_driver", None) in driver_candidates:
            return True

    if "Employee" in roles:
        employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if doc.employee_id == employee_id:
            return True

    return doc.owner == user


ALLOWED_REQUEST_ROLES = {"Employee", "Driver", "Fleet Manager", "System Manager"}


def _is_manager(roles=None):
    roles = roles if roles is not None else frappe.get_roles()
    return "Fleet Manager" in roles or "System Manager" in roles


def _is_request_owner(doc, user=None):
    """True when `user` is the Employee who owns this Cab Request."""
    user = user or frappe.session.user
    if getattr(doc, "owner", None) == user:
        return True
    employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
    return bool(employee_id) and getattr(doc, "employee_id", None) == employee_id


def _is_assigned_driver(doc, user=None):
    """True when `user` resolves to one of the identifiers stored in `assigned_driver`."""
    user = user or frappe.session.user
    assigned = getattr(doc, "assigned_driver", None)
    if not assigned:
        return False
    return assigned in _get_driver_identity_candidates(user)


def _get_driver_identity_candidates(user):
    """
    Return all possible identifiers that might be stored in Cab Request.assigned_driver
    for a driver user.
    """
    candidates = set()
    candidates.add(user)

    # 1) Direct Driver mapping by custom_user (works even when Employee link is missing)
    linked_driver = frappe.db.get_value("Driver", {"custom_user": user}, "name")
    if linked_driver:
        candidates.add(linked_driver)
        driver_full_name = frappe.db.get_value("Driver", linked_driver, "full_name")
        if driver_full_name:
            candidates.add(driver_full_name)
        linked_employee = frappe.db.get_value("Driver", linked_driver, "employee")
        if linked_employee:
            candidates.add(linked_employee)
            linked_employee_name = frappe.db.get_value("Employee", linked_employee, "employee_name")
            if linked_employee_name:
                candidates.add(linked_employee_name)

    # 2) Employee -> Driver mapping
    employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if employee_id:
        candidates.add(employee_id)
        emp_name = frappe.db.get_value("Employee", employee_id, "employee_name")
        if emp_name:
            candidates.add(emp_name)

        driver_id = frappe.db.get_value("Driver", {"employee": employee_id}, "name")
        if driver_id:
            candidates.add(driver_id)
            driver_full_name = frappe.db.get_value("Driver", driver_id, "full_name")
            if driver_full_name:
                candidates.add(driver_full_name)

    # 3) Fallback by User full name -> Driver.full_name
    user_full_name = frappe.db.get_value("User", user, "full_name")
    if user_full_name:
        candidates.add(user_full_name)
        driver_by_name = frappe.db.get_value("Driver", {"full_name": user_full_name}, "name")
        if driver_by_name:
            candidates.add(driver_by_name)
            employee_by_name = frappe.db.get_value("Driver", driver_by_name, "employee")
            if employee_by_name:
                candidates.add(employee_by_name)
                employee_name = frappe.db.get_value("Employee", employee_by_name, "employee_name")
                if employee_name:
                    candidates.add(employee_name)

    return {c for c in candidates if c}


# =========================================================
#  GEOMETRY HELPERS
# =========================================================

def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_to_segment_km(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-12:
        return _haversine_km(px, py, ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return _haversine_km(px, py, ax + t * dx, ay + t * dy)


def _distance_from_route(emp_lat, emp_lng, waypoints):
    sorted_wps = sorted(waypoints, key=lambda w: w.get("sequence", 0))
    min_dist   = float("inf")

    for wp in sorted_wps:
        d = _haversine_km(emp_lat, emp_lng, wp["latitude"], wp["longitude"])
        if d < min_dist:
            min_dist = d

    for i in range(len(sorted_wps) - 1):
        a, b = sorted_wps[i], sorted_wps[i + 1]
        d = _point_to_segment_km(
            emp_lat, emp_lng,
            a["latitude"], a["longitude"],
            b["latitude"], b["longitude"],
        )
        if d < min_dist:
            min_dist = d

    return round(min_dist, 2)


# =========================================================
#  SEAT AVAILABILITY
#  FIX: Count uses BOTH assigned_route name AND travel_date.
#       travel_date is stored as DATE field set from booking_datetime.
#       We also accept booking_datetime date part as fallback so
#       counts always match regardless of which field is set.
# =========================================================

def _get_booked_seat_count(route_name, travel_date):
    """
    Count confirmed bookings for a route on a given travel date.
    FIX: Counts against BOTH travel_date field AND booking_datetime date part
         to handle cases where travel_date may not be set yet but
         booking_datetime is. Uses OR condition to catch all cases.
    """
    if not travel_date:
        return 0

    # Primary count: using travel_date field (set by book_route_cab)
    count_by_travel_date = frappe.db.count(
        "Cab Request",
        filters={
            "assigned_route": route_name,
            "travel_date":    travel_date,
            "status":         ["in", ["Assigned", "In Trip", "Completed"]],
        },
    )

    # Secondary count: using booking_datetime date part
    # This catches bookings where travel_date wasn't set but booking_datetime matches
    count_by_booking_date = frappe.db.sql("""
        SELECT COUNT(*) as cnt
        FROM `tabCab Request`
        WHERE assigned_route = %(route)s
          AND DATE(booking_datetime) = %(date)s
          AND status IN ('Assigned', 'In Trip', 'Completed')
          AND (travel_date IS NULL OR travel_date = '')
    """, {"route": route_name, "date": travel_date}, as_dict=True)

    secondary = count_by_booking_date[0]["cnt"] if count_by_booking_date else 0

    return count_by_travel_date + secondary


def _get_booked_seat_counts(route_names, travel_date):
    """Batched seat-count for many routes on one date.

    Returns {route_name: booked_count}. Same semantics as
    `_get_booked_seat_count` (counts Assigned/In Trip/Completed against both
    `travel_date` and `DATE(booking_datetime)`), but in a single SQL pass —
    so a 20-route fleet stays O(1) queries instead of O(40).
    """
    if not route_names or not travel_date:
        return {name: 0 for name in (route_names or [])}

    rows = frappe.db.sql(
        """
        SELECT assigned_route, COUNT(*) AS cnt
        FROM `tabCab Request`
        WHERE assigned_route IN %(routes)s
          AND status IN ('Assigned', 'In Trip', 'Completed')
          AND (
                travel_date = %(date)s
             OR ((travel_date IS NULL OR travel_date = '')
                 AND DATE(booking_datetime) = %(date)s)
          )
        GROUP BY assigned_route
        """,
        {"routes": tuple(route_names), "date": travel_date},
        as_dict=True,
    )

    counts = {name: 0 for name in route_names}
    for r in rows:
        if r["assigned_route"] in counts:
            counts[r["assigned_route"]] = int(r["cnt"])
    return counts


# =========================================================
#  AUTO-FETCH EMPLOYEE DETAILS
# =========================================================

@frappe.whitelist()
def get_employee_basic_details():
    """
    Returns the logged-in user's Employee record for auto-fill.
    """
    user = frappe.session.user

    employee = frappe.db.get_value(
        "Employee",
        {"user_id": user},
        ["name", "employee_name", "department", "cell_number", "personal_email"],
        as_dict=True,
    )

    return employee


# =========================================================
#  FIND MATCHING CABS
#  FIX: Always queries DB fresh — no server-side caching.
#       Returns accurate booked/available counts every call.
#       Also returns route_name (display) separately from route (internal ID).
# =========================================================

@frappe.whitelist()
def find_matching_cabs(employee_lat, employee_lng, travel_date, threshold_km=5.0):
    """
    Find all Active Cab Routes within threshold_km of the employee's pickup.
    Returns list sorted by distance_from_route ascending.
    FIX: Seat counts are always fetched live from DB, never cached.
    """
    if not (set(frappe.get_roles()) & ALLOWED_REQUEST_ROLES):
        frappe.throw(_("You are not authorised to search cabs."), frappe.PermissionError)

    emp_lat   = float(employee_lat)
    emp_lng   = float(employee_lng)
    threshold = float(threshold_km)

    routes = frappe.get_all(
        "Cab Route",
        filters={"status": "Active"},
        fields=[
            "name", "route_name", "vehicle",
            "driver_name", "driver_contact",
            "total_seats", "shift_time",
            "start_location", "start_lat", "start_lng",
            "end_location",   "end_lat",   "end_lng",
        ]
    )

    seat_counts = _get_booked_seat_counts([r["name"] for r in routes], travel_date)

    results = []

    for route in routes:
        waypoints_raw = frappe.get_all(
            "Route Waypoint",
            filters={"parent": route["name"]},
            fields=["stop_name", "latitude", "longitude", "sequence", "pickup_time"],
        )

        all_points = (
            [{
                "stop_name":   route["start_location"],
                "latitude":    route["start_lat"],
                "longitude":   route["start_lng"],
                "sequence":    0,
                "pickup_time": str(route.get("shift_time") or ""),
            }]
            + list(waypoints_raw)
            + [{
                "stop_name":   route["end_location"],
                "latitude":    route["end_lat"],
                "longitude":   route["end_lng"],
                "sequence":    9999,
                "pickup_time": "",
            }]
        )

        if len(all_points) < 2:
            continue

        dist_km = _distance_from_route(emp_lat, emp_lng, all_points)

        if dist_km > threshold:
            continue

        # FIX: Always fetch live seat count from DB for this route+date
        booked    = seat_counts.get(route["name"], 0)
        available = max(0, (route["total_seats"] or 0) - booked)

        results.append({
            "route":               route["name"],          # internal DocName
            "route_name":          route["route_name"],    # display name
            "vehicle":             route["vehicle"],
            "license_plate":       route.get("license_plate") or route.get("vehicle") or "",
            "driver_name":         route.get("driver_name", ""),
            "driver_contact":      route.get("driver_contact", ""),
            "total_seats":         int(route["total_seats"] or 0),
            "booked_seats":        booked,
            "available_seats":     available,
            "shift_time":          str(route.get("shift_time") or ""),
            "distance_from_route": dist_km,
            "start_location":      route["start_location"],
            "end_location":        route["end_location"],
            "waypoints":           all_points,
        })

    results.sort(key=lambda x: x["distance_from_route"])
    return results


# =========================================================
#  AUTO BOOK ROUTE CAB
#  FIX: Stores route_name (display name) in a separate fetch
#       so the booking card shows the human-readable name.
#       Also ensures travel_date is always set from booking_datetime.
# =========================================================

@frappe.whitelist()
def book_route_cab(cab_request_name, route_name, distance_from_route=None):
    """
    Auto-confirm route booking when employee selects a cab.
    FIX: Sets travel_date from booking_datetime so seat counts always work.
         Re-checks seat count at booking time to prevent race conditions.
    """
    import secrets

    # ── Validate doc exists ───────────────────────────────────────────────
    if not frappe.db.exists("Cab Request", cab_request_name):
        return {
            "status":  "error",
            "message": f"Cab Request '{cab_request_name}' was not found. "
                       "Please try again."
        }

    doc   = frappe.get_doc("Cab Request", cab_request_name)
    route = frappe.get_doc("Cab Route", route_name)

    # Only the employee who owns this request (or a manager) may book it.
    # Without this, any authenticated employee could hijack another employee's
    # pending request by supplying its docname.
    roles = frappe.get_roles()
    if not _is_manager(roles) and not _is_request_owner(doc):
        frappe.throw(
            _("You can only book a cab for your own request."),
            frappe.PermissionError,
        )

    # ── Extract travel date from booking_datetime ─────────────────────────
    travel_date = None
    if doc.booking_datetime:
        travel_date = str(doc.booking_datetime)[:10]

    # ── Re-check seat availability at booking time (race condition guard) ──
    # Lock the route row so concurrent bookings for the last seat serialise.
    frappe.db.get_value("Cab Route", route_name, "name", for_update=True)
    booked = _get_booked_seat_count(route_name, travel_date)
    if booked >= (route.total_seats or 0):
        return {
            "status":  "error",
            "message": "No seats available on this route. Please choose another cab."
        }

    # ── Check employee doesn't already have an active booking ─────────────
    existing = frappe.db.get_value(
        "Cab Request",
        {
            "employee_id": doc.employee_id,
            "status": ["in", ["Assigned", "In Trip"]],
            "name": ["!=", cab_request_name]
        },
        ["name", "status"],
        as_dict=True
    )
    if existing:
        return {
            "status":  "error",
            "message": f"You already have an active booking ({existing['name']}) with status {existing['status']}. "
                       "Please complete or cancel it before booking again."
        }

    # ── Generate 6-digit OTP ──────────────────────────────────────────────
    # Use `secrets` (CSPRNG) so the OTP cannot be predicted from prior samples.
    otp = str(secrets.randbelow(900000) + 100000)

    # ── FIX: Also store route display name for easy retrieval ─────────────
    # assigned_route stores internal DocName (e.g. CAB-ROUTE-001)
    # We set shift_time from route so the booking card can display it
    update_fields = {
        "assigned_route":      route_name,
        "assigned_cab":        route.vehicle or "",
        "assigned_driver":     route.driver_name or "",
        "shift_time":          str(route.shift_time or ""),
        "distance_from_route": float(distance_from_route) if distance_from_route else None,
        "travel_date":         travel_date,
        "otp":                 otp,
    }

    # ── Apply the Assigned transition via the central state machine ───────
    # Validates Pending → Assigned and writes a Cab Request Status Log entry;
    # update_fields is written in the same db.set_value, bypassing validate.
    apply_status_transition(
        cab_request_name, "Assigned", source="Auto Assign", extra_fields=update_fields
    )

    frappe.db.commit()

    # ── Reload doc for email sending ──────────────────────────────────────
    doc.reload()

    # ── Send emails ───────────────────────────────────────────────────────
    _send_route_booking_email(doc, route, otp)

    return {
        "status":  "success",
        "otp":     otp,
        "message": f"Cab booked! Vehicle: {route.vehicle} | Route: {route.route_name}",
        "booking_details": {
            "route":          route.route_name,
            "vehicle":        route.vehicle,
            "driver":         route.driver_name,
            "driver_contact": getattr(route, "driver_contact", ""),
            "shift_time":     str(route.shift_time or ""),
            "travel_date":    travel_date,
            "pickup":         doc.pickup_location,
            "distance":       distance_from_route,
        }
    }


# =========================================================
#  BOOKING EMAIL
# =========================================================

def _send_route_booking_email(cab_request_doc, route_doc, otp=None):
    try:
        travel_date = str(cab_request_doc.booking_datetime)[:10] if cab_request_doc.booking_datetime else "—"

        otp_section = ""
        if otp:
            otp_section = f"""
            <div style="background:#0d6efd;color:#fff;border-radius:10px;padding:16px;
                        text-align:center;margin:14px 0;">
                <div style="font-size:12px;opacity:0.8;margin-bottom:6px;">YOUR TRIP OTP</div>
                <div style="font-size:36px;font-weight:900;letter-spacing:10px;
                            font-family:monospace;">{otp}</div>
                <div style="font-size:11px;opacity:0.7;margin-top:6px;">
                    Share this with your driver to start the trip
                </div>
            </div>
            <p style="color:#856404;background:#fff3cd;padding:10px;border-radius:6px;font-size:12px;">
                ⚠️ Do not share this OTP with anyone except your assigned driver.
            </p>
            """

        # ── Notify Employee ──────────────────────────────────────────────────
        employee_email = frappe.db.get_value(
            "Employee", cab_request_doc.employee_id, "personal_email"
        )
        if employee_email:
            frappe.sendmail(
                recipients=[employee_email],
                subject="✅ Cab Booking Confirmed — Your Trip OTP Inside",
                message=f"""
                Hello {cab_request_doc.employee_name},<br><br>
                Your cab has been booked and auto-assigned successfully.<br><br>
                Route: {route_doc.route_name}<br>
                Vehicle: {route_doc.vehicle}<br>
                Driver: {route_doc.driver_name or 'TBD'}<br>
                Pickup: {cab_request_doc.pickup_location or '—'}<br>
                Distance from route: {cab_request_doc.distance_from_route or '—'} km<br>
                Travel Date: {travel_date}<br>
                Shift Time: {route_doc.shift_time or '—'}<br><br>
                {otp_section}
                Regards
                """
            )

        # ── Notify Driver ────────────────────────────────────────────────────
        if route_doc.driver_name:
            driver_emp_email = frappe.db.get_value(
                "Employee", {"employee_name": route_doc.driver_name}, "personal_email"
            )
            if driver_emp_email:
                frappe.sendmail(
                    recipients=[driver_emp_email],
                    subject=f"🚗 New Passenger Assigned — {cab_request_doc.employee_name}",
                    message=f"""
                    Hello {route_doc.driver_name},<br><br>
                    A new passenger has been assigned to your route.<br><br>
                    Employee: {cab_request_doc.employee_name}<br>
                    Contact: {cab_request_doc.contact_no or '—'}<br>
                    Pickup Location: {cab_request_doc.pickup_location or '—'}<br>
                    Distance from route: {cab_request_doc.distance_from_route or '—'} km<br>
                    Travel Date: {travel_date}<br>
                    Route: {route_doc.route_name}<br>
                    Shift Time: {route_doc.shift_time or '—'}<br><br>
                    Please verify the employee's OTP when they board to start the trip.<br><br>
                    Regards
                    """
                )

        # ── Notify Fleet Managers ────────────────────────────────────────────
        managers = frappe.get_all(
            "Has Role",
            filters={"role": ["in", ["Fleet Manager", "System Manager"]], "parenttype": "User"},
            fields=["parent"]
        )
        mgr_emails = [m["parent"] for m in managers if m["parent"] != "Administrator"]
        if mgr_emails:
            frappe.sendmail(
                recipients=mgr_emails,
                subject=f"📋 Cab Auto-Assigned — {cab_request_doc.name}",
                message=f"""
                A new cab booking has been auto-assigned.<br><br>
                Booking Ref: {cab_request_doc.name}<br>
                Employee: {cab_request_doc.employee_name} ({cab_request_doc.employee_id or '—'})<br>
                Route: {route_doc.route_name}<br>
                Vehicle: {route_doc.vehicle}<br>
                Driver: {route_doc.driver_name or 'TBD'}<br>
                Pickup: {cab_request_doc.pickup_location or '—'}<br>
                Travel Date: {travel_date}<br>
                Shift Time: {route_doc.shift_time or '—'}<br><br>
                Regards
                """
            )

    except Exception as e:
        frappe.log_error(str(e), "Route Cab Booking Email Error")


# =========================================================
#  CANCEL ROUTE BOOKING
# =========================================================

@frappe.whitelist()
def cancel_route_booking(cab_request_name):
    doc = frappe.get_doc("Cab Request", cab_request_name)

    if doc.status not in ("Assigned", "Pending"):
        frappe.throw(_(
            "You can only cancel a booking with status <b>Pending</b> or <b>Assigned</b>. "
            "Once the driver has started the trip (In Trip), cancellation is not allowed."
        ))

    roles = frappe.get_roles()
    if "Fleet Manager" not in roles and "System Manager" not in roles:
        current_user = frappe.session.user
        employee_id  = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
        if doc.employee_id != employee_id:
            frappe.throw(_("You can only cancel your own cab booking."))

    apply_status_transition(cab_request_name, "Cancelled", source="Booking Cancelled")
    frappe.db.commit()
    return {"status": "success", "message": "Booking cancelled."}


# =========================================================
#  GET TRIP OTP
# =========================================================

@frappe.whitelist()
def get_otp(docname):
    doc = frappe.get_doc("Cab Request", docname)

    current_user = frappe.session.user
    employee_id  = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
    roles        = frappe.get_roles()
    is_manager   = "Fleet Manager" in roles or "System Manager" in roles

    if not is_manager and doc.employee_id != employee_id:
        frappe.throw(_("You are not authorised to view this OTP."), frappe.PermissionError)

    if not doc.otp:
        return {"otp": None, "message": "No OTP found for this booking."}

    return {"otp": doc.otp}


# =========================================================
#  VERIFY OTP & START TRIP
# =========================================================

@frappe.whitelist()
def verify_otp_and_start_trip(docname, entered_otp):
    roles = frappe.get_roles()
    if "Driver" not in roles and "Fleet Manager" not in roles and "System Manager" not in roles:
        frappe.throw(_("Only a Driver can verify OTP and start a trip."))

    doc = frappe.get_doc("Cab Request", docname)

    # Block drivers from acting on trips they are not assigned to.
    # Managers retain override; without this gate, any driver-role user with the
    # OTP could start any other driver's trip.
    if not _is_manager(roles) and not _is_assigned_driver(doc):
        frappe.throw(
            _("You are not the assigned driver for this trip."),
            frappe.PermissionError,
        )

    if doc.status != "Assigned":
        return {
            "status":  "error",
            "message": f"This trip is currently '{doc.status}'. Only Assigned bookings can be started."
        }

    if not doc.otp:
        return {
            "status":  "expired",
            "message": "OTP has already been used or has expired."
        }

    if str(doc.otp).strip() != str(entered_otp).strip():
        return {
            "status":  "invalid",
            "message": "Incorrect OTP. Please ask the employee for the correct code."
        }

    # OTP correct — move to In Trip, clear OTP (one-time use)
    # `otp` is an INT column in DB, so clear with 0 (not empty string).
    apply_status_transition(
        docname, "In Trip", source="OTP Verified", extra_fields={"otp": 0}
    )
    frappe.db.commit()

    # Notify employee that trip has started
    try:
        employee_email = frappe.db.get_value("Employee", doc.employee_id, "personal_email")
        if employee_email:
            frappe.sendmail(
                recipients=[employee_email],
                subject="🚗 Your Cab Trip Has Started",
                message=f"""
                Hello {doc.employee_name},<br><br>
                Your driver has verified your OTP and the trip has started.<br><br>
                Driver: {doc.assigned_driver or '—'}<br>
                Vehicle: {doc.assigned_cab or '—'}<br>
                Pickup: {doc.pickup_location or '—'}<br><br>
                Have a safe journey!<br><br>
                Regards
                """
            )
    except Exception as e:
        frappe.log_error(str(e), "Trip Start Email Error")

    return {
        "status":  "success",
        "message": "OTP verified! Trip has started."
    }


# =========================================================
#  DRIVER COMPLETE TRIP
# =========================================================

@frappe.whitelist()
def driver_complete_trip(docname):
    roles = frappe.get_roles()
    if "Driver" not in roles and "Fleet Manager" not in roles and "System Manager" not in roles:
        frappe.throw(_("Only a Driver can mark a trip as Completed."))

    doc = frappe.get_doc("Cab Request", docname)

    # See note in verify_otp_and_start_trip — drivers may only act on their own trip.
    if not _is_manager(roles) and not _is_assigned_driver(doc):
        frappe.throw(
            _("You are not the assigned driver for this trip."),
            frappe.PermissionError,
        )

    if doc.status != "In Trip":
        frappe.throw(_("Only a trip that is 'In Trip' can be marked as Completed."))

    apply_status_transition(docname, "Completed", source="Trip Completed")
    frappe.db.commit()
    return "success"


# =========================================================
#  GET BOOKING DETAILS FOR DISPLAY
#  FIX: New whitelisted method so JS can fetch full trip details
#       including route display name, vehicle, driver, shift_time
#       all in one call — fixes "—" showing in booking card.
# =========================================================

@frappe.whitelist()
def get_booking_display_details(cab_request_name):
    """
    Returns full trip details for the booking card display.
    Joins Cab Route to get the human-readable route_name.
    """
    if not frappe.db.exists("Cab Request", cab_request_name):
        return None

    doc = frappe.get_doc("Cab Request", cab_request_name)

    # Restrict to the request owner, the assigned driver, or a manager.
    # Otherwise any logged-in user could read PII (employee name, contact,
    # pickup location) for any booking by guessing the docname.
    roles = frappe.get_roles()
    if not (_is_manager(roles) or _is_request_owner(doc) or _is_assigned_driver(doc)):
        frappe.throw(
            _("You are not authorised to view this booking."),
            frappe.PermissionError,
        )

    result = {
        "status":              doc.status,
        "employee_name":       doc.employee_name or "",
        "employee_id":         doc.employee_id or "",
        "contact_no":          doc.contact_no or "",
        "department":          doc.department or "",
        "pickup_location":     doc.pickup_location or "",
        "drop_location":       doc.drop_location or "",
        "travel_date":         str(doc.travel_date or ""),
        "booking_datetime":    str(doc.booking_datetime or ""),
        "assigned_route_id":   doc.assigned_route or "",
        "assigned_route":      "",   # display name — filled below
        "assigned_cab":        doc.assigned_cab or "",
        "assigned_driver":     doc.assigned_driver or "",
        "shift_time":          str(doc.shift_time or "") if doc.shift_time else "",
        "distance_from_route": doc.distance_from_route or "",
    }

    # Fetch human-readable route_name from Cab Route
    if doc.assigned_route:
        route_data = frappe.db.get_value(
            "Cab Route",
            doc.assigned_route,
            ["route_name", "vehicle", "driver_name", "shift_time"],
            as_dict=True,
        )
        if route_data:
            result["assigned_route"]  = route_data.get("route_name") or doc.assigned_route
            # Fill blanks from route doc if not on the cab request
            if not result["assigned_cab"]:
                result["assigned_cab"]    = route_data.get("vehicle") or ""
            if not result["assigned_driver"]:
                result["assigned_driver"] = route_data.get("driver_name") or ""
            if not result["shift_time"]:
                result["shift_time"]      = str(route_data.get("shift_time") or "")
        else:
            result["assigned_route"] = doc.assigned_route

    return result


# =========================================================
#  MANAGER: GET ALL ROUTES FOR MAP
# =========================================================

@frappe.whitelist()
def get_all_routes_for_manager():
    roles = frappe.get_roles()
    if "Fleet Manager" not in roles and "System Manager" not in roles:
        frappe.throw(_("Access denied."), frappe.PermissionError)

    today = frappe.utils.today()

    routes_raw = frappe.get_all(
        "Cab Route",
        filters={"status": "Active"},
        fields=[
            "name", "route_name",
            "vehicle",
            "driver_name", "driver_contact",
            "total_seats", "shift_time",
            "start_location", "start_lat", "start_lng",
            "end_location",   "end_lat",   "end_lng",
        ],
        ignore_permissions=True,
    )

    seat_counts = _get_booked_seat_counts([r["name"] for r in routes_raw], today)

    routes = []
    for r in routes_raw:
        waypoints_raw = frappe.get_all(
            "Route Waypoint",
            filters={"parent": r["name"]},
            fields=["stop_name", "latitude", "longitude", "pickup_time", "sequence"],
            order_by="sequence asc",
            ignore_permissions=True,
        )

        all_points = (
            [{
                "stop_name":   r["start_location"],
                "latitude":    r["start_lat"],
                "longitude":   r["start_lng"],
                "sequence":    0,
                "pickup_time": str(r.get("shift_time") or ""),
            }]
            + list(waypoints_raw)
            + [{
                "stop_name":   r["end_location"],
                "latitude":    r["end_lat"],
                "longitude":   r["end_lng"],
                "sequence":    9999,
                "pickup_time": "",
            }]
        )

        booked = seat_counts.get(r["name"], 0)

        routes.append({
            "name":              r["name"],
            "route_name":        r["route_name"],
            "start_location":    r["start_location"],
            "end_location":      r["end_location"],
            "vehicle":           r.get("vehicle", ""),
            "license_plate":     r.get("license_plate", ""),
            "driver_name":       r.get("driver_name", ""),
            "driver_contact":    r.get("driver_contact", ""),
            "total_seats":       int(r.get("total_seats") or 0),
            "booked_seats":      booked,
            "shift_time":        str(r.get("shift_time") or ""),
            "waypoints":         all_points,
            "assigned_route_id": r["name"],
        })

    emp_requests = frappe.get_all(
        "Cab Request",
        filters={
            "travel_date":    today,
            "assigned_route": ["is", "set"],
            "status":         ["in", ["Assigned", "In Trip"]],
        },
        fields=[
            "name", "owner", "employee_id", "employee_name",
            "pickup_location", "pickup_lat", "pickup_lng",
            "assigned_route", "assigned_cab", "assigned_driver",
            "contact_no", "travel_date", "status",
        ],
    )

    employees = []
    for emp in emp_requests:
        if not emp.get("pickup_lat") or not emp.get("pickup_lng"):
            continue

        assigned_route_name = ""
        if emp.get("assigned_route"):
            try:
                assigned_route_name = (
                    frappe.db.get_value("Cab Route", emp["assigned_route"], "route_name")
                    or emp["assigned_route"]
                )
            except Exception:
                assigned_route_name = emp["assigned_route"]

        employees.append({
            "employee":          emp.get("employee_id") or emp.get("owner"),
            "employee_name":     emp.get("employee_name") or emp.get("owner"),
            "pickup_location":   emp.get("pickup_location", ""),
            "pickup_lat":        float(emp["pickup_lat"]),
            "pickup_lng":        float(emp["pickup_lng"]),
            "assigned_route":    assigned_route_name,
            "assigned_route_id": emp.get("assigned_route", ""),
            "assigned_cab":      emp.get("assigned_cab", ""),
            "assigned_driver":   emp.get("assigned_driver", ""),
            "contact_no":        emp.get("contact_no", ""),
            "travel_date":       str(emp.get("travel_date") or today),
            "status":            emp.get("status", ""),
            "docname":           emp["name"],
        })

    return {"routes": routes, "employees": employees}


# =========================================================
#  DRIVER: GET ROUTE DETAILS
# =========================================================

@frappe.whitelist()
def get_driver_route_details():
    """
    Returns the logged-in driver's Cab Route + today's passengers.

    ROOT CAUSE FIX:
    Cab Route.driver_name can store ANY of these depending on how the route
    was created:
      - Employee full name  e.g. "Ravi Kumar"
      - Driver doc name     e.g. "HR-DRI-0001"
      - User email          e.g. "ravi@company.com"
      - Employee ID         e.g. "EMP-0001"

    We collect all possible values for the logged-in user and try each one
    until we find a matching Cab Route.
    """
    roles = frappe.get_roles()
    if "Driver" not in roles and "Fleet Manager" not in roles and "System Manager" not in roles:
        frappe.throw(_("Access denied."))

    current_user = frappe.session.user
    today        = frappe.utils.today()

    # ── Collect every possible identifier for this driver ─────────────────
    candidates = set()
    candidates.add(current_user)  # user email e.g. ravi@co.com

    employee_id = frappe.db.get_value("Employee", {"user_id": current_user}, "name")
    if employee_id:
        candidates.add(employee_id)   # EMP-0001
        emp_full_name = frappe.db.get_value("Employee", employee_id, "employee_name")
        if emp_full_name:
            candidates.add(emp_full_name)  # "Ravi Kumar"

        # Driver doctype linked to this employee
        driver_doc = frappe.db.get_value("Driver", {"employee": employee_id}, "name")
        if driver_doc:
            candidates.add(driver_doc)  # HR-DRI-0001
            drv_full = frappe.db.get_value("Driver", driver_doc, "full_name")
            if drv_full:
                candidates.add(drv_full)

    candidates.discard(None)
    candidates.discard("")

    # ── Find the first matching active Cab Route ───────────────────────────
    route_name = None

    for candidate in candidates:
        found = frappe.db.get_value(
            "Cab Route",
            {"driver_name": candidate, "status": "Active"},
            "name"
        )
        if found:
            route_name = found
            break

    # ── Fallback: find route via an active Cab Request for today ──────────
    # Handles case where route was assigned but driver_name key differs
    if not route_name:
        for candidate in candidates:
            req_route = frappe.db.get_value(
                "Cab Request",
                {
                    "assigned_driver": candidate,
                    "travel_date":     today,
                    "status":          ["in", ["Assigned", "In Trip"]],
                },
                "assigned_route"
            )
            if req_route:
                route_name = req_route
                break

    if not route_name:
        return {
            "has_route":     False,
            "route":         None,
            "employees":     [],
            "passengers":    [],
            "_debug_user":   current_user,
            "_debug_tried":  list(candidates),
            "_debug_hint":   "No active Cab Route found. Make sure Cab Route.driver_name matches one of the above."
        }

    # ── Load route + waypoints ─────────────────────────────────────────────
    route = frappe.get_doc("Cab Route", route_name)
    waypoints_raw = frappe.get_all(
        "Route Waypoint",
        filters={"parent": route_name},
        fields=["stop_name", "latitude", "longitude", "pickup_time", "sequence"],
        order_by="sequence asc",
    )
    all_points = (
        [{
            "stop_name":   route.start_location or "Start",
            "latitude":    float(route.start_lat or 0),
            "longitude":   float(route.start_lng or 0),
            "sequence":    0,
            "pickup_time": str(route.shift_time or ""),
        }]
        + [dict(wp) for wp in waypoints_raw]
        + [{
            "stop_name":   route.end_location or "End",
            "latitude":    float(route.end_lat or 0),
            "longitude":   float(route.end_lng or 0),
            "sequence":    9999,
            "pickup_time": "",
        }]
    )

    route_data = {
        "name":           route_name,
        "route_name":     route.route_name or route_name,
        "vehicle":        route.vehicle or "",
        "vehicle_no":     route.vehicle or "",
        "assigned_cab":   route.vehicle or "",
        "driver_name":    route.driver_name or "",
        "assigned_driver": route.driver_name or "",
        "driver_contact": route.driver_contact or "",
        "shift_time":     str(route.shift_time or ""),
        "start_location": route.start_location or "",
        "end_location":   route.end_location   or "",
        "waypoints":      all_points,
    }

    # Backfill missing route-level driver/vehicle values from today's assigned
    # cab requests so dashboard custom blocks can still render details.
    if not route_data["vehicle"] or not route_data["driver_name"]:
        fallback_req = frappe.get_all(
            "Cab Request",
            filters={
                "assigned_route": route_name,
                "travel_date": today,
                "status": ["in", ["Assigned", "In Trip"]],
            },
            fields=["assigned_cab", "assigned_driver"],
            limit=1,
        )
        if fallback_req:
            fr = fallback_req[0]
            if not route_data["vehicle"]:
                route_data["vehicle"] = fr.get("assigned_cab") or ""
                route_data["vehicle_no"] = route_data["vehicle"]
                route_data["assigned_cab"] = route_data["vehicle"]
            if not route_data["driver_name"]:
                route_data["driver_name"] = fr.get("assigned_driver") or ""
                route_data["assigned_driver"] = route_data["driver_name"]

    # ── Load passengers — try all candidates ─────────────────────────────
    passengers_raw = []
    for candidate in candidates:
        rows = frappe.get_all(
            "Cab Request",
            filters={
                "assigned_driver": candidate,
                "travel_date":     today,
                "status":          ["in", ["Assigned", "In Trip"]],
            },
            fields=[
                "name", "employee_id", "employee_name",
                "pickup_location", "pickup_lat", "pickup_lng",
                "contact_no", "distance_from_route", "status",
                "booking_datetime",
            ],
        )
        if rows:
            passengers_raw.extend(rows)

    # Also load by assigned_route in case assigned_driver was stored differently
    if not passengers_raw:
        passengers_raw = frappe.get_all(
            "Cab Request",
            filters={
                "assigned_route": route_name,
                "travel_date":    today,
                "status":         ["in", ["Assigned", "In Trip"]],
            },
            fields=[
                "name", "employee_id", "employee_name",
                "pickup_location", "pickup_lat", "pickup_lng",
                "contact_no", "distance_from_route", "status",
                "booking_datetime",
            ],
        )

    # Deduplicate
    seen = set()
    passengers = []
    for p in passengers_raw:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        if not p.get("pickup_lat") or not p.get("pickup_lng"):
            continue
        passengers.append({
            "docname":             p["name"],
            "employee_id":         p.get("employee_id", ""),
            "employee_name":       p.get("employee_name", ""),
            "pickup_location":     p.get("pickup_location", ""),
            "pickup_lat":          float(p["pickup_lat"]),
            "pickup_lng":          float(p["pickup_lng"]),
            "contact_no":          p.get("contact_no", ""),
            "distance_from_route": p.get("distance_from_route", ""),
            "status":              p.get("status", ""),
            "booking_datetime":    str(p.get("booking_datetime", "") or ""),
        })

    return {
        "has_route":  True,
        "route":      route_data,
        "employees":  passengers,
        "passengers": passengers,
    }


# =========================================================
#  GEOJSON GENERATOR — hooks.py: Cab Route before_save
# =========================================================

def generate_route_geojson(doc, method=None):
    try:
        waypoints = sorted(doc.waypoints or [], key=lambda w: w.sequence)
        coords = [[float(doc.start_lng), float(doc.start_lat)]]
        for wp in waypoints:
            coords.append([float(wp.longitude), float(wp.latitude)])
        coords.append([float(doc.end_lng), float(doc.end_lat)])

        doc.route_polyline = json.dumps({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"route_name": doc.route_name},
        })
    except Exception as e:
        frappe.log_error(str(e), "Cab Route GeoJSON Error")
