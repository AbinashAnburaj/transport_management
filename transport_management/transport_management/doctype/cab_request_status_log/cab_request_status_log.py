# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CabRequestStatusLog(Document):
    """Append-only audit record of a Cab Request status change.

    Records are written by transport_management.transport_management.cab_status
    (apply_status_transition / log_status_change) and by CabRequest.on_update
    for manual form edits. No role has write access — the log is immutable
    once created.
    """

    pass
