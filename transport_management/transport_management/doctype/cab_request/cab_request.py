import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime, add_to_date
from transport_management.whatsapp import send_whatsapp_message
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