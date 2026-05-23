# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Trip Analytics — booking volume, outcomes and detour distance per route.

Sourced from Cab Request, grouped by assigned_route. The chart shows the
overall status mix across the filtered period; the table breaks it down by
route. `distance_from_route` is the employee's pickup detour in km.
"""

import frappe
from frappe import _

STATUS_COLORS = {
    "Completed": "#28a745",
    "In Trip": "#17a2b8",
    "Assigned": "#007bff",
    "Pending": "#ffc107",
    "Cancelled": "#dc3545",
}


def execute(filters=None):
    filters = frappe._dict(filters or {})
    data = get_data(filters)
    status_mix = get_status_mix(filters)
    return (
        get_columns(),
        data,
        None,
        get_chart(status_mix),
        get_report_summary(data, status_mix),
    )


def get_columns():
    return [
        {"label": _("Route"), "fieldname": "route", "fieldtype": "Link",
         "options": "Cab Route", "width": 220},
        {"label": _("Total Trips"), "fieldname": "total_trips", "fieldtype": "Int", "width": 110},
        {"label": _("Completed"), "fieldname": "completed", "fieldtype": "Int", "width": 110},
        {"label": _("In Trip"), "fieldname": "in_trip", "fieldtype": "Int", "width": 100},
        {"label": _("Cancelled"), "fieldname": "cancelled", "fieldtype": "Int", "width": 110},
        {"label": _("Avg Detour (km)"), "fieldname": "avg_detour", "fieldtype": "Float", "width": 140},
        {"label": _("Total Distance (km)"), "fieldname": "total_distance", "fieldtype": "Float", "width": 160},
    ]


def _conditions(filters):
    conditions = ["assigned_route IS NOT NULL", "assigned_route != ''"]
    if filters.get("from_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) <= %(to_date)s")
    if filters.get("route"):
        conditions.append("assigned_route = %(route)s")
    return " AND ".join(conditions)


def get_data(filters):
    return frappe.db.sql(
        """
        SELECT
            assigned_route AS route,
            COUNT(name) AS total_trips,
            SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'In Trip'   THEN 1 ELSE 0 END) AS in_trip,
            SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled,
            ROUND(AVG(NULLIF(distance_from_route, 0)), 2) AS avg_detour,
            SUM(COALESCE(total_distance, 0)) AS total_distance
        FROM `tabCab Request`
        WHERE {where}
        GROUP BY assigned_route
        ORDER BY total_trips DESC
        """.format(where=_conditions(filters)),
        filters,
        as_dict=True,
    )


def get_status_mix(filters):
    """Overall status counts across the filtered period (for the chart)."""
    conditions = ["1 = 1"]
    if filters.get("from_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) <= %(to_date)s")
    if filters.get("route"):
        conditions.append("assigned_route = %(route)s")

    rows = frappe.db.sql(
        """
        SELECT COALESCE(NULLIF(status, ''), 'Pending') AS status, COUNT(name) AS count
        FROM `tabCab Request`
        WHERE {where}
        GROUP BY status
        ORDER BY count DESC
        """.format(where=" AND ".join(conditions)),
        filters,
        as_dict=True,
    )
    return rows


def get_chart(status_mix):
    if not status_mix:
        return None
    return {
        "type": "donut",
        "data": {
            "labels": [row["status"] for row in status_mix],
            "datasets": [{"values": [row["count"] for row in status_mix]}],
        },
        "colors": [STATUS_COLORS.get(row["status"], "#6c757d") for row in status_mix],
    }


def get_report_summary(data, status_mix):
    total = sum(row["count"] for row in status_mix)
    completed = next((r["count"] for r in status_mix if r["status"] == "Completed"), 0)
    cancelled = next((r["count"] for r in status_mix if r["status"] == "Cancelled"), 0)
    distance = sum(row["total_distance"] for row in data)
    rate = round(completed / total * 100, 1) if total else 0

    return [
        {"label": _("Total Trips"), "value": total, "indicator": "Blue"},
        {"label": _("Completed"), "value": completed, "indicator": "Green"},
        {"label": _("Cancelled"), "value": cancelled, "indicator": "Red"},
        {"label": _("Routes Used"), "value": len(data), "indicator": "Blue"},
        {
            "label": _("Completion Rate"),
            "value": f"{rate}%",
            "indicator": "Green" if rate >= 70 else "Orange",
        },
        {"label": _("Total Distance (km)"), "value": distance, "indicator": "Blue"},
    ]
