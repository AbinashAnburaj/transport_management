import frappe


def execute():
    """Reset Cab Request.docstatus to 0 now that the doctype is no longer submittable.

    The app's lifecycle is driven by the custom `status` field — keeping any
    submitted (`docstatus = 1`) or cancelled-via-submit (`docstatus = 2`) rows
    around would silently lock or hide records the operator expects to edit.
    """
    if not frappe.db.table_exists("Cab Request"):
        return

    frappe.db.sql(
        """
        UPDATE `tabCab Request`
        SET docstatus = 0
        WHERE docstatus IN (1, 2)
        """
    )
    frappe.db.commit()
