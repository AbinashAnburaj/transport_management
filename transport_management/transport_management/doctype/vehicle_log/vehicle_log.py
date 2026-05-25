import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


MANAGER_ROLES = {"Fleet Manager", "System Manager"}


def _get_roles(user=None):
    return set(frappe.get_roles(user or frappe.session.user))


def _is_manager(user=None):
    return bool(_get_roles(user) & MANAGER_ROLES)


def _is_driver_only(user=None):
    roles = _get_roles(user)
    return "Driver" in roles and not bool(roles & MANAGER_ROLES)


def _get_employee_for_user(user):
    return frappe.db.get_value("Employee", {"user_id": user}, "name")


def _has_vehicle_log_field(fieldname):
    return bool(frappe.get_meta("Vehicle Log").has_field(fieldname))


def _has_vehicle_field(fieldname):
    return bool(frappe.get_meta("Vehicle").has_field(fieldname))


def _get_driver_doc_for_user(user):
    employee = _get_employee_for_user(user)
    driver = {}
    if employee:
        driver = frappe.db.get_value(
            "Driver",
            {"employee": employee},
            ["name", "full_name"],
            as_dict=True,
        ) or {}

    if not driver:
        driver = frappe.db.get_value(
            "Driver",
            {"user_id": user},
            ["name", "full_name", "employee"],
            as_dict=True,
        ) or {}

    if not employee and driver.get("employee"):
        employee = driver.get("employee")

    return {
        "employee": employee,
        "driver_id": driver.get("name"),
        "driver_name": driver.get("full_name"),
    }


def _find_active_route_for_driver(user):
    linked = _get_driver_doc_for_user(user)
    candidates = {
        user,
        linked.get("employee"),
        linked.get("driver_id"),
        linked.get("driver_name"),
    }
    candidates = [c for c in candidates if c]

    for candidate in candidates:
        route = frappe.db.get_value(
            "Cab Route",
            {"status": "Active", "driver_name": candidate},
            ["name", "vehicle", "driver_id", "driver_name"],
            as_dict=True,
        )
        if route:
            return route

    if linked.get("driver_id"):
        route = frappe.db.get_value(
            "Cab Route",
            {"status": "Active", "driver_id": linked.get("driver_id")},
            ["name", "vehicle", "driver_id", "driver_name"],
            as_dict=True,
        )
        if route:
            return route

    # Fallback from Vehicle master if directly tagged with driver/employee.
    vehicle = None
    if linked.get("driver_id"):
        vehicle = frappe.db.get_value(
            "Vehicle",
            {"driver": linked.get("driver_id")},
            "name",
        )
    if not vehicle and linked.get("employee"):
        vehicle = frappe.db.get_value(
            "Vehicle",
            {"employee": linked.get("employee")},
            "name",
        )
    if not vehicle and linked.get("driver_name"):
        vehicle = frappe.db.get_value(
            "Vehicle",
            {"custom_driver_name": linked.get("driver_name")},
            "name",
        )
    if not vehicle and linked.get("driver_id") and _has_vehicle_field("custom_driver_id"):
        vehicle = frappe.db.get_value(
            "Vehicle",
            {"custom_driver_id": linked.get("driver_id")},
            "name",
        )
    if vehicle:
        return {
            "vehicle": vehicle,
            "driver_id": linked.get("driver_id"),
            "driver_name": linked.get("driver_name"),
        }
    return {}


@frappe.whitelist()
def get_driver_vehicle_defaults():
    user = frappe.session.user
    if not _is_driver_only(user):
        return {}

    linked = _get_driver_doc_for_user(user)
    route = _find_active_route_for_driver(user)

    return {
        "employee": linked.get("employee"),
        "driver_id": route.get("driver_id") or linked.get("driver_id"),
        "driver_name": route.get("driver_name") or linked.get("driver_name"),
        "license_plate": route.get("vehicle"),
    }


def setup_vehicle_log_driver_workflow():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields(
        {
            "Vehicle Log": [
                {
                    "fieldname": "approval_status",
                    "label": "Status",
                    "fieldtype": "Select",
                    "options": "Pending\nApproved",
                    "default": "Pending",
                    "insert_after": "service_detail",
                    "in_list_view": 1,
                }
            ]
        },
        update=True,
    )

    client_script = frappe.db.get_value(
        "Client Script",
        {"dt": "Vehicle Log", "view": "Form"},
        "name",
    )
    script_text = frappe.get_app_path(
        "transport_management",
        "public",
        "js",
        "vehicle_log.js",
    )
    with open(script_text, "r", encoding="utf-8") as f:
        script_body = f.read()

    if client_script:
        doc = frappe.get_doc("Client Script", client_script)
        doc.script = script_body
        doc.enabled = 1
        doc.save(ignore_permissions=True)
    else:
        # Disable existing non-Form scripts for this doctype to avoid confusion.
        existing = frappe.get_all(
            "Client Script",
            filters={"dt": "Vehicle Log"},
            fields=["name", "view", "enabled"],
        )
        for row in existing:
            if row.get("view") != "Form" and row.get("enabled"):
                doc = frappe.get_doc("Client Script", row.get("name"))
                doc.enabled = 0
                doc.save(ignore_permissions=True)

        frappe.get_doc(
            {
                "doctype": "Client Script",
                "name": "vehicle log transport management",
                "dt": "Vehicle Log",
                "enabled": 1,
                "view": "Form",
                "script": script_body,
            }
        ).insert(ignore_permissions=True)

    dt = frappe.get_doc("DocType", "Vehicle Log")
    has_driver_perm = any(p.role == "Driver" for p in dt.permissions)
    if not has_driver_perm:
        dt.append(
            "permissions",
            {
                "role": "Driver",
                "read": 1,
                "write": 1,
                "create": 1,
                "report": 1,
                "print": 1,
                "email": 1,
            },
        )
        dt.save(ignore_permissions=True)

    file_dt = frappe.get_doc("DocType", "File")
    has_file_driver_perm = any(p.role == "Driver" for p in file_dt.permissions)
    if not has_file_driver_perm:
        file_dt.append(
            "permissions",
            {
                "role": "Driver",
                "read": 1,
                "write": 1,
                "create": 1,
            },
        )
        file_dt.save(ignore_permissions=True)

    _grant_vehicle_log_user_permission_to_all_drivers()

    frappe.clear_cache(doctype="Vehicle Log")


def _grant_vehicle_log_user_permission_to_all_drivers():
    driver_users = set(
        frappe.get_all(
            "Has Role",
            filters={"role": "Driver", "parenttype": "User"},
            pluck="parent",
        )
    )

    for user in driver_users:
        if user in ("Administrator", "Guest"):
            continue
        frappe.permissions.add_user_permission(
            doctype="DocType",
            name="Vehicle Log",
            user=user,
            ignore_permissions=True,
        )


def ensure_vehicle_log_permission_for_driver_role(doc, method=None):
    if getattr(doc, "parenttype", None) != "User":
        return
    if getattr(doc, "role", None) != "Driver":
        return

    user = getattr(doc, "parent", None)
    if not user or user in ("Administrator", "Guest"):
        return

    frappe.permissions.add_user_permission(
        doctype="DocType",
        name="Vehicle Log",
        user=user,
        ignore_permissions=True,
    )


class VehicleLog(Document):
    def validate(self):
        self._set_total_distance()

        if not _is_driver_only():
            return

        self._set_driver_defaults()
        self._ensure_pending_for_driver()
        self._prevent_driver_status_edit()

    def _set_total_distance(self):
        current_odo = getattr(self, "odometer", None)
        last_odo = getattr(self, "last_odometer", None)
        if last_odo is None:
            # Backward compatibility for alternate schemas.
            last_odo = getattr(self, "end_odometer", None)

        if current_odo is None or last_odo is None:
            return

        # Daily Distance = Current Odometer - Last Odometer.
        distance = max(flt(current_odo) - flt(last_odo), 0)
        if _has_vehicle_log_field("daily_distance"):
            self.daily_distance = distance
        elif _has_vehicle_log_field("total_distance"):
            self.total_distance = distance

    def _set_driver_defaults(self):
        defaults = get_driver_vehicle_defaults() or {}

        if defaults.get("employee") and _has_vehicle_log_field("employee"):
            self.employee = defaults.get("employee")
        if defaults.get("driver_id") and _has_vehicle_log_field("driver_id"):
            self.driver_id = defaults.get("driver_id")
        if defaults.get("driver_name") and _has_vehicle_log_field("driver_name"):
            self.driver_name = defaults.get("driver_name")
        if defaults.get("license_plate") and _has_vehicle_log_field("license_plate") and not self.license_plate:
            self.license_plate = defaults.get("license_plate")

    def _ensure_pending_for_driver(self):
        if self.is_new():
            self.approval_status = "Pending"

    def _prevent_driver_status_edit(self):
        if self.is_new():
            return

        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        if self.approval_status != old_doc.approval_status:
            frappe.throw(_("Only Fleet Manager/System Manager can change Status."))

        if old_doc.approval_status == "Approved":
            frappe.throw(_("Approved Vehicle Log cannot be edited by Driver."))


def get_permission_query_conditions(user):
    user = user or frappe.session.user

    if _is_manager(user):
        return None

    if _is_driver_only(user):
        if _has_vehicle_log_field("employee"):
            employee = _get_employee_for_user(user)
            if employee:
                return f"`tabVehicle Log`.employee = {frappe.db.escape(employee)}"
        return f"`tabVehicle Log`.owner = {frappe.db.escape(user)}"

    return "1=0"


def has_permission(doc, user=None, permission_type=None):
    user = user or frappe.session.user

    if _is_manager(user):
        return True

    if not _is_driver_only(user):
        return False

    # Pre-insert / synthetic-doc paths (doctype-level checks, attachment
    # upload pre-checks, provisional unsaved docs). Restrict to drivers who
    # actually have an active route — without that gate, any driver-role user
    # could open a Vehicle Log create form for any vehicle.
    pre_insert = (
        not getattr(doc, "doctype", None)
        or (hasattr(doc, "is_new") and doc.is_new())
        or not (getattr(doc, "name", "") or "")
        or (getattr(doc, "name", "") or "").startswith("new-vehicle-log-")
    )
    if pre_insert:
        if permission_type not in (None, "read", "create", "write"):
            return False
        return bool(_find_active_route_for_driver(user))

    if _has_vehicle_log_field("employee"):
        employee = _get_employee_for_user(user)
        if employee and getattr(doc, "employee", None) == employee:
            return True

    return getattr(doc, "owner", None) == user
