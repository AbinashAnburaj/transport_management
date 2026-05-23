# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Normalise invalid Cab Request status values.

A legacy row carried status="Success" — not a valid `status` Select option
nor a cab_status state. Such values are remapped to the closest valid state.
Idempotent: only rows whose status is outside the canonical set are touched.
"""

import frappe

VALID = {"Pending", "Assigned", "In Trip", "Completed", "Cancelled"}
REMAP = {"Success": "Completed"}


def execute():
    rows = frappe.get_all(
        "Cab Request",
        filters={"status": ["not in", list(VALID)]},
        fields=["name", "status"],
    )
    for row in rows:
        new_status = REMAP.get(row.status, "Completed")
        frappe.db.set_value("Cab Request", row.name, "status", new_status)
        frappe.logger("transport_management").info(
            f"Normalised Cab Request {row.name} status {row.status!r} -> {new_status!r}"
        )
