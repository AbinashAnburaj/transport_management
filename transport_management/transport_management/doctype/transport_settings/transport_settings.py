# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address


class TransportSettings(Document):
    def validate(self):
        self._validate_day_list("compliance_warning_days")
        self._validate_day_list("maintenance_warning_days")
        self._validate_additional_alert_emails()

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

    def _validate_additional_alert_emails(self):
        """Reject malformed addresses up front so alert delivery doesn't drop them silently."""
        raw = self.get("additional_alert_emails")
        if not raw:
            return

        for token in str(raw).replace("\n", ",").split(","):
            email = token.strip()
            if not email:
                continue
            # `throw=False` returns the cleaned address or None.
            if not validate_email_address(email, throw=False):
                frappe.throw(
                    _("'{0}' contains an invalid email address: {1}").format(
                        self.meta.get_label("additional_alert_emails"), email
                    )
                )
