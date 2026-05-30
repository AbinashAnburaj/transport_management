# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Driver Performance — trips, completion rate and distance per driver.

Sourced from Cab Request. Trips are bucketed by the app-managed `status`
field (not docstatus), since the booking lifecycle is driven by `status`.
The trip date uses travel_date, falling back to the date part of
booking_datetime to match how the booking flow stores dates.
"""

import frappe
from frappe import _


def execute(filters=None):
    filters = frappe._dict(filters or {})
    data = get_data(filters)
    return get_columns(), data, None, get_chart(data), get_report_summary(data)


def get_columns():
    return [
        {"label": _("Driver"), "fieldname": "driver", "fieldtype": "Data", "width": 200},
        {"label": _("Total Trips"), "fieldname": "total_trips", "fieldtype": "Int", "width": 110},
        {"label": _("Completed"), "fieldname": "completed", "fieldtype": "Int", "width": 110},
        {"label": _("In Trip"), "fieldname": "in_trip", "fieldtype": "Int", "width": 100},
        {"label": _("Cancelled"), "fieldname": "cancelled", "fieldtype": "Int", "width": 110},
        {"label": _("Completion Rate"), "fieldname": "completion_rate", "fieldtype": "Percent", "width": 140},
        {"label": _("Total Distance (km)"), "fieldname": "total_distance", "fieldtype": "Float", "width": 160},
    ]


def get_data(filters):
    conditions = ["assigned_driver IS NOT NULL", "assigned_driver != ''"]
    if filters.get("from_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) <= %(to_date)s")
    if filters.get("driver"):
        conditions.append("assigned_driver = %(driver)s")

    rows = frappe.db.sql(
        """
        SELECT
            assigned_driver AS driver,
            COUNT(name) AS total_trips,
            SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'In Trip'   THEN 1 ELSE 0 END) AS in_trip,
            SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled,
            SUM(COALESCE(total_distance, 0)) AS total_distance
        FROM `tabCab Request`
        WHERE {where}
        GROUP BY assigned_driver
        ORDER BY total_trips DESC
        """.format(where=" AND ".join(conditions)),
        filters,
        as_dict=True,
    )

    for row in rows:
        row["completion_rate"] = (
            round(row["completed"] / row["total_trips"] * 100, 1) if row["total_trips"] else 0
        )
    return rows


def get_chart(data):
    top = data[:10]
    if not top:
        return None
    return {
        "type": "bar",
        "data": {
            "labels": [row["driver"] for row in top],
            "datasets": [
                {"name": _("Completed"), "values": [row["completed"] for row in top]},
                {"name": _("Cancelled"), "values": [row["cancelled"] for row in top]},
            ],
        },
        "colors": ["#28a745", "#dc3545"],
    }


def get_report_summary(data):
    total = sum(row["total_trips"] for row in data)
    completed = sum(row["completed"] for row in data)
    cancelled = sum(row["cancelled"] for row in data)
    distance = sum(row["total_distance"] for row in data)
    rate = round(completed / total * 100, 1) if total else 0

    return [
        {"label": _("Total Trips"), "value": total, "indicator": "Blue"},
        {"label": _("Completed"), "value": completed, "indicator": "Green"},
        {"label": _("Cancelled"), "value": cancelled, "indicator": "Red"},
        {
            "label": _("Completion Rate"),
            "value": f"{rate}%",
            "indicator": "Green" if rate >= 70 else "Orange",
        },
        {"label": _("Total Distance (km)"), "value": distance, "indicator": "Blue"},
    ]
