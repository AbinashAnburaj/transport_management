# Copyright (c) 2026, our team and Contributors
# See license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase


def _delete_if_exists(name):
	if name and frappe.db.exists("Cab Route", name):
		frappe.delete_doc("Cab Route", name, force=1, ignore_permissions=True)


class TestCabRouteGeoJSON(FrappeTestCase):
	"""Verifies the `Cab Route.before_save` → generate_route_geojson hook."""

	def test_polyline_built_with_waypoints_in_sequence_order(self):
		route = frappe.get_doc({
			"doctype": "Cab Route",
			"route_name": f"QA-Geo-{frappe.generate_hash(length=6)}",
			"start_location": "S",
			"start_lat": 12.97,
			"start_lng": 77.59,
			"end_location": "E",
			"end_lat": 12.98,
			"end_lng": 77.60,
			"status": "Active",
			"waypoints": [
				# Insert deliberately out-of-order to prove the hook sorts by sequence.
				{"stop_name": "B", "latitude": 12.978, "longitude": 77.598, "sequence": 2},
				{"stop_name": "A", "latitude": 12.972, "longitude": 77.592, "sequence": 1},
			],
		}).insert(ignore_permissions=True)
		try:
			self.assertTrue(route.route_polyline, "before_save hook did not populate route_polyline")
			geo = json.loads(route.route_polyline)
			self.assertEqual(geo["geometry"]["type"], "LineString")
			coords = geo["geometry"]["coordinates"]
			# Order: start, A (seq 1), B (seq 2), end — 4 points; GeoJSON uses [lng, lat].
			self.assertEqual(len(coords), 4)
			self.assertEqual(coords[0], [77.59, 12.97])
			self.assertEqual(coords[1], [77.592, 12.972])
			self.assertEqual(coords[2], [77.598, 12.978])
			self.assertEqual(coords[-1], [77.60, 12.98])
			self.assertEqual(geo["properties"]["route_name"], route.route_name)
		finally:
			_delete_if_exists(route.name)

	def test_polyline_built_without_waypoints(self):
		route = frappe.get_doc({
			"doctype": "Cab Route",
			"route_name": f"QA-Geo-{frappe.generate_hash(length=6)}",
			"start_location": "S",
			"start_lat": 1.0,
			"start_lng": 2.0,
			"end_location": "E",
			"end_lat": 3.0,
			"end_lng": 4.0,
			"status": "Active",
		}).insert(ignore_permissions=True)
		try:
			coords = json.loads(route.route_polyline)["geometry"]["coordinates"]
			self.assertEqual(coords, [[2.0, 1.0], [4.0, 3.0]])
		finally:
			_delete_if_exists(route.name)
