# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

"""Add performance indexes for high-query-volume fields.

Indexes added:
  - tabCab Request: composite (assigned_route, travel_date, status)
      Used by _get_booked_seat_count and _get_booked_seat_counts hot paths.
      Individual indexes already exist on each column; the composite index
      lets MariaDB resolve seat-count queries with an index-only scan instead
      of three separate index merges.
  - tabCab Request: assigned_driver (verified present — skipped if exists)
  - tabVehicle GPS Log: composite (vehicle, recorded_at)
      Used by get_my_driver_location and the realtime GPS queries.

Idempotent: each index is only created if not already present.
Safe to re-run.
"""

import frappe


def _index_exists(table, index_name):
	"""Return True if an index with `index_name` already exists on `table`."""
	result = frappe.db.sql(
		"""
		SELECT COUNT(*) AS cnt
		FROM INFORMATION_SCHEMA.STATISTICS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME   = %s
		  AND INDEX_NAME   = %s
		""",
		(table, index_name),
		as_dict=True,
	)
	return bool(result and result[0].get("cnt", 0))


def execute():
	# ── 1. Composite index on Cab Request (assigned_route, travel_date, status) ─
	if not _index_exists("tabCab Request", "route_date_status_idx"):
		frappe.db.sql(
			"""
			ALTER TABLE `tabCab Request`
			ADD INDEX `route_date_status_idx` (assigned_route, travel_date, status)
			"""
		)
		frappe.logger("transport_management").info(
			"Created index route_date_status_idx on tabCab Request"
		)

	# ── 2. assigned_driver index (should already be present; skip if so) ───────
	if not _index_exists("tabCab Request", "assigned_driver_index"):
		frappe.db.add_index("Cab Request", ["assigned_driver"])
		frappe.logger("transport_management").info(
			"Created index assigned_driver_index on tabCab Request"
		)

	# ── 3. Composite index on Vehicle GPS Log (vehicle, recorded_at) ───────────
	if not _index_exists("tabVehicle GPS Log", "vehicle_recorded_at_idx"):
		frappe.db.sql(
			"""
			ALTER TABLE `tabVehicle GPS Log`
			ADD INDEX `vehicle_recorded_at_idx` (vehicle, recorded_at)
			"""
		)
		frappe.logger("transport_management").info(
			"Created index vehicle_recorded_at_idx on tabVehicle GPS Log"
		)
