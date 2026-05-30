# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""In-house GPS tracking API for the Transport Management app.

  update_vehicle_location()    — ingest: a GPS device / driver app POSTs a ping.
  get_live_vehicle_locations() — serve: latest position per vehicle, for the
                                 manager live map.
  get_vehicle_track()          — serve: recent GPS trail for one vehicle.
  purge_old_gps_logs()         — daily scheduler job: prune stale GPS history.
"""

import math

import frappe
from frappe import _
from frappe.utils import add_days, flt, now_datetime, time_diff_in_seconds

GPS_POST_ROLES = {"Driver", "Fleet Manager", "System Manager"}
GPS_VIEW_ROLES = {"Fleet Manager", "System Manager"}
DEFAULT_STALE_MINUTES = 10
DEFAULT_RETENTION_DAYS = 30

# Geofence radius (km) around a route's start/end point that triggers a notify.
GEOFENCE_RADIUS_KM = 0.15
# Don't re-notify the same {request, event} pair within this window.
GEOFENCE_DEDUPE_SECONDS = 300


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
                assigned or _("No vehicle is assigned to your active route.")),
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

    # Phase C — broadcast the ping to subscribed manager pages in real time.
    # Scoped to the Vehicle GPS Log doctype room so clients that called
    # `frappe.realtime.doctype_subscribe('Vehicle GPS Log')` receive it.
    frappe.publish_realtime(
        event="tms_vehicle_location",
        message={
            "vehicle": vehicle,
            "latitude": flt(latitude),
            "longitude": flt(longitude),
            "speed_kmph": flt(speed_kmph) if speed_kmph not in (None, "") else None,
            "recorded_at": str(log.recorded_at),
        },
        doctype="Vehicle GPS Log",
        after_commit=True,
    )

    _check_geofence_events(vehicle, flt(latitude), flt(longitude))

    return {"status": "success", "log": log.name, "recorded_at": str(log.recorded_at)}


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _check_geofence_events(vehicle, lat, lng):
    """Notify managers when an active Cab Request's vehicle reaches its
    pickup or dropoff geofence. Never mutates Cab Request status — this is
    a notify-only signal.
    """
    request = frappe.db.get_value(
        "Cab Request",
        {"assigned_cab": vehicle, "status": ["in", ["Assigned", "In Trip"]]},
        ["name", "status", "assigned_route", "employee_name",
         "pickup_lat", "pickup_lng"],
        as_dict=True,
        order_by="modified desc",
    )
    if not request or not request.assigned_route:
        return

    route = frappe.db.get_value(
        "Cab Route",
        request.assigned_route,
        ["start_lat", "start_lng", "end_lat", "end_lng", "route_name"],
        as_dict=True,
    )
    if not route:
        return

    # Use the employee's actual pickup point for the arrival geofence — falling
    # back to the route's start only when the request doesn't carry a pickup.
    # Using the route start on a long route would fire "driver arrived" while
    # the vehicle is still kilometres away from the rider.
    pickup_lat = request.pickup_lat or route.start_lat
    pickup_lng = request.pickup_lng or route.start_lng

    candidates = []
    if request.status == "Assigned" and pickup_lat and pickup_lng:
        d = _haversine_km(lat, lng, pickup_lat, pickup_lng)
        if d <= GEOFENCE_RADIUS_KM:
            candidates.append(("driver_at_pickup",
                               _("Driver has arrived at pickup for {0}").format(request.employee_name or request.name)))
    if request.status == "In Trip" and route.end_lat and route.end_lng:
        d = _haversine_km(lat, lng, route.end_lat, route.end_lng)
        if d <= GEOFENCE_RADIUS_KM:
            candidates.append(("trip_arriving",
                               _("Trip {0} is arriving at destination").format(request.name)))

    for event, label in candidates:
        cache_key = f"tms:geofence:{request.name}:{event}"
        if frappe.cache().get_value(cache_key):
            continue
        frappe.cache().set_value(cache_key, 1, expires_in_sec=GEOFENCE_DEDUPE_SECONDS)

        frappe.publish_realtime(
            event="tms_geofence_event",
            message={
                "cab_request": request.name,
                "route": request.assigned_route,
                "route_name": route.route_name,
                "vehicle": vehicle,
                "event": event,
                "label": label,
            },
            doctype="Vehicle GPS Log",
            after_commit=True,
        )


@frappe.whitelist()
def get_live_vehicle_locations(stale_minutes=None):
    """Latest known position per vehicle, for the manager live map."""
    if not (set(frappe.get_roles()) & GPS_VIEW_ROLES):
        frappe.throw(_("Access denied."), frappe.PermissionError)

    stale_minutes = int(stale_minutes or DEFAULT_STALE_MINUTES)

    # Cap how far back we look. Without this, vehicles that stopped pinging
    # months ago still appear as "ghost" pins on the manager live map, and the
    # self-join grows linearly with all-time Vehicle GPS Log history.
    lookback_minutes = max(stale_minutes * 6, 60 * 24)

    rows = frappe.db.sql(
        """
        SELECT g.vehicle, g.latitude, g.longitude, g.speed_kmph, g.recorded_at
        FROM `tabVehicle GPS Log` g
        INNER JOIN (
            SELECT vehicle, MAX(recorded_at) AS max_at
            FROM `tabVehicle GPS Log`
            WHERE recorded_at >= DATE_SUB(NOW(), INTERVAL %(lookback)s MINUTE)
            GROUP BY vehicle
        ) latest ON latest.vehicle = g.vehicle AND latest.max_at = g.recorded_at
        """,
        {"lookback": lookback_minutes},
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
def can_i_post_for_request(cab_request):
    """Resolve whether the current user is the assigned driver for a Cab Request.

    Replaces a naive client-side `assigned_driver == session.user` compare —
    assigned_driver may hold a User email, Driver doc name, Employee ID, or
    Employee full name. Re-uses _get_driver_identity_candidates so the four
    shapes are handled identically to the rest of the app.

    Returns:
      {"can_post": True,  "vehicle": "<plate>"}                 — start pinger
      {"can_post": False, "reason": "not_active"}               — wrong status
      {"can_post": False, "reason": "no_vehicle"}               — assigned_cab unset
      {"can_post": False, "reason": "not_assigned"}             — caller is not the driver
      {"can_post": False, "reason": "not_found"}                — bad cab_request name
    """
    from transport_management.transport_management.doctype.cab_request.cab_request import (
        _get_driver_identity_candidates,
    )

    if not frappe.db.exists("Cab Request", cab_request):
        return {"can_post": False, "reason": "not_found"}

    req = frappe.db.get_value(
        "Cab Request",
        cab_request,
        ["status", "assigned_driver", "assigned_cab"],
        as_dict=True,
    )

    if req.status not in ("Assigned", "In Trip"):
        return {"can_post": False, "reason": "not_active"}
    if not req.assigned_cab:
        return {"can_post": False, "reason": "no_vehicle"}

    candidates = _get_driver_identity_candidates(frappe.session.user)
    if req.assigned_driver not in candidates:
        return {"can_post": False, "reason": "not_assigned"}

    return {"can_post": True, "vehicle": req.assigned_cab}


@frappe.whitelist()
def get_my_driver_location(cab_request, stale_minutes=None):
    """Latest GPS ping for the vehicle assigned to a Cab Request.

    Authorised callers:
      - Fleet Manager / System Manager   (any request)
      - The Employee who owns the request (only their own — matched by
        Employee.user_id OR Cab Request.owner)

    Returns a payload with `available` False and a `reason` when there is
    nothing to show (trip not active, no vehicle yet, no pings yet); never
    raises in those cases so the client can render a neutral status.
    """
    if not frappe.db.exists("Cab Request", cab_request):
        frappe.throw(_("Cab Request {0} not found.").format(cab_request))

    req = frappe.db.get_value(
        "Cab Request",
        cab_request,
        ["status", "assigned_cab", "employee_id", "owner"],
        as_dict=True,
    )

    roles = set(frappe.get_roles())
    if not (roles & GPS_VIEW_ROLES):
        user = frappe.session.user
        employee_id = frappe.db.get_value("Employee", {"user_id": user}, "name")
        owns = req.owner == user or (employee_id and req.employee_id == employee_id)
        if not owns:
            frappe.throw(
                _("You are not authorised to view this driver's location."),
                frappe.PermissionError,
            )

    if req.status not in ("Assigned", "In Trip"):
        return {
            "available": False,
            "reason": "not_active",
            "message": _("No live tracking — this trip is not currently active."),
        }

    if not req.assigned_cab:
        return {
            "available": False,
            "reason": "no_vehicle",
            "message": _("No vehicle assigned to this booking yet."),
        }

    log = frappe.db.get_value(
        "Vehicle GPS Log",
        {"vehicle": req.assigned_cab},
        ["latitude", "longitude", "speed_kmph", "recorded_at"],
        order_by="recorded_at desc",
        as_dict=True,
    )
    if not log:
        return {
            "available": False,
            "reason": "no_pings_yet",
            "vehicle": req.assigned_cab,
            "message": _("Driver has not started sharing their location yet."),
        }

    stale_minutes = int(stale_minutes or DEFAULT_STALE_MINUTES)
    age_seconds = time_diff_in_seconds(now_datetime(), log["recorded_at"])
    return {
        "available": True,
        "vehicle": req.assigned_cab,
        "latitude": log["latitude"],
        "longitude": log["longitude"],
        "speed_kmph": log["speed_kmph"],
        "recorded_at": str(log["recorded_at"]),
        "seconds_ago": round(age_seconds),
        "is_stale": age_seconds > stale_minutes * 60,
    }


@frappe.whitelist()
def get_vehicle_track(vehicle, limit=100):
    """Recent GPS trail for a single vehicle, newest first."""
    if not (set(frappe.get_roles()) & GPS_VIEW_ROLES):
        frappe.throw(_("Access denied."), frappe.PermissionError)

    # M-5: Cap at 1000 to prevent unbounded result sets / DoS via large limit param.
    limit = min(int(limit or 100), 1000)
    return frappe.get_all(
        "Vehicle GPS Log",
        filters={"vehicle": vehicle},
        fields=["name", "latitude", "longitude", "speed_kmph", "recorded_at"],
        order_by="recorded_at desc",
        limit=limit,
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
