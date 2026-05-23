# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Deactivate the misconfigured `Cab Request Workflow`.

The workflow was bound to the `status` field but defined an invalid state
(`Cancelled Trip` writing `Rejected`, neither a valid status option) and
conflicted with the code-driven booking flow. Phase 4 replaces it with the
cab_status state machine, so the workflow is deactivated to remove the
data-corruption risk. Idempotent and reversible.
"""

import frappe

WORKFLOW_NAME = "Cab Request Workflow"


def execute():
    if not frappe.db.exists("Workflow", WORKFLOW_NAME):
        return

    if frappe.db.get_value("Workflow", WORKFLOW_NAME, "is_active"):
        frappe.db.set_value("Workflow", WORKFLOW_NAME, "is_active", 0)
        frappe.clear_cache(doctype="Cab Request")
