# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Vendor billing automation for the Transport Management app.

Turns Completed Cab Requests into Cab Vendor Invoices, grouped by vendor and
billing month. Billing is per-kilometre: amount = rate x total_distance.

A trip is billable only when it is Completed, has a vendor, a rate > 0, a
recorded total_distance > 0, and is NOT already linked to an invoice. The
`Cab Request.invoice_link` field is the single source of truth that prevents
double-billing and drives the Vendor Billing Reconciliation report.

Entry points:
  - generate_vendor_invoices()  -> whitelisted, on-demand (manager button)
  - monthly_vendor_billing()    -> scheduled, bills the previous month
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, formatdate, get_first_day, getdate, today

COMPLETED_STATUS = "Completed"
DEFAULT_CHARGE_TYPE = "Rent"
MANAGER_ROLES = {"Fleet Manager", "System Manager"}


# ─────────────────────────────────────────────────────────────
#  ELIGIBILITY
# ─────────────────────────────────────────────────────────────
def get_billable_trips(billing_month=None, vendor=None):
    """Return Completed, un-invoiced trips that can be billed.

    `billing_month` — restrict to one month (any date within it).
    `vendor`        — restrict to one Supplier.
    """
    filters = {
        "status": COMPLETED_STATUS,
        "vendor": ["is", "set"],
        "rate": [">", 0],
        "total_distance": [">", 0],
    }
    if vendor:
        filters["vendor"] = vendor

    trips = frappe.get_all(
        "Cab Request",
        filters=filters,
        fields=[
            "name", "vendor", "rate", "total_distance", "travel_date",
            "billing_month", "assigned_route", "assigned_cab", "invoice_link",
        ],
    )

    # Exclude trips already linked to an invoice (invoice_link is a Data field).
    trips = [t for t in trips if not (t.get("invoice_link") or "").strip()]

    if billing_month:
        target = get_first_day(getdate(billing_month))
        trips = [t for t in trips if _billing_period(t) == target]

    return trips


def _billing_period(trip):
    """First day of the month a trip belongs to (billing_month, else travel_date)."""
    ref_date = trip.get("billing_month") or trip.get("travel_date")
    return get_first_day(getdate(ref_date)) if ref_date else None


def _trip_amount(trip):
    """Per-km billing: rate x distance."""
    return flt(trip["rate"]) * flt(trip["total_distance"])


# ─────────────────────────────────────────────────────────────
#  CORE — group trips and create invoices
# ─────────────────────────────────────────────────────────────
def generate_invoices(billing_month=None, vendor=None):
    """Group billable trips by (vendor, month) and create one invoice each.

    Each (vendor, month) group is committed independently — a failure in one
    group is logged and rolled back without affecting the others.
    """
    trips = get_billable_trips(billing_month=billing_month, vendor=vendor)

    groups = {}
    skipped_no_period = []
    for trip in trips:
        period = _billing_period(trip)
        if not period:
            skipped_no_period.append(trip["name"])
            continue
        groups.setdefault((trip["vendor"], period), []).append(trip)

    created = []
    for (group_vendor, period), group_trips in groups.items():
        try:
            invoice_name, total, billed = _create_invoice_for_group(group_vendor, group_trips)
            frappe.db.commit()
            if invoice_name:
                created.append({
                    "invoice": invoice_name,
                    "vendor": group_vendor,
                    "billing_month": str(period),
                    "trips": billed,
                    "total_amount": total,
                })
        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Vendor billing failed: {group_vendor} / {period}",
            )

    return {
        "invoice_count": len(created),
        "trip_count": sum(row["trips"] for row in created),
        "created": created,
        "skipped_no_period": skipped_no_period,
    }


def _create_invoice_for_group(vendor, trips):
    """Create one Cab Vendor Invoice for a vendor's trips and link them back.

    Returns (invoice_name, total, billed_count). Each candidate trip's
    invoice_link is re-read WITH A ROW LOCK and skipped if already billed —
    this closes the race between get_billable_trips() and the invoice_link
    write when two billing runs overlap. If every trip was already billed,
    returns (None, 0.0, 0) and no invoice is created.
    """
    unbilled = []
    for trip in trips:
        current = frappe.db.get_value(
            "Cab Request", trip["name"], "invoice_link", for_update=True
        )
        if not (current or "").strip():
            unbilled.append(trip)
    if not unbilled:
        return None, 0.0, 0

    invoice = frappe.new_doc("Cab Vendor Invoice")
    invoice.vendor = vendor
    invoice.date = today()

    # trip_reference is a single Link to Cab Route — set it only when every
    # trip in the group shares the same route.
    routes = {t.get("assigned_route") for t in unbilled if t.get("assigned_route")}
    if len(routes) == 1:
        route = next(iter(routes))
        if frappe.db.exists("Cab Route", route):
            invoice.trip_reference = route

    total = 0.0
    for trip in unbilled:
        amount = _trip_amount(trip)
        total += amount
        invoice.append("items", {
            "charge_type": DEFAULT_CHARGE_TYPE,
            "description": _("Trip {0} on {1}{2}").format(
                trip["name"],
                formatdate(trip["travel_date"]) if trip.get("travel_date") else "-",
                f" — {trip['assigned_cab']}" if trip.get("assigned_cab") else "",
            ),
            "amount": amount,
        })

    invoice.total_amount = total
    invoice.insert(ignore_permissions=True)

    # Link each trip to the invoice — this is what prevents double-billing.
    for trip in unbilled:
        frappe.db.set_value("Cab Request", trip["name"], "invoice_link", invoice.name)

    return invoice.name, total, len(unbilled)


# ─────────────────────────────────────────────────────────────
#  ENTRY POINTS
# ─────────────────────────────────────────────────────────────
@frappe.whitelist()
def generate_vendor_invoices(billing_month=None, vendor=None):
    """On-demand generation — called from the Vendor Billing Reconciliation report."""
    _check_billing_permission()

    result = generate_invoices(billing_month=billing_month, vendor=vendor)

    if result["invoice_count"]:
        frappe.msgprint(
            _("Created {0} vendor invoice(s) covering {1} trip(s).").format(
                result["invoice_count"], result["trip_count"]),
            title=_("Vendor Billing"), indicator="green",
        )
    else:
        frappe.msgprint(
            _("No billable trips found. A trip must be Completed, have a vendor, "
              "a rate, a recorded distance, and not already be invoiced."),
            title=_("Vendor Billing"), indicator="orange",
        )
    return result


def monthly_vendor_billing():
    """Scheduled monthly entry point — bills the previous calendar month."""
    previous_month = get_first_day(add_months(getdate(today()), -1))
    result = generate_invoices(billing_month=previous_month)

    if result["invoice_count"]:
        frappe.logger("transport_management").info(
            "Monthly vendor billing for {0}: {1} invoice(s), {2} trip(s).".format(
                previous_month, result["invoice_count"], result["trip_count"])
        )


def _check_billing_permission():
    if not (set(frappe.get_roles()) & MANAGER_ROLES):
        frappe.throw(
            _("Only a Fleet Manager or System Manager can generate vendor invoices."),
            frappe.PermissionError,
        )
