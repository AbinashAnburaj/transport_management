# Copyright (c) 2026, our team and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from transport_management.transport_management.cab_status import is_valid_transition
from transport_management.transport_management.doctype.cab_request.cab_request import (
	_distance_from_route,
	_get_booked_seat_count,
	_get_driver_identity_candidates,
	_haversine_km,
	_point_to_segment_km,
	book_route_cab,
	driver_complete_trip,
	get_permission_query_conditions,
	has_permission,
	verify_otp_and_start_trip,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_user(email, full_name, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": full_name,
			"send_welcome_email": 0,
			"enabled": 1,
		}).insert(ignore_permissions=True)
	existing = {r.role for r in user.roles}
	dirty = False
	for role in roles:
		if role not in existing:
			user.append("roles", {"role": role})
			dirty = True
	if dirty:
		user.save(ignore_permissions=True)
	return user


def _new_request(**overrides):
	defaults = {
		"doctype": "Cab Request",
		"employee_name": "QA Test",
		"pickup_location": "Office A",
		"drop_location": "Office B",
		"booking_datetime": add_to_date(now_datetime(), hours=3),
		"status": "Pending",
	}
	defaults.update(overrides)
	return frappe.get_doc(defaults)


def _delete_if_exists(doctype, name):
	if name and frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)


# ─────────────────────────────────────────────────────────────────────────────
#  State machine (pure)
# ─────────────────────────────────────────────────────────────────────────────

class TestCabRequestStateMachine(FrappeTestCase):
	"""Pure-function checks on cab_status.is_valid_transition."""

	def test_no_op_transition_is_allowed(self):
		for s in ("Pending", "Assigned", "In Trip", "Completed", "Cancelled"):
			self.assertTrue(is_valid_transition(s, s))

	def test_canonical_lifecycle(self):
		self.assertTrue(is_valid_transition("Pending", "Assigned"))
		self.assertTrue(is_valid_transition("Assigned", "In Trip"))
		self.assertTrue(is_valid_transition("In Trip", "Completed"))

	def test_cancellation_only_before_in_trip(self):
		self.assertTrue(is_valid_transition("Pending", "Cancelled"))
		self.assertTrue(is_valid_transition("Assigned", "Cancelled"))
		self.assertFalse(is_valid_transition("In Trip", "Cancelled"))

	def test_terminal_states_block_all_transitions(self):
		for terminal in ("Completed", "Cancelled"):
			for target in ("Pending", "Assigned", "In Trip"):
				self.assertFalse(is_valid_transition(terminal, target))

	def test_backwards_transitions_disallowed(self):
		self.assertFalse(is_valid_transition("Assigned", "Pending"))
		self.assertFalse(is_valid_transition("In Trip", "Assigned"))
		self.assertFalse(is_valid_transition("Completed", "In Trip"))

	def test_unknown_from_status_does_not_block(self):
		# Legacy/stray status values must not hard-block the state machine.
		self.assertTrue(is_valid_transition("LegacyValue", "Pending"))


# ─────────────────────────────────────────────────────────────────────────────
#  Geometry helpers (pure)
# ─────────────────────────────────────────────────────────────────────────────

class TestCabRequestGeoHelpers(FrappeTestCase):
	def test_haversine_zero_distance(self):
		self.assertAlmostEqual(_haversine_km(12.97, 77.59, 12.97, 77.59), 0.0, places=4)

	def test_haversine_chennai_bangalore(self):
		# Great-circle Chennai (13.0827, 80.2707) ↔ Bangalore (12.9716, 77.5946) ≈ 290 km
		d = _haversine_km(13.0827, 80.2707, 12.9716, 77.5946)
		self.assertGreater(d, 280)
		self.assertLess(d, 300)

	def test_point_on_segment_returns_zero(self):
		# Point at midpoint of the segment along the equator (0,0) → (0,1).
		d = _point_to_segment_km(0.0, 0.5, 0.0, 0.0, 0.0, 1.0)
		self.assertAlmostEqual(d, 0.0, places=4)

	def test_collapsed_segment_falls_back_to_haversine(self):
		d = _point_to_segment_km(0.0, 0.0, 1.0, 1.0, 1.0, 1.0)
		self.assertAlmostEqual(d, _haversine_km(0.0, 0.0, 1.0, 1.0), places=4)

	def test_distance_uses_segment_not_just_waypoint(self):
		# Test point lies near the SEGMENT midpoint but far from either endpoint.
		# Segment-distance must be smaller than haversine to the closer waypoint.
		wps = [
			{"latitude": 0.0, "longitude": 0.0, "sequence": 1},
			{"latitude": 0.0, "longitude": 1.0, "sequence": 2},
		]
		d_seg = _distance_from_route(0.001, 0.5, wps)
		d_to_endpoint = _haversine_km(0.001, 0.5, 0.0, 0.0)
		self.assertLess(d_seg, d_to_endpoint)
		self.assertLess(d_seg, 1.0)

	def test_distance_from_route_sorts_by_sequence(self):
		wps = [
			{"latitude": 0.0, "longitude": 1.0, "sequence": 2},
			{"latitude": 0.0, "longitude": 0.0, "sequence": 1},
		]
		d = _distance_from_route(0.0, 0.5, wps)
		self.assertAlmostEqual(d, 0.0, places=2)


# ─────────────────────────────────────────────────────────────────────────────
#  validate() — date / odometer / business rules
# ─────────────────────────────────────────────────────────────────────────────

class TestCabRequestValidations(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	def test_past_booking_rejected(self):
		doc = _new_request(booking_datetime=add_to_date(now_datetime(), hours=-2))
		with self.assertRaises(frappe.exceptions.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_booking_under_one_hour_rejected(self):
		doc = _new_request(booking_datetime=add_to_date(now_datetime(), minutes=30))
		with self.assertRaises(frappe.exceptions.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_valid_future_booking_inserts(self):
		doc = _new_request().insert(ignore_permissions=True)
		self.assertEqual(doc.status, "Pending")

	def test_odometer_reverse_rejected(self):
		doc = _new_request().insert(ignore_permissions=True)
		doc.start_odometer = 1000
		doc.end_odometer = 500
		with self.assertRaises(frappe.exceptions.ValidationError):
			doc.save(ignore_permissions=True)

	def test_total_distance_computed_from_odometers(self):
		doc = _new_request().insert(ignore_permissions=True)
		doc.start_odometer = 1000
		doc.end_odometer = 1250
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.total_distance, 250)

	def test_total_distance_not_set_when_readings_missing(self):
		doc = _new_request().insert(ignore_permissions=True)
		self.assertFalse(doc.total_distance)


# ─────────────────────────────────────────────────────────────────────────────
#  Seat-counting helper
# ─────────────────────────────────────────────────────────────────────────────

class TestSeatCount(FrappeTestCase):
	def test_no_travel_date_returns_zero(self):
		self.assertEqual(_get_booked_seat_count("ANY-ROUTE", None), 0)

	def test_counts_only_assigned_in_trip_completed(self):
		route_name = f"TEST-SEAT-{frappe.generate_hash(length=6)}"
		td = frappe.utils.today()
		for status in ("Assigned", "In Trip", "Completed", "Pending", "Cancelled"):
			d = _new_request(travel_date=td).insert(ignore_permissions=True)
			# db.set_value bypasses validate() — pin both route and status directly.
			frappe.db.set_value(
				"Cab Request",
				d.name,
				{"assigned_route": route_name, "status": status},
			)
		# Assigned + In Trip + Completed → 3; Pending + Cancelled excluded.
		self.assertEqual(_get_booked_seat_count(route_name, td), 3)

	def test_fallback_to_booking_datetime_when_travel_date_blank(self):
		route_name = f"TEST-SEAT-FB-{frappe.generate_hash(length=6)}"
		td = frappe.utils.today()
		booking = add_to_date(now_datetime(), hours=3)
		doc = _new_request(booking_datetime=booking).insert(ignore_permissions=True)
		# Pin Assigned + clear travel_date so only the booking_datetime fallback can match.
		frappe.db.set_value(
			"Cab Request",
			doc.name,
			{"assigned_route": route_name, "status": "Assigned", "travel_date": None},
		)
		# `today` matches DATE(booking_datetime) since booking_datetime = now + 3h.
		self.assertEqual(_get_booked_seat_count(route_name, td), 1)


# ─────────────────────────────────────────────────────────────────────────────
#  Driver identity resolution
# ─────────────────────────────────────────────────────────────────────────────

class TestDriverIdentityCandidates(FrappeTestCase):
	def test_user_email_always_included(self):
		candidates = _get_driver_identity_candidates("nonexistent-user@example.invalid")
		self.assertIn("nonexistent-user@example.invalid", candidates)

	def test_no_blank_candidates(self):
		candidates = _get_driver_identity_candidates("nonexistent-user@example.invalid")
		self.assertNotIn("", candidates)
		self.assertNotIn(None, candidates)


# ─────────────────────────────────────────────────────────────────────────────
#  Row-level permission query
# ─────────────────────────────────────────────────────────────────────────────

class TestPermissionQueryConditions(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		suffix = frappe.generate_hash(length=4)
		cls.mgr_email = f"qa_mgr_{suffix}@cabtest.example"
		cls.drv_email = f"qa_drv_{suffix}@cabtest.example"
		cls.norole_email = f"qa_norole_{suffix}@cabtest.example"
		_ensure_user(cls.mgr_email, "QA Manager", ["Fleet Manager"])
		_ensure_user(cls.drv_email, "QA Driver", ["Driver"])
		_ensure_user(cls.norole_email, "QA NoRole", [])

	@classmethod
	def tearDownClass(cls):
		for email in (cls.mgr_email, cls.drv_email, cls.norole_email):
			_delete_if_exists("User", email)
		super().tearDownClass()

	def test_manager_gets_unfiltered_access(self):
		self.assertEqual(get_permission_query_conditions(self.mgr_email), "")

	def test_no_domain_role_denies_everything(self):
		self.assertEqual(get_permission_query_conditions(self.norole_email), "1=0")

	def test_driver_filter_includes_user_email(self):
		cond = get_permission_query_conditions(self.drv_email)
		self.assertIn("assigned_driver IN", cond)
		self.assertIn(self.drv_email, cond)


# ─────────────────────────────────────────────────────────────────────────────
#  Doc-level has_permission
# ─────────────────────────────────────────────────────────────────────────────

class TestHasPermission(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		suffix = frappe.generate_hash(length=4)
		cls.mgr_email = f"qa_perm_mgr_{suffix}@cabtest.example"
		cls.drv_email = f"qa_perm_drv_{suffix}@cabtest.example"
		_ensure_user(cls.mgr_email, "QA Perm Mgr", ["Fleet Manager"])
		_ensure_user(cls.drv_email, "QA Perm Drv", ["Driver"])

	@classmethod
	def tearDownClass(cls):
		for email in (cls.mgr_email, cls.drv_email):
			_delete_if_exists("User", email)
		super().tearDownClass()

	def test_manager_sees_all(self):
		doc = frappe._dict(
			assigned_driver="someone-else",
			employee_id="X",
			owner="other@example.com",
		)
		self.assertTrue(has_permission(doc, user=self.mgr_email))

	def test_driver_sees_assigned_doc(self):
		doc = frappe._dict(
			assigned_driver=self.drv_email,
			employee_id="",
			owner="other@example.com",
		)
		self.assertTrue(has_permission(doc, user=self.drv_email))

	def test_driver_blocked_from_others_doc(self):
		doc = frappe._dict(
			assigned_driver="someone-else@example.com",
			employee_id="",
			owner="other@example.com",
		)
		self.assertFalse(has_permission(doc, user=self.drv_email))


# ─────────────────────────────────────────────────────────────────────────────
#  End-to-end booking lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class TestBookingLifecycle(FrappeTestCase):
	"""Full happy path through book_route_cab → verify_otp → driver_complete_trip."""

	route_name = None

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# Minimal Cab Route — Vehicle and Driver Link fields are optional so we leave them blank.
		route = frappe.get_doc({
			"doctype": "Cab Route",
			"route_name": f"QA-Lifecycle-{frappe.generate_hash(length=6)}",
			"start_location": "Start",
			"start_lat": 12.97,
			"start_lng": 77.59,
			"end_location": "End",
			"end_lat": 12.98,
			"end_lng": 77.60,
			"total_seats": 4,
			"status": "Active",
			"driver_name": "qa_lifecycle_driver@example.com",
			"waypoints": [
				{"stop_name": "WP1", "latitude": 12.975, "longitude": 77.595, "sequence": 1},
			],
		}).insert(ignore_permissions=True)
		cls.route_name = route.name

	@classmethod
	def tearDownClass(cls):
		# Bulletproof cleanup: raw SQL in strict FK-safe order so a single ORM
		# hiccup never leaves the QA route stranded in the dashboard.
		try:
			cls._purge_leaked_requests()
		finally:
			if cls.route_name:
				frappe.db.sql(
					"DELETE FROM `tabRoute Waypoint` WHERE parent = %s",
					(cls.route_name,),
				)
				frappe.db.sql(
					"DELETE FROM `tabCab Route` WHERE name = %s",
					(cls.route_name,),
				)
				frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def _purge_leaked_requests(cls):
		# book_route_cab commits, so requests escape the per-test savepoint rollback.
		# Wipe anything pinned to our test route and their status-log rows.
		if not cls.route_name:
			return
		frappe.db.sql(
			"""
			DELETE l FROM `tabCab Request Status Log` l
			INNER JOIN `tabCab Request` r ON l.cab_request = r.name
			WHERE r.assigned_route = %s
			""",
			(cls.route_name,),
		)
		frappe.db.sql(
			"DELETE FROM `tabCab Request` WHERE assigned_route = %s",
			(cls.route_name,),
		)
		frappe.db.commit()

	def tearDown(self):
		# Keep test-to-test isolation despite the internal db.commit in book_route_cab.
		self._purge_leaked_requests()
		frappe.db.commit()
		super().tearDown()

	def _book(self, distance=0.2):
		req = _new_request().insert(ignore_permissions=True)
		# Pin a unique fake employee_id so the "active booking" guard inside
		# book_route_cab doesn't false-match leaked requests from sibling tests.
		frappe.db.set_value(
			"Cab Request", req.name, "employee_id", f"FAKE-EMP-{req.name}"
		)
		req.reload()
		result = book_route_cab(req.name, self.route_name, distance_from_route=distance)
		self.assertEqual(result["status"], "success", msg=result)
		return req, result

	def test_happy_path_to_completion(self):
		req, result = self._book()
		otp = result["otp"]

		req.reload()
		self.assertEqual(req.status, "Assigned")
		self.assertEqual(req.assigned_route, self.route_name)
		self.assertEqual(int(req.otp), int(otp))
		self.assertEqual(str(req.travel_date), str(req.booking_datetime)[:10])

		verify = verify_otp_and_start_trip(req.name, otp)
		self.assertEqual(verify["status"], "success")
		req.reload()
		self.assertEqual(req.status, "In Trip")
		self.assertEqual(req.otp or 0, 0)

		self.assertEqual(driver_complete_trip(req.name), "success")
		req.reload()
		self.assertEqual(req.status, "Completed")

		logs = frappe.get_all(
			"Cab Request Status Log",
			filters={"cab_request": req.name},
			fields=["from_status", "to_status"],
		)
		transitions = {(row.from_status, row.to_status) for row in logs}
		self.assertIn(("Pending", "Assigned"), transitions)
		self.assertIn(("Assigned", "In Trip"), transitions)
		self.assertIn(("In Trip", "Completed"), transitions)

	def test_wrong_otp_keeps_status_assigned(self):
		req, _ = self._book()
		result = verify_otp_and_start_trip(req.name, "000000")
		self.assertEqual(result["status"], "invalid")
		req.reload()
		self.assertEqual(req.status, "Assigned")

	def test_second_verify_after_start_returns_error(self):
		req, booking = self._book()
		verify_otp_and_start_trip(req.name, booking["otp"])
		# Status is now In Trip and OTP cleared — second attempt rejected on status check.
		again = verify_otp_and_start_trip(req.name, booking["otp"])
		self.assertEqual(again["status"], "error")


# ─────────────────────────────────────────────────────────────────────────────
#  Live driver location API (api/gps.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetMyDriverLocation(FrappeTestCase):
	"""Permission gates and routing for the employee-scoped GPS read API."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=4)
		cls.outsider_email = f"qa_outsider_{suffix}@cabtest.example"
		_ensure_user(cls.outsider_email, "QA Outsider", ["Employee"])

	@classmethod
	def tearDownClass(cls):
		_delete_if_exists("User", cls.outsider_email)
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		self.req = _new_request().insert(ignore_permissions=True)

	def _call(self, user=None):
		from transport_management.transport_management.api.gps import get_my_driver_location
		if user:
			previous = frappe.session.user
			frappe.set_user(user)
			try:
				return get_my_driver_location(self.req.name)
			finally:
				frappe.set_user(previous)
		return get_my_driver_location(self.req.name)

	def test_unrelated_employee_blocked(self):
		with self.assertRaises(frappe.exceptions.PermissionError):
			self._call(user=self.outsider_email)

	def test_pending_request_returns_not_active(self):
		# Default insert leaves status=Pending
		result = self._call()
		self.assertFalse(result["available"])
		self.assertEqual(result["reason"], "not_active")

	def test_assigned_but_no_vehicle_returns_no_vehicle(self):
		frappe.db.set_value(
			"Cab Request",
			self.req.name,
			{"status": "Assigned", "assigned_cab": None},
		)
		result = self._call()
		self.assertFalse(result["available"])
		self.assertEqual(result["reason"], "no_vehicle")

	def test_assigned_with_vehicle_but_no_logs_returns_no_pings(self):
		fake_vehicle = f"QA-VEH-{frappe.generate_hash(length=6)}"
		frappe.db.set_value(
			"Cab Request",
			self.req.name,
			{"status": "Assigned", "assigned_cab": fake_vehicle},
		)
		result = self._call()
		self.assertFalse(result["available"])
		self.assertEqual(result["reason"], "no_pings_yet")
		self.assertEqual(result["vehicle"], fake_vehicle)


# ─────────────────────────────────────────────────────────────────────────────
#  can_i_post_for_request — server-side identity resolver for the JS pinger
# ─────────────────────────────────────────────────────────────────────────────

class TestCanIPostForRequest(FrappeTestCase):
	"""Drives the gate that decides whether the JS pinger starts."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	def setUp(self):
		super().setUp()
		self.req = _new_request().insert(ignore_permissions=True)

	def _call(self):
		from transport_management.transport_management.api.gps import can_i_post_for_request
		return can_i_post_for_request(self.req.name)

	def test_unknown_request_returns_not_found(self):
		from transport_management.transport_management.api.gps import can_i_post_for_request
		self.assertEqual(
			can_i_post_for_request("NONEXISTENT-XYZ"),
			{"can_post": False, "reason": "not_found"},
		)

	def test_pending_request_returns_not_active(self):
		result = self._call()
		self.assertFalse(result["can_post"])
		self.assertEqual(result["reason"], "not_active")

	def test_assigned_without_vehicle_returns_no_vehicle(self):
		frappe.db.set_value(
			"Cab Request", self.req.name,
			{"status": "Assigned", "assigned_cab": None},
		)
		result = self._call()
		self.assertEqual(result, {"can_post": False, "reason": "no_vehicle"})

	def test_caller_not_in_driver_candidates_returns_not_assigned(self):
		# Pin to a driver string the current user (Administrator) cannot resolve to.
		frappe.db.set_value(
			"Cab Request", self.req.name,
			{
				"status": "Assigned",
				"assigned_cab": "TEST-VEH-XX",
				"assigned_driver": "someone-completely-unrelated@example.invalid",
			},
		)
		result = self._call()
		self.assertEqual(result, {"can_post": False, "reason": "not_assigned"})

	def test_caller_matches_via_user_email_candidate(self):
		# The minimum candidate always includes session.user — assign by email.
		current_user = frappe.session.user
		frappe.db.set_value(
			"Cab Request", self.req.name,
			{
				"status": "Assigned",
				"assigned_cab": "TEST-VEH-EMAIL",
				"assigned_driver": current_user,
			},
		)
		result = self._call()
		self.assertEqual(result, {"can_post": True, "vehicle": "TEST-VEH-EMAIL"})
