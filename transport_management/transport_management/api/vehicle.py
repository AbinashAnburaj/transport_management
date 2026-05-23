# Copyright (c) 2026, and contributors
# For license information, please see license.txt

import frappe


def sync_vehicle_status(doc, method):
    """Propagate a Vehicle's status to every Cab Route that uses it.

    Wired via hooks.doc_events -> Vehicle.on_update.
    """
    linked_routes = frappe.get_all("Cab Route", filters={"vehicle": doc.name})
    for route in linked_routes:
        frappe.db.set_value("Cab Route", route.name, "vehicle_status", doc.vehicle_status)
