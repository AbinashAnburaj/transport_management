import frappe


def execute():
    """Update the existing "Approved Trips" Number Card to a valid filter.

    The card historically filtered on `status = "Approved"`, which is not a
    valid Cab Request status — so it always rendered 0. Re-point it at the
    Pending status and rename the visible label. Leaves the doc.name alone so
    any workspace reference (none today, but defensive) keeps resolving.
    """
    name = "Approved Trips"
    if not frappe.db.exists("Number Card", name):
        return

    frappe.db.set_value(
        "Number Card",
        name,
        {
            "label": "Pending Trips",
            "filters_json": '[["Cab Request","status","=","Pending",false]]',
        },
    )
    frappe.clear_cache(doctype="Number Card")
    frappe.db.commit()
