# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Fuel Analytics — fuel consumption, mileage and running cost per vehicle.

Sourced from Vehicle Log. Distance is computed as (odometer - last_odometer)
per log row rather than read from `daily_distance`, because that field is
stored as a varchar. Cancelled logs (docstatus 2) are excluded.

Mileage  = total distance / total fuel quantity   (km per litre)
Cost/km  = total fuel cost / total distance        (currency per km)
"""

import frappe
from frappe import _


def execute(filters=None):
    filters = frappe._dict(filters or {})
    data = get_data(filters)
    return get_columns(), data, None, get_chart(data), get_report_summary(data)


def get_columns():
    return [
        {"label": _("Vehicle"), "fieldname": "vehicle", "fieldtype": "Link",
         "options": "Vehicle", "width": 180},
        {"label": _("Logs"), "fieldname": "log_count", "fieldtype": "Int", "width": 80},
        {"label": _("Total Fuel (L)"), "fieldname": "total_fuel", "fieldtype": "Float", "width": 130},
        {"label": _("Total Fuel Cost"), "fieldname": "total_cost", "fieldtype": "Currency", "width": 140},
        {"label": _("Distance (km)"), "fieldname": "total_distance", "fieldtype": "Float", "width": 130},
        {"label": _("Mileage (km/L)"), "fieldname": "mileage", "fieldtype": "Float", "width": 130},
        {"label": _("Cost / km"), "fieldname": "cost_per_km", "fieldtype": "Currency", "width": 120},
    ]


def get_data(filters):
    conditions = ["docstatus < 2", "license_plate IS NOT NULL", "license_plate != ''"]
    if filters.get("from_date"):
        conditions.append("`date` >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("`date` <= %(to_date)s")
    if filters.get("vehicle"):
        conditions.append("license_plate = %(vehicle)s")

    rows = frappe.db.sql(
        """
        SELECT
            license_plate AS vehicle,
            COUNT(name) AS log_count,
            SUM(COALESCE(fuel_qty, 0)) AS total_fuel,
            SUM(COALESCE(price, 0)) AS total_cost,
            SUM(GREATEST(COALESCE(odometer, 0) - COALESCE(last_odometer, 0), 0)) AS total_distance
        FROM `tabVehicle Log`
        WHERE {where}
        GROUP BY license_plate
        ORDER BY total_cost DESC
        """.format(where=" AND ".join(conditions)),
        filters,
        as_dict=True,
    )

    for row in rows:
        fuel = row["total_fuel"] or 0
        distance = row["total_distance"] or 0
        row["mileage"] = round(distance / fuel, 2) if fuel else 0
        row["cost_per_km"] = round(row["total_cost"] / distance, 2) if distance else 0
    return rows


def get_chart(data):
    top = data[:10]
    if not top:
        return None
    return {
        "type": "bar",
        "data": {
            "labels": [row["vehicle"] for row in top],
            "datasets": [{"name": _("Mileage (km/L)"), "values": [row["mileage"] for row in top]}],
        },
        "colors": ["#17a2b8"],
    }


def get_report_summary(data):
    total_fuel = sum(row["total_fuel"] for row in data)
    total_cost = sum(row["total_cost"] for row in data)
    total_distance = sum(row["total_distance"] for row in data)
    avg_mileage = round(total_distance / total_fuel, 2) if total_fuel else 0
    avg_cost_km = round(total_cost / total_distance, 2) if total_distance else 0

    return [
        {"label": _("Total Fuel (L)"), "value": round(total_fuel, 2), "indicator": "Blue"},
        {"label": _("Total Fuel Cost"), "value": total_cost, "datatype": "Currency", "indicator": "Red"},
        {"label": _("Distance (km)"), "value": total_distance, "indicator": "Blue"},
        {"label": _("Avg Mileage (km/L)"), "value": avg_mileage,
         "indicator": "Green" if avg_mileage >= 10 else "Orange"},
        {"label": _("Avg Cost / km"), "value": avg_cost_km, "datatype": "Currency", "indicator": "Orange"},
    ]
