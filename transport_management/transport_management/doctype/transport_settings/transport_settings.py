# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TransportSettings(Document):
    def validate(self):
        self._validate_day_list("compliance_warning_days")
        self._validate_day_list("maintenance_warning_days")

    def _validate_day_list(self, fieldname):
        """Ensure a warning-days field holds only comma/newline separated whole numbers."""
        raw = self.get(fieldname)
        if not raw:
            return

        for token in str(raw).replace("\n", ",").split(","):
            token = token.strip()
            if not token:
                continue
            if not token.isdigit():
                frappe.throw(
                    _("'{0}' must be a comma-separated list of whole numbers — got '{1}'.").format(
                        self.meta.get_label(fieldname), token
                    )
                )
