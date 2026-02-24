import frappe
from frappe.permissions import add_permission

def execute():
    # List of doctypes that need Read permission for the Driver role
    doctypes = ["Number Card", "Dashboard Chart", "Workspace"]
    
    for dt in doctypes:
        # Check if permission already exists
        if not frappe.db.exists("DocPerm", {"parent": dt, "role": "Driver", "read": 1}):
            add_permission(dt, "Driver", 0)
            print(f"Added Read permission for Driver on {dt}")
        else:
            print(f"Read permission for Driver on {dt} already exists")

    # Force permission cache clear
    frappe.clear_cache(doctype="Number Card")
    frappe.clear_cache(doctype="Dashboard Chart")
    frappe.clear_cache(doctype="Workspace")
