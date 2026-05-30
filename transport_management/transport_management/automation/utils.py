# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Shared helpers for the Transport Management scheduled-automation jobs."""

import frappe


def parse_day_list(raw):
    """Parse a comma/newline separated string into a sorted list of unique ints.

    Invalid tokens are silently dropped — `TransportSettings.validate` already
    rejects bad input at save time, this is just a defensive fallback.
    """
    if not raw:
        return []

    days = set()
    for token in str(raw).replace("\n", ",").split(","):
        token = token.strip()
        if token.isdigit():
            days.add(int(token))
    return sorted(days)


def get_alert_recipients(settings=None):
    """Resolve Transport Settings recipient roles + extra emails into a unique,
    de-duplicated list of valid, enabled email addresses."""
    if settings is None:
        settings = frappe.get_single("Transport Settings")

    candidates = set()

    for role in _split(settings.alert_recipient_roles):
        candidates.update(
            frappe.get_all(
                "Has Role",
                filters={"role": role, "parenttype": "User"},
                pluck="parent",
            )
        )

    candidates.update(_split(settings.additional_alert_emails))
    candidates.discard("Administrator")
    candidates.discard("Guest")

    recipients = set()
    for value in candidates:
        if "@" not in value:
            continue
        # Literal addresses (not Users) return None for `enabled` — keep them.
        enabled = frappe.db.get_value("User", value, "enabled")
        if enabled in (None, 1):
            recipients.add(value)
    return sorted(recipients)


def _split(raw):
    """Split a comma/newline separated string into a list of trimmed tokens."""
    if not raw:
        return []
    return [token.strip() for token in str(raw).replace("\n", ",").split(",") if token.strip()]
