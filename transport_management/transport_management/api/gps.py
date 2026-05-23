# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""In-house GPS tracking API for the Transport Management app.

  update_vehicle_location()    — ingest: a GPS device / driver app POSTs a ping.
  get_live_vehicle_locations() — serve: latest position per vehicle, for the
                                 manager live map.
  get_vehicle_track()          — serve: recent GPS trail for one vehicle.
  purge_old_gps_logs()         — daily scheduler job: prune stale GPS history.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, now_datetime, time_diff_in_seconds

GPS_POST_ROLES = {"Driver", "Fleet Manager", "System Manager"}
GPS_VIEW_ROLES = {"Fleet Manager", "System Manager"}
DEFAULT_STALE_MINUTES = 10
DEFAULT_RETENTION_DAYS = 30


def _assert_can_post_for(vehicle):
    """Authorise a GPS post.

    Managers may post for any vehicle; a Driver may post only for the vehicle
    assigned to them (resolved via their active route / Vehicle master). This
    blocks a driver from spoofing another vehicle's location.
    """
    roles = set(frappe.get_roles())
    if roles & {"Fleet Manager", "System Manager"}:
        return
    if "Driver" not in roles:
        frappe.throw(_("You are not permitted to post vehicle locations."),
                     frappe.PermissionError)

    from transport_management.transport_management.doctype.vehicle_log.vehicle_log import (
        get_driver_vehicle_defaults,
    )
    assigned = (get_driver_vehicle_defaults() or {}).get("license_plate")
    if not assigned or assigned != vehicle:
        frappe.throw(
            _("You can only post locations for your assigned vehicle ({0}).").format(
                assigned or _("none")),
            frappe.PermissionError,
        )


@frappe.whitelist(methods=["POST"])
def update_vehicle_location(vehicle, latitude, longitude, speed_kmph=None,
                            recorded_at=None, driver=None):
    """Ingest one GPS ping. Called by the driver app or an on-board device."""
    if not frappe.db.exists("Vehicle", vehicle):
        frappe.throw(_("Vehicle {0} was not found.").format(vehicle))

    _assert_can_post_for(vehicle)

    log = frappe.get_doc({
        "doctype": "Vehicle GPS Log",
        "vehicle": vehicle,
        "latitude": flt(latitude),
        "longitude": flt(longitude),
        "speed_kmph": flt(speed_kmph) if speed_kmph not in (None, "") else None,
        "recorded_at": recorded_at or now_datetime(),
        "source": "API",
        "driver": driver,
    })
    log.insert(ignore_permissions=True)

    return {"status": "success", "log": log.name, "recorded_at": str(log.recorded_at)}


@frappe.whitelist()
def get_live_vehicle_locations(stale_minutes=None):
    """Latest known position per vehicle, for the manager live map."""
    if not (set(frappe.get_roles()) & GPS_VIEW_ROLES):
        frappe.throw(_("Access denied."), frappe.PermissionError)

    stale_minutes = int(stale_minutes or DEFAULT_STALE_MINUTES)

    # Latest log per vehicle via a max(recorded_at) self-join.
    rows = frappe.db.sql(
        """
        SELECT g.vehicle, g.latitude, g.longitude, g.speed_kmph, g.recorded_at
        FROM `tabVehicle GPS Log` g
        INNER JOIN (
            SELECT vehicle, MAX(recorded_at) AS max_at
            FROM `tabVehicle GPS Log`
            GROUP BY vehicle
        ) latest ON latest.vehicle = g.vehicle AND latest.max_at = g.recorded_at
        """,
        as_dict=True,
    )

    now = now_datetime()
    seen = set()
    locations = []
    for row in rows:
        # Guard against two rows sharing the exact same max recorded_at.
        if row["vehicle"] in seen:
            continue
        seen.add(row["vehicle"])

        age_seconds = time_diff_in_seconds(now, row["recorded_at"])
        locations.append({
            "vehicle": row["vehicle"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "speed_kmph": row["speed_kmph"],
            "recorded_at": str(row["recorded_at"]),
            "minutes_ago": round(age_seconds / 60, 1),
            "is_stale": age_seconds > stale_minutes * 60,
        })
    return locations


@frappe.whitelist()
def get_vehicle_track(vehicle, limit=100):
    """Recent GPS trail for a single vehicle, newest first."""
    if not (set(frappe.get_roles()) & GPS_VIEW_ROLES):
        frappe.throw(_("Access denied."), frappe.PermissionError)

    return frappe.get_all(
        "Vehicle GPS Log",
        filters={"vehicle": vehicle},
        fields=["name", "latitude", "longitude", "speed_kmph", "recorded_at"],
        order_by="recorded_at desc",
        limit=int(limit or 100),
    )


def purge_old_gps_logs():
    """Daily scheduler job — delete GPS logs older than the configured retention.

    Retention is read from Transport Settings (gps_log_retention_days); 0 or
    blank disables purging.
    """
    days = frappe.db.get_single_value("Transport Settings", "gps_log_retention_days")
    days = int(days or DEFAULT_RETENTION_DAYS)
    if days <= 0:
        return

    cutoff = add_days(now_datetime(), -days)
    stale = {"recorded_at": ["<", cutoff]}
    count = frappe.db.count("Vehicle GPS Log", stale)
    if not count:
        return

    frappe.db.delete("Vehicle GPS Log", stale)
    frappe.db.commit()
    frappe.logger("transport_management").info(
        f"Purged {count} Vehicle GPS Log row(s) older than {days} day(s)."
    )
