# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Central status state-machine for Cab Request.

Phase 4 retired the misconfigured `Cab Request Workflow` and replaced it with
this code-level state machine. Every status change — from an API method or a
manual form edit — is validated against ALLOWED_TRANSITIONS and recorded in
the Cab Request Status Log audit doctype.

  apply_status_transition()  — used by the booking API methods (book_route_cab,
                               verify_otp_and_start_trip, driver_complete_trip,
                               cancel_route_booking): validates, writes, logs.
  is_valid_transition()      — used by CabRequest.validate to gate manual edits.
  log_status_change()        — appends an audit record.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

# Canonical statuses — matches the Cab Request.status Select options.
STATUSES = ("Pending", "Assigned", "In Trip", "Completed", "Cancelled")

# from-status -> allowed next statuses. Completed and Cancelled are terminal.
ALLOWED_TRANSITIONS = {
    "Pending": {"Assigned", "Cancelled"},
    "Assigned": {"In Trip", "Cancelled"},
    "In Trip": {"Completed"},
    "Completed": set(),
    "Cancelled": set(),
}


def is_valid_transition(from_status, to_status):
    """Return True if `from_status` -> `to_status` is permitted.

    A no-op (same status) is allowed. An unrecognised current status — e.g. a
    legacy/stray value not in ALLOWED_TRANSITIONS — is permitted so the state
    machine never hard-blocks pre-existing data.
    """
    if from_status == to_status:
        return True
    if from_status not in ALLOWED_TRANSITIONS:
        return True
    return to_status in ALLOWED_TRANSITIONS[from_status]


def apply_status_transition(cab_request, new_status, source, extra_fields=None,
                            note=None, user=None):
    """Validate and apply a status change, then write an audit-log entry.

    Writes via frappe.db.set_value (bypassing validate, as the booking API
    intentionally does). `extra_fields` are written in the same DB update.
    Committing the transaction is left to the caller.
    """
    name = cab_request if isinstance(cab_request, str) else cab_request.name
    # Lock the row so a concurrent caller cannot read the same "before" status
    # and race us into a duplicate transition (e.g. two book_route_cab calls
    # firing on the same Pending request from a double-click or retry).
    current = frappe.db.get_value("Cab Request", name, "status", for_update=True)

    updates = dict(extra_fields or {})

    if current == new_status:
        # Status unchanged — still apply any accompanying field updates.
        if updates:
            frappe.db.set_value("Cab Request", name, updates)
        return

    if not is_valid_transition(current, new_status):
        frappe.throw(
            _("Status change {0} → {1} is not allowed.").format(
                current or _("(none)"), new_status),
            title=_("Invalid Status Transition"),
        )

    updates["status"] = new_status
    frappe.db.set_value("Cab Request", name, updates)
    log_status_change(name, current, new_status, source, note=note, user=user)


def log_status_change(cab_request, from_status, to_status, source, note=None, user=None):
    """Append an immutable Cab Request Status Log record."""
    frappe.get_doc({
        "doctype": "Cab Request Status Log",
        "cab_request": cab_request,
        "from_status": from_status or "",
        "to_status": to_status,
        "source": source,
        "changed_by": user or frappe.session.user,
        "changed_on": now_datetime(),
        "note": note or "",
    }).insert(ignore_permissions=True)
