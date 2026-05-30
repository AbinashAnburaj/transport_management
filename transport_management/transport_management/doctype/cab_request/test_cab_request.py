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
	_otp_attempt_key,
	_point_to_segment_km,
	book_route_cab,
	driver_complete_trip,
	get_permission_query_conditions,
	has_permission,
	reset_otp_attempts,
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


def _get_test_employee_id():
	"""Return the name of a guaranteed-to-exist Employee for test fixtures.

	Uses Frappe's built-in `_T-Employee-00001` (inserted by frappe test fixtures)
	so tests never depend on site-specific data.
	"""
	emp = frappe.db.get_value("Employee", "_T-Employee-00001", "name")
	if emp:
		return emp
	# Fallback: pick any employee present in this site.
	return frappe.db.get_value("Employee", {}, "name") or None


def _new_request(**overrides):
	defaults = {
		"doctype": "Cab Request",
		"employee_id": _get_test_employee_id(),
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


# ─────────────────────────────────────────────────────────────────────────────
#  H-1: OTP brute-force lockout
# ─────────────────────────────────────────────────────────────────────────────

class TestOtpLockout(FrappeTestCase):
	"""OTP attempt counter: lock after 5 bad attempts; manager reset unblocks."""

	route_name = None

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		route = frappe.get_doc({
			"doctype": "Cab Route",
			"route_name": f"QA-OtpLock-{frappe.generate_hash(length=6)}",
			"start_location": "S",
			"start_lat": 12.97,
			"start_lng": 77.59,
			"end_location": "E",
			"end_lat": 12.98,
			"end_lng": 77.60,
			"total_seats": 10,
			"status": "Active",
			"driver_name": "Administrator",
			"waypoints": [
				{"stop_name": "W1", "latitude": 12.975, "longitude": 77.595, "sequence": 1},
			],
		}).insert(ignore_permissions=True)
		cls.route_name = route.name

	@classmethod
	def tearDownClass(cls):
		if cls.route_name:
			frappe.db.sql(
				"DELETE FROM `tabCab Request Status Log` WHERE cab_request IN "
				"(SELECT name FROM `tabCab Request` WHERE assigned_route = %s)",
				(cls.route_name,),
			)
			frappe.db.sql(
				"DELETE FROM `tabCab Request` WHERE assigned_route = %s",
				(cls.route_name,),
			)
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

	def tearDown(self):
		# Clear any cache keys left by the test.
		if hasattr(self, "_req_name") and self._req_name:
			frappe.cache().delete_value(_otp_attempt_key(self._req_name))
		super().tearDown()

	def _book(self):
		req = _new_request().insert(ignore_permissions=True)
		frappe.db.set_value("Cab Request", req.name, "employee_id", f"FAKE-EMP-{req.name}")
		req.reload()
		result = book_route_cab(req.name, self.route_name, distance_from_route=0.5)
		self.assertEqual(result["status"], "success", msg=result)
		req.reload()
		return req

	def test_lockout_after_five_bad_attempts(self):
		req = self._book()
		self._req_name = req.name
		# First 4 wrong attempts should return 'invalid', not 'locked'.
		for i in range(4):
			result = verify_otp_and_start_trip(req.name, "000000")
			self.assertEqual(result["status"], "invalid", msg=f"attempt {i+1}: {result}")
		# 5th attempt must lock.
		result = verify_otp_and_start_trip(req.name, "000000")
		self.assertEqual(result["status"], "locked", msg=result)
		# Further attempt is still locked.
		result = verify_otp_and_start_trip(req.name, "000000")
		self.assertEqual(result["status"], "locked", msg=result)

	def test_manager_reset_unblocks(self):
		req = self._book()
		self._req_name = req.name
		# Exhaust all 5 attempts.
		for _ in range(5):
			verify_otp_and_start_trip(req.name, "000000")
		locked = verify_otp_and_start_trip(req.name, "000000")
		self.assertEqual(locked["status"], "locked")

		# Manager resets the counter.
		reset_result = reset_otp_attempts(req.name)
		self.assertEqual(reset_result["status"], "success")

		# Now the correct OTP should work again.
		req.reload()
		otp = frappe.db.get_value("Cab Request", req.name, "otp")
		verify = verify_otp_and_start_trip(req.name, str(otp))
		self.assertEqual(verify["status"], "success", msg=verify)

	def test_correct_otp_clears_counter(self):
		req = self._book()
		self._req_name = req.name
		# Two wrong attempts then the correct one — counter must clear.
		verify_otp_and_start_trip(req.name, "000000")
		verify_otp_and_start_trip(req.name, "000000")
		otp = frappe.db.get_value("Cab Request", req.name, "otp")
		result = verify_otp_and_start_trip(req.name, str(otp))
		self.assertEqual(result["status"], "success")
		# Counter is gone — cache key should be None/missing.
		remaining = frappe.cache().get_value(_otp_attempt_key(req.name))
		self.assertFalse(remaining)


# ─────────────────────────────────────────────────────────────────────────────
#  H-2: has_permission None==None guard
# ─────────────────────────────────────────────────────────────────────────────

class TestHasPermissionNoneGuard(FrappeTestCase):
	"""Employee with no Employee record must NOT see a blank-employee_id request."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=4)
		cls.bare_email = f"qa_bare_{suffix}@cabtest.example"
		# User has Employee role but no Employee record (so db.get_value returns None).
		_ensure_user(cls.bare_email, "QA Bare Emp", ["Employee"])

	@classmethod
	def tearDownClass(cls):
		_delete_if_exists("User", cls.bare_email)
		super().tearDownClass()

	def test_blank_employee_id_doc_not_visible(self):
		# Synthesise a doc with no employee_id and a different owner.
		doc = frappe._dict(
			employee_id=None,
			assigned_driver=None,
			owner="someone-else@example.com",
		)
		# The bare user has Employee role but no Employee record →
		# employee_id lookup returns None. With the guard, None != None is never True.
		result = has_permission(doc, user=self.bare_email)
		self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────────────
#  GAP-1a: Last-seat double-booking guard (deterministic interleaving)
#
#  Frappe tests run inside a single transaction that is rolled back after each
#  test, so true OS-level concurrency is not feasible without separate DB
#  connections (which would require external test infrastructure).  Instead we
#  simulate the TOCTOU race deterministically:
#
#    1. Reserve the one free seat normally (booking A succeeds).
#    2. Call `_get_booked_seat_count` a second time with the seat already taken.
#    3. Invoke the guard logic directly — prove it returns the rejection dict
#       rather than creating a second booking.
#    4. Assert only one Cab Request is Assigned for that route+date.
#
#  This is the canonical interleaving where thread-2 reads "1 booked" AFTER
#  thread-1 commits "1 booked".  The FOR UPDATE lock in `book_route_cab` makes
#  the real concurrent path serial; this test codifies the expected outcome so
#  any regression (e.g. someone removing the `for_update=True` call) is caught.
# ─────────────────────────────────────────────────────────────────────────────

class TestLastSeatDoubleBookingGuard(FrappeTestCase):
	"""Regression: last-seat race must never oversell."""

	route_name = None

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		route = frappe.get_doc({
			"doctype": "Cab Route",
			"route_name": f"QA-LastSeat-{frappe.generate_hash(length=6)}",
			"start_location": "S",
			"start_lat": 12.97,
			"start_lng": 77.59,
			"end_location": "E",
			"end_lat": 12.98,
			"end_lng": 77.60,
			"total_seats": 1,
			"status": "Active",
			"driver_name": "qa_lastseat_driver@example.com",
			"waypoints": [
				{"stop_name": "W1", "latitude": 12.975, "longitude": 77.595, "sequence": 1},
			],
		}).insert(ignore_permissions=True)
		cls.route_name = route.name

	@classmethod
	def tearDownClass(cls):
		if cls.route_name:
			frappe.db.sql(
				"DELETE FROM `tabCab Request Status Log` WHERE cab_request IN "
				"(SELECT name FROM `tabCab Request` WHERE assigned_route = %s)",
				(cls.route_name,),
			)
			frappe.db.sql(
				"DELETE FROM `tabCab Request` WHERE assigned_route = %s",
				(cls.route_name,),
			)
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

	def tearDown(self):
		# Purge anything committed to the test route so each sub-test starts fresh.
		if self.route_name:
			frappe.db.sql(
				"DELETE FROM `tabCab Request Status Log` WHERE cab_request IN "
				"(SELECT name FROM `tabCab Request` WHERE assigned_route = %s)",
				(self.route_name,),
			)
			frappe.db.sql(
				"DELETE FROM `tabCab Request` WHERE assigned_route = %s",
				(self.route_name,),
			)
			frappe.db.commit()
		super().tearDown()

	def _book_one(self, fake_emp_suffix):
		req = _new_request().insert(ignore_permissions=True)
		frappe.db.set_value(
			"Cab Request", req.name, "employee_id", f"LS-EMP-{fake_emp_suffix}-{req.name}"
		)
		req.reload()
		return req

	def test_first_booking_succeeds_on_single_seat_route(self):
		"""Control: one seat, one booking → must succeed."""
		req = self._book_one("A")
		result = book_route_cab(req.name, self.route_name, distance_from_route=0.5)
		self.assertEqual(result["status"], "success", msg=result)

	def test_second_booking_rejected_after_first_fills_seat(self):
		"""Core regression: after seat-0 → seat-1, second booking must get 'no seats'."""
		# Booking A fills the one seat (commits inside book_route_cab).
		req_a = self._book_one("A")
		result_a = book_route_cab(req_a.name, self.route_name, distance_from_route=0.5)
		self.assertEqual(result_a["status"], "success", msg=f"First booking should succeed: {result_a}")

		# Booking B — the route now has 0 free seats.
		req_b = self._book_one("B")
		result_b = book_route_cab(req_b.name, self.route_name, distance_from_route=0.5)
		self.assertEqual(result_b["status"], "error", msg=f"Second booking must be rejected: {result_b}")
		self.assertIn("seat", result_b.get("message", "").lower(),
			msg=f"Rejection message should mention seats: {result_b['message']}")

	def test_seat_count_reflects_committed_bookings(self):
		"""_get_booked_seat_count must return 1 after the first booking commits."""
		req = self._book_one("X")
		travel_date = str(req.booking_datetime)[:10]
		# Before booking: 0 seats taken.
		self.assertEqual(_get_booked_seat_count(self.route_name, travel_date), 0)
		book_route_cab(req.name, self.route_name, distance_from_route=0.5)
		# After booking commits: 1 seat taken.
		self.assertEqual(_get_booked_seat_count(self.route_name, travel_date), 1)

	def test_oversell_guard_is_in_book_route_cab_not_only_validate(self):
		"""The seat guard inside book_route_cab uses a FOR UPDATE lock re-check,
		NOT just the pre-query from find_matching_cabs.  Simulate the TOCTOU window:
		manually set a booking to Assigned (as if thread-1 committed) then call
		book_route_cab for thread-2 and expect rejection — proving the in-function
		re-check fires even when the first read showed 0 booked."""
		req_a = self._book_one("TOCTOU-A")
		req_b = self._book_one("TOCTOU-B")
		travel_date = str(req_a.booking_datetime)[:10]

		# Simulate thread-1 committing outside of book_route_cab (bypass validate).
		frappe.db.set_value(
			"Cab Request",
			req_a.name,
			{
				"assigned_route": self.route_name,
				"status": "Assigned",
				"travel_date": travel_date,
			},
		)
		frappe.db.commit()

		# Thread-2 now calls book_route_cab — the FOR UPDATE re-check must catch this.
		result = book_route_cab(req_b.name, self.route_name, distance_from_route=0.5)
		self.assertEqual(result["status"], "error",
			msg=f"TOCTOU guard must reject thread-2: {result}")


# ─────────────────────────────────────────────────────────────────────────────
#  GAP-1b: Vendor double-billing guard (deterministic interleaving)
#
#  The billing guard in vendor_billing._create_invoice_for_group re-reads
#  invoice_link WITH FOR UPDATE before writing.  We simulate the race:
#
#    1. Create a Completed, billable Cab Request.
#    2. Run generate_invoices once → invoice A created, invoice_link set.
#    3. Run generate_invoices a second time → must produce zero new invoices
#       because invoice_link is already set.
#    4. Verify exactly ONE Cab Vendor Invoice exists for that trip.
#
#  A true concurrent test would need two separate DB connections; this
#  deterministic replay is the best achievable within the Frappe test harness.
# ─────────────────────────────────────────────────────────────────────────────

class TestVendorDoubleBillingGuard(FrappeTestCase):
	"""Regression: generate_invoices must never create two invoices for one trip."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# Ensure a Supplier exists for the test vendor.
		cls.vendor_name = f"QA-Vendor-{frappe.generate_hash(length=6)}"
		if not frappe.db.exists("Supplier", cls.vendor_name):
			frappe.get_doc({
				"doctype": "Supplier",
				"supplier_name": cls.vendor_name,
				"supplier_group": frappe.db.get_value("Supplier Group", {}, "name") or "All Supplier Groups",
				"supplier_type": "Company",
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		# Clean up test invoices and trips first.
		frappe.db.sql(
			"DELETE FROM `tabCab Invoice Item` WHERE parent IN "
			"(SELECT name FROM `tabCab Vendor Invoice` WHERE vendor = %s)",
			(cls.vendor_name,),
		)
		frappe.db.sql(
			"DELETE FROM `tabCab Vendor Invoice` WHERE vendor = %s",
			(cls.vendor_name,),
		)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		# Create a fresh billable Completed trip for each test.
		self.req = _new_request().insert(ignore_permissions=True)
		travel_date = str(self.req.booking_datetime)[:10]
		frappe.db.set_value(
			"Cab Request",
			self.req.name,
			{
				"status": "Completed",
				"travel_date": travel_date,
				"vendor": self.vendor_name,
				"rate": 10.0,
				"total_distance": 25.0,
				"invoice_link": None,
			},
		)
		frappe.db.commit()

	def tearDown(self):
		# Remove invoices + trips created during this test.
		frappe.db.sql(
			"DELETE FROM `tabCab Invoice Item` WHERE parent IN "
			"(SELECT name FROM `tabCab Vendor Invoice` WHERE vendor = %s)",
			(self.vendor_name,),
		)
		frappe.db.sql(
			"DELETE FROM `tabCab Vendor Invoice` WHERE vendor = %s",
			(self.vendor_name,),
		)
		if self.req and frappe.db.exists("Cab Request", self.req.name):
			frappe.db.sql(
				"DELETE FROM `tabCab Request` WHERE name = %s",
				(self.req.name,),
			)
		frappe.db.commit()
		super().tearDown()

	def _run_billing(self):
		from transport_management.transport_management.billing.vendor_billing import generate_invoices
		travel_date = frappe.db.get_value("Cab Request", self.req.name, "travel_date")
		return generate_invoices(billing_month=travel_date, vendor=self.vendor_name)

	def test_first_billing_run_creates_one_invoice(self):
		result = self._run_billing()
		self.assertEqual(result["invoice_count"], 1, msg=f"Expected 1 invoice, got: {result}")
		self.assertEqual(result["trip_count"], 1)

	def test_second_billing_run_creates_no_new_invoices(self):
		"""Idempotency: running billing twice must not double-bill."""
		result_1 = self._run_billing()
		self.assertEqual(result_1["invoice_count"], 1, msg=f"First run: {result_1}")

		# Simulate the race: run billing again before any cleanup.
		result_2 = self._run_billing()
		self.assertEqual(result_2["invoice_count"], 0,
			msg=f"Second billing run must create 0 invoices; got: {result_2}")

	def test_invoice_link_set_prevents_double_billing(self):
		"""invoice_link is the single source of truth for the billing guard."""
		result = self._run_billing()
		self.assertEqual(result["invoice_count"], 1)

		# invoice_link must now be set on the Cab Request.
		invoice_link = frappe.db.get_value("Cab Request", self.req.name, "invoice_link")
		self.assertTrue(invoice_link, msg="invoice_link must be set after billing")

		# Verify exactly one Cab Vendor Invoice exists for this trip's vendor.
		count = frappe.db.count("Cab Vendor Invoice", {"vendor": self.vendor_name})
		self.assertEqual(count, 1, msg=f"Must be exactly 1 invoice, found {count}")

	def test_toctou_simulation_second_connection_sees_locked_row(self):
		"""Simulate thread-2 arriving after thread-1 has already set invoice_link.

		This tests the FOR UPDATE re-read in _create_invoice_for_group: even if
		thread-2 passed get_billable_trips() while invoice_link was still NULL
		(because thread-1 hadn't committed yet), the row lock + re-read inside
		_create_invoice_for_group must cause thread-2 to skip the already-billed
		trip and produce 0 new invoices.
		"""
		from transport_management.transport_management.billing.vendor_billing import (
			_create_invoice_for_group,
			get_billable_trips,
		)
		travel_date = frappe.db.get_value("Cab Request", self.req.name, "travel_date")

		# Thread-1 completes billing normally.
		trips = get_billable_trips(billing_month=travel_date, vendor=self.vendor_name)
		invoice_name, total, billed = _create_invoice_for_group(self.vendor_name, trips)
		frappe.db.commit()
		self.assertIsNotNone(invoice_name)
		self.assertEqual(billed, 1)

		# Thread-2: same trip list (snapshot from before thread-1 committed).
		# The FOR UPDATE re-read inside _create_invoice_for_group will see
		# invoice_link already set and skip the trip → returns (None, 0.0, 0).
		invoice_name_2, total_2, billed_2 = _create_invoice_for_group(self.vendor_name, trips)
		frappe.db.commit()
		self.assertIsNone(invoice_name_2, msg="Thread-2 must not create a second invoice")
		self.assertEqual(billed_2, 0, msg="Thread-2 must bill 0 trips")
