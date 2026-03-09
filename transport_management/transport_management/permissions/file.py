import frappe


def has_permission(doc, ptype=None, user=None, debug=False):
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))

    # Upload endpoint can check create permission without a concrete File doc.
    if ptype == "create" and not getattr(doc, "attached_to_doctype", None):
        if "Driver" in roles:
            return True
        return frappe.has_permission("Vehicle Log", "write", user=user, raise_exception=False)

    attached_doctype = getattr(doc, "attached_to_doctype", None)
    attached_name = getattr(doc, "attached_to_name", "") or ""

    # Allow temporary file ops while creating a new unsaved Vehicle Log.
    # Frappe may check create/read/select on File even before Vehicle Log is inserted.
    if attached_doctype == "Vehicle Log" and (
        not attached_name or attached_name.startswith("new-vehicle-log-")
    ):
        if ptype in (None, "create", "read", "select", "write"):
            return True
        return True

    # Defer to Frappe's default File permission logic for all other cases.
    return None
