# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Vehicle Utilization — trip load, distance and active days per vehicle.

Sourced from Cab Request, grouped by assigned_cab. `active_days` counts the
distinct trip dates a vehicle was used, which exposes idle vehicles when
compared against the filtered date range.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, getdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    data = get_data(filters)
    return get_columns(), data, None, get_chart(data), get_report_summary(data, filters)


def get_columns():
    return [
        {"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Data", "width": 180},
        {"label": _("Total Trips"), "fieldname": "total_trips", "fieldtype": "Int", "width": 110},
        {"label": _("Completed"), "fieldname": "completed", "fieldtype": "Int", "width": 110},
        {"label": _("Cancelled"), "fieldname": "cancelled", "fieldtype": "Int", "width": 110},
        {"label": _("Active Days"), "fieldname": "active_days", "fieldtype": "Int", "width": 110},
        {"label": _("Total Distance (km)"), "fieldname": "total_distance", "fieldtype": "Float", "width": 160},
    ]


def get_data(filters):
    conditions = ["assigned_cab IS NOT NULL", "assigned_cab != ''"]
    if filters.get("from_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("COALESCE(travel_date, DATE(booking_datetime)) <= %(to_date)s")
    if filters.get("vehicle"):
        conditions.append("assigned_cab = %(vehicle)s")

    return frappe.db.sql(
        """
        SELECT
            assigned_cab AS vehicle,
            COUNT(name) AS total_trips,
            SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled,
            COUNT(DISTINCT COALESCE(travel_date, DATE(booking_datetime))) AS active_days,
            SUM(COALESCE(total_distance, 0)) AS total_distance
        FROM `tabCab Request`
        WHERE {where}
        GROUP BY assigned_cab
        ORDER BY total_trips DESC
        """.format(where=" AND ".join(conditions)),
        filters,
        as_dict=True,
    )


def get_chart(data):
    top = data[:10]
    if not top:
        return None
    return {
        "type": "bar",
        "data": {
            "labels": [row["vehicle"] for row in top],
            "datasets": [{"name": _("Total Trips"), "values": [row["total_trips"] for row in top]}],
        },
        "colors": ["#007bff"],
    }


def get_report_summary(data, filters):
    total_trips = sum(row["total_trips"] for row in data)
    total_distance = sum(row["total_distance"] for row in data)
    vehicles_used = len(data)

    # Average utilisation = active days / days in the selected window.
    window_days = 0
    if filters.get("from_date") and filters.get("to_date"):
        window_days = date_diff(getdate(filters["to_date"]), getdate(filters["from_date"])) + 1

    if window_days and vehicles_used:
        avg_days = sum(row["active_days"] for row in data) / vehicles_used
        utilisation = round(avg_days / window_days * 100, 1)
    else:
        utilisation = 0

    return [
        {"label": _("Vehicles Used"), "value": vehicles_used, "indicator": "Blue"},
        {"label": _("Total Trips"), "value": total_trips, "indicator": "Blue"},
        {"label": _("Total Distance (km)"), "value": total_distance, "indicator": "Blue"},
        {
            "label": _("Avg Utilisation"),
            "value": f"{utilisation}%",
            "indicator": "Green" if utilisation >= 50 else "Orange",
        },
    ]
