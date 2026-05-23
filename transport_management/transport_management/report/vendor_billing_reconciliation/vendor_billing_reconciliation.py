# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Vendor Billing Reconciliation — which Completed trips are billed vs pending.

Sourced from Cab Request (Completed trips only). Billable amount is per-km
(rate x total_distance), matching billing.vendor_billing. The billing_status
column makes data gaps visible: a trip can't be billed until it has a vendor,
a rate, and a recorded distance.
"""

import frappe
from frappe import _
from frappe.utils import flt

COMPLETED_STATUS = "Completed"

STATUS_COLORS = {
    "Billed": "#28a745",
    "Pending": "#007bff",
    "No Vendor": "#6c757d",
    "No Rate": "#fd7e14",
    "No Distance": "#dc3545",
}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    data = get_data(filters)
    return get_columns(), data, None, get_chart(data), get_report_summary(data)


def get_columns():
    return [
        {"label": _("Trip"), "fieldname": "trip", "fieldtype": "Link",
         "options": "Cab Request", "width": 150},
        {"label": _("Vendor"), "fieldname": "vendor", "fieldtype": "Link",
         "options": "Supplier", "width": 150},
        {"label": _("Travel Date"), "fieldname": "travel_date", "fieldtype": "Date", "width": 110},
        {"label": _("Route"), "fieldname": "route", "fieldtype": "Data", "width": 150},
        {"label": _("Rate"), "fieldname": "rate", "fieldtype": "Currency", "width": 100},
        {"label": _("Distance (km)"), "fieldname": "distance", "fieldtype": "Float", "width": 120},
        {"label": _("Billable Amount"), "fieldname": "billable_amount", "fieldtype": "Currency", "width": 140},
        {"label": _("Billing Status"), "fieldname": "billing_status", "fieldtype": "Data", "width": 130},
        {"label": _("Invoice"), "fieldname": "invoice", "fieldtype": "Link",
         "options": "Cab Vendor Invoice", "width": 150},
    ]


def get_data(filters):
    conditions = ["status = %(status)s"]
    query_filters = {"status": COMPLETED_STATUS}

    if filters.get("from_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) >= %(from_date)s")
        query_filters["from_date"] = filters["from_date"]
    if filters.get("to_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) <= %(to_date)s")
        query_filters["to_date"] = filters["to_date"]
    if filters.get("vendor"):
        conditions.append("vendor = %(vendor)s")
        query_filters["vendor"] = filters["vendor"]

    rows = frappe.db.sql(
        """
        SELECT
            name AS trip,
            vendor,
            COALESCE(travel_date, DATE(booking_datetime)) AS travel_date,
            assigned_route AS route,
            rate,
            total_distance AS distance,
            invoice_link AS invoice
        FROM `tabCab Request`
        WHERE {where}
        ORDER BY travel_date DESC
        """.format(where=" AND ".join(conditions)),
        query_filters,
        as_dict=True,
    )

    wanted_status = filters.get("billing_status")
    data = []
    for row in rows:
        row["rate"] = flt(row.get("rate"))
        row["distance"] = flt(row.get("distance"))
        row["billable_amount"] = row["rate"] * row["distance"]
        row["invoice"] = (row.get("invoice") or "").strip()
        row["billing_status"] = _billing_status(row)

        if wanted_status and row["billing_status"] != wanted_status:
            continue
        data.append(row)

    return data


def _billing_status(row):
    if row["invoice"]:
        return "Billed"
    if not row["vendor"]:
        return "No Vendor"
    if not row["rate"]:
        return "No Rate"
    if not row["distance"]:
        return "No Distance"
    return "Pending"


def get_chart(data):
    counts = {}
    for row in data:
        counts[row["billing_status"]] = counts.get(row["billing_status"], 0) + 1
    if not counts:
        return None

    labels = list(counts.keys())
    return {
        "type": "donut",
        "data": {
            "labels": labels,
            "datasets": [{"values": [counts[label] for label in labels]}],
        },
        "colors": [STATUS_COLORS.get(label, "#6c757d") for label in labels],
    }


def get_report_summary(data):
    billed = [row for row in data if row["billing_status"] == "Billed"]
    pending = [row for row in data if row["billing_status"] == "Pending"]
    not_billable = [
        row for row in data
        if row["billing_status"] in ("No Vendor", "No Rate", "No Distance")
    ]
    pending_amount = sum(row["billable_amount"] for row in pending)
    billed_amount = sum(row["billable_amount"] for row in billed)

    return [
        {"label": _("Completed Trips"), "value": len(data), "indicator": "Blue"},
        {"label": _("Billed"), "value": len(billed), "indicator": "Green"},
        {"label": _("Billed Amount"), "value": billed_amount, "datatype": "Currency",
         "indicator": "Green"},
        {"label": _("Pending"), "value": len(pending), "indicator": "Blue"},
        {"label": _("Pending Amount"), "value": pending_amount, "datatype": "Currency",
         "indicator": "Orange"},
        {"label": _("Not Billable"), "value": len(not_billable), "indicator": "Red"},
    ]
