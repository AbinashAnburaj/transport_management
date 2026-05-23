# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Add compliance & maintenance tracking fields to the standard Vehicle doctype.

These fields back the daily compliance and maintenance scheduler jobs:
  - custom_permit_expiry_date / custom_fitness_expiry_date / custom_road_tax_expiry_date
  - custom_next_service_date / custom_service_interval_km / custom_next_service_odometer

Insurance (end_date), pollution (carbon_check_date) and driver licence
(Driver.expiry_date) already exist on the standard doctypes and are reused.

Idempotent: `create_custom_fields(update=True)` only inserts missing fields and
refreshes existing ones, so this patch is safe to re-run.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields(
        {
            "Vehicle": [
                {
                    "fieldname": "custom_compliance_section",
                    "fieldtype": "Section Break",
                    "label": "Compliance & Maintenance",
                    "insert_after": "carbon_check_date",
                    "collapsible": 1,
                },
                {
                    "fieldname": "custom_permit_expiry_date",
                    "fieldtype": "Date",
                    "label": "Permit Expiry Date",
                    "insert_after": "custom_compliance_section",
                },
                {
                    "fieldname": "custom_fitness_expiry_date",
                    "fieldtype": "Date",
                    "label": "Fitness Certificate Expiry",
                    "insert_after": "custom_permit_expiry_date",
                },
                {
                    "fieldname": "custom_road_tax_expiry_date",
                    "fieldtype": "Date",
                    "label": "Road Tax Expiry Date",
                    "insert_after": "custom_fitness_expiry_date",
                },
                {
                    "fieldname": "custom_maintenance_column",
                    "fieldtype": "Column Break",
                    "insert_after": "custom_road_tax_expiry_date",
                },
                {
                    "fieldname": "custom_next_service_date",
                    "fieldtype": "Date",
                    "label": "Next Service Date",
                    "insert_after": "custom_maintenance_column",
                },
                {
                    "fieldname": "custom_service_interval_km",
                    "fieldtype": "Int",
                    "label": "Service Interval (KM)",
                    "insert_after": "custom_next_service_date",
                },
                {
                    "fieldname": "custom_next_service_odometer",
                    "fieldtype": "Int",
                    "label": "Next Service Odometer",
                    "insert_after": "custom_service_interval_km",
                },
            ]
        },
        update=True,
    )

    frappe.clear_cache(doctype="Vehicle")
