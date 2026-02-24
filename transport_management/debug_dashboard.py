import frappe

def debug_dashboard_permissions():
    frappe.connect()
    users = frappe.get_all("User", filters={"enabled": 1}, fields=["name"])
    
    print("--- Debugging User -> Employee -> Driver Links ---")
    for user_record in users:
        user = user_record.name
        roles = frappe.get_roles(user)
        if "Driver" in roles:
            print(f"\nUser: {user} (Roles: {', '.join(roles)})")
            
            # 1. Check Employee Link
            employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
            if not employee_id:
                print(f"❌ User {user} is NOT linked to any Employee (via user_id field).")
            else:
                print(f"✅ Linked to Employee: {employee_id}")
                
                # 2. Check Driver Link
                driver_name = frappe.db.get_value("Driver", {"employee": employee_id}, "name")
                if not driver_name:
                    print(f"❌ Employee {employee_id} is NOT linked to any Driver (via employee field).")
                else:
                    print(f"✅ Linked to Driver: {driver_name}")
                    
                    # 3. Check Cab Requests
                    count = frappe.db.count("Cab Request", {"driver_id": driver_name})
                    print(f"📊 Cab Requests assigned to {driver_name}: {count}")

    print("\n--- Checking/Applying Number Card / Dashboard Chart Permissions for Driver Role ---")
    from frappe.permissions import add_permission
    for dt in ["Number Card", "Dashboard Chart", "Dashboard", "Workspace"]:
        perms = frappe.get_all("Custom DocPerm", filters={"parent": dt, "role": "Driver"}, fields=["read"])
        if perms:
            print(f"✅ {dt}: Driver has Read permission (Custom).")
        else:
            # Check standard permissions
            standard_perms = frappe.get_all("DocPerm", filters={"parent": dt, "role": "Driver"}, fields=["read"])
            if standard_perms:
                 print(f"✅ {dt}: Driver has Read permission (Standard).")
            else:
                 print(f"⚠️ {dt}: Driver lacks Read permission! Applying now...")
                 try:
                     add_permission(dt, "Driver", 0)
                     print(f"✨ Applied Read permission to {dt}")
                 except Exception as e:
                     print(f"❌ Failed to apply permission to {dt}: {e}")

    # Clear cache
    frappe.clear_cache(doctype="Number Card")
    frappe.clear_cache(doctype="Dashboard Chart")
    frappe.clear_cache(doctype="Workspace")
    print("✅ Cache cleared.")

if __name__ == "__main__":
    debug_dashboard_permissions()
