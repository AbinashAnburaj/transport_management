# Copyright (c) 2026, and contributors
# For license information, please see license.txt

import frappe
 
def sync_vehicle_status(doc, method):

    # 1. Pop up a message to prove the hook is triggering

    frappe.msgprint(f"Running hook update for Vehicle: {doc.name}")

    # 2. Find the routes linked to this vehicle

    linked_routes = frappe.get_all("Cab Route", filters={"vehicle": doc.name})

    # 3. Pop up a second message telling us exactly how many routes it found

    frappe.msgprint(f"Found {len(linked_routes)} Cab Route(s) to update.")
 
    # 4. Loop and update the vehicle_status in the Cab Route doctype

    for route in linked_routes:

        frappe.db.set_value("Cab Route", route.name, "vehicle_status", doc.vehicle_status)
 
