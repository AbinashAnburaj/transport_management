# Transport Management — Enterprise QA Report

**App:** `transport_management` · **Site:** `cabtest.local` · **Framework:** Frappe v15 / ERPNext v15
**Date:** 2026-05-22 · **Prepared by:** QA Architect (live regression sweep + code review)

---

## 1. Executive summary

A live regression sweep was executed against `cabtest.local` covering the booking/OTP
lifecycle, billing, RBAC, GPS, schedulers and data integrity. **10 defects** were found —
**1 Critical, 1 High, 4 Medium, 4 Low**.

### Go-live verdict: 🟡 CONDITIONALLY READY *(post-remediation)*

**9 of 10 defects are FIXED and verified live.** No code blocker remains. DEF-09 is
deliberately deferred (rationale below). The system is clear for go-live once the
operational items in §8 (scheduler, SMTP, demo-data replacement, commit) are closed
and UAT (§7) is signed off.

| Severity | Count | IDs | Status |
|---|---|---|---|
| Critical | 1 | DEF-01 | ✅ Fixed & verified |
| High | 1 | DEF-02 | ✅ Fixed & verified |
| Medium | 4 | DEF-03, DEF-04, DEF-05, DEF-06 | ✅ Fixed & verified |
| Low | 4 | DEF-07, DEF-08, DEF-10 · DEF-09 | ◐ 3 fixed · 1 deferred |

**DEF-09 (Low) — deferred, with rationale:** flipping `is_submittable` on a live doctype
that already has submitted documents (docstatus 1) is exactly the risky architectural
change this engagement prohibits without a planned migration. It is cosmetic (Low) and
belongs in a scheduled data-migration window, not a QA hotfix. Tracked, not fixed.

---

## 2. Defects

### DEF-01 — Cab Request data leakage via permission query 🔴 CRITICAL
- **Module:** RBAC / Cab Request
- **Problem:** `get_permission_query_conditions` returns `""` (Frappe treats an empty
  string as *no restriction = full access*) for any authenticated user who is **not**
  Driver / Employee / Fleet Manager / System Manager.
- **Root cause:** the function appends row conditions only for those four roles; if none
  match, control falls through to a final `return ""`.
- **Reproduction:** *(confirmed live with user `mohankumar@gmail.com`)*
  1. Log in as a user holding no transport role.
  2. Open the Cab Request list view or any Cab Request report.
  3. Every employee's bookings are visible.
- **Expected:** such a user sees nothing (or only documents they own).
- **Actual:** sees all bookings — pickup locations, contact numbers, employee names.
- **Suggested fix:** when no role-based condition was produced and the user is not a
  manager, `return "1=0"` instead of `return ""`.
- **Risk impact:** organisation-wide PII leakage; privacy / compliance exposure.

### DEF-02 — Historical Cab Requests are uneditable 🟠 HIGH
- **Module:** Cab Request
- **Problem:** Saving any existing older Cab Request fails.
- **Root cause:** `shift_type` / `shift_time` are mandatory but legacy rows are blank;
  additionally `validate_dates` rejects any `booking_datetime` in the past on every save.
- **Reproduction:** open `CAB-BOOK-007`, click Save → *"Missing mandatory fields:
  shift_type, shift_time"*.
- **Expected:** managers can correct/edit historical records.
- **Actual:** all edits of legacy records are blocked; the Phase-4 manual-edit audit
  (`on_update`) can therefore never fire on legacy data.
- **Suggested fix:** (a) backfill `shift_type`/`shift_time` on legacy rows via a patch (or
  relax `reqd`); (b) scope `validate_dates` to `is_new()` or to `status == "Pending"` so
  in-progress/closed trips stay editable.
- **Risk impact:** data correction impossible; audit trail incomplete for old trips.

### DEF-03 — Invalid status value `"Success"` in production data 🟡 MEDIUM
- **Module:** Cab Request / data integrity
- **Problem:** 1 row has `status = "Success"` — not in the `status` Select options nor in
  the `cab_status` state machine.
- **Root cause:** legacy/pre-state-machine write.
- **Suggested fix:** data patch to normalise (`Success` → `Completed`); add a `validate`
  guard rejecting unknown status values.
- **Risk impact:** phantom bucket in reports/charts/number cards; the state machine is
  *lenient* on unknown source states, so odd transitions are possible from this row.

### DEF-04 — GPS endpoint lacks vehicle-ownership check 🟡 MEDIUM
- **Module:** GPS API (`api/gps.update_vehicle_location`)
- **Problem:** the endpoint accepts any `vehicle` argument; a Driver can post coordinates
  for **any** vehicle, not only the one assigned to them.
- **Root cause:** authorisation checks role membership only, not vehicle ownership.
- **Suggested fix:** verify the posting Driver is the assigned driver of that vehicle /
  active route before accepting the ping.
- **Risk impact:** GPS spoofing / poisoning of the live tracking map.

### DEF-05 — Seat-booking race condition (TOCTOU) 🟡 MEDIUM
- **Module:** Booking (`book_route_cab`)
- **Problem:** `_get_booked_seat_count` is read, then the booking is written — two
  concurrent requests for the last seat can both pass the check.
- **Suggested fix:** take a row lock on the Cab Route (`for_update=True`) around the
  re-check + write.
- **Risk impact:** route overbooking.

### DEF-06 — Unescaped SQL interpolation in permission query 🟡 MEDIUM
- **Module:** RBAC (`get_permission_query_conditions`, Employee branch)
- **Problem:** builds `f"...employee_id = '{employee_id}'"` without `frappe.db.escape`
  (the Driver branch *does* escape — inconsistent).
- **Root cause:** missing escaping.
- **Suggested fix:** `frappe.db.escape(employee_id)`.
- **Risk impact:** low exploitability (employee_id is system-generated) but injection-shaped
  and inconsistent with the rest of the file.

### DEF-07 — Debug `msgprint` left in `sync_vehicle_status` 🔵 LOW
- **Module:** Vehicle (`api/vehicle.py`)
- **Problem:** every Vehicle save pops up *"Running hook update for Vehicle…"* and
  *"Found N Cab Route(s)…"*.
- **Suggested fix:** remove the two `frappe.msgprint` calls.
- **Risk impact:** unprofessional UX; noise on every Vehicle update.

### DEF-08 — Dead code: `send_status_mail` 🔵 LOW
- **Module:** Cab Request
- **Problem:** `CabRequest.send_status_mail` is defined but never invoked (no hook wires it).
- **Suggested fix:** wire it intentionally to `on_update`, or delete it.

### DEF-09 — Submittable doctype with status managed outside docstatus 🔵 LOW
- **Module:** Cab Request
- **Problem:** `is_submittable = 1` with an `amended_from` field, but the lifecycle is the
  `status` field; 19/21 rows are `docstatus 0`. Submit/amend is effectively unused.
- **Suggested fix:** decide — drop `is_submittable`, or genuinely adopt docstatus.

### DEF-10 — Vendor billing race window 🔵 LOW
- **Module:** Billing (`generate_invoices`)
- **Problem:** between `get_billable_trips` and setting `invoice_link`, a concurrent run
  could double-invoice the same trips.
- **Suggested fix:** row-lock candidate trips, or set a provisional marker before insert.
- **Risk impact:** low probability (managers rarely click simultaneously; monthly job is
  single-run) but financially material if it occurs.

---

## 3. QA strategy

| Layer | Approach |
|---|---|
| Unit | Per-doctype `validate`, `cab_status` transitions, geo/billing/fuel calculations |
| Integration | Booking → OTP → trip → completion → billing chain end-to-end |
| API | Each `@frappe.whitelist()` method: happy path, bad input, unauthorised caller |
| RBAC | Each role (Employee/Driver/Fleet Manager/System Manager) against each doctype + the no-role case |
| Regression | Re-run the Phase 1–5 verification suites after every change |
| Performance | Query plans on `get_all_routes_for_manager`, GPS latest-per-vehicle, report SQL |
| UAT | Role-based business scenarios (§7) |

---

## 4. Enterprise testing checklist

**Vehicle / Driver Management** — CRUD per role; compliance-field validation; licence/insurance expiry surfaced.
**Trip / Booking** — book ≥1h ahead; past-date rejected; double-booking blocked; seat count accurate; OTP generated/one-time-use; status transitions follow the state machine; invalid transitions rejected.
**Route Management** — waypoints ordered; geo-matching threshold honoured; route polyline generated.
**Fuel / Maintenance** — fuel logged; mileage & cost/km correct; service-due detection by date and odometer.
**Vendor / Billing** — auto-invoice groups by vendor+month; amount = rate × distance; double-billing blocked; reconciliation states correct.
**RBAC** — no cross-role data leakage; no-role user sees nothing *(DEF-01)*; API methods reject unauthorised callers.
**GPS** — ingest validates coordinates & vehicle ownership *(DEF-04)*; live map shows latest, flags stale; purge respects retention.
**Schedulers** — daily/monthly jobs run, are idempotent, log failures.
**Audit** — every status change produces a Cab Request Status Log row; log is append-only.
**Reports / Dashboards** — KPIs match source data; filters apply; number cards compute.

---

## 5. Priority-wise test plan

| Priority | Scope | Gate |
|---|---|---|
| P0 | DEF-01, DEF-02 — fix + retest | Blocks go-live |
| P1 | Booking/OTP lifecycle, billing accuracy, RBAC matrix, DEF-04 | Blocks UAT sign-off |
| P2 | Schedulers, GPS, reports/dashboards, DEF-03, DEF-05 | Blocks production sign-off |
| P3 | DEF-06–DEF-10, UX polish | Fast-follow / post-go-live |

---

## 6. Regression test plan

Run after every change (all have automated verification scripts from Phases 1–5):
1. State machine — invalid transitions rejected, audit rows written.
2. Booking — book/cancel/OTP/complete happy path.
3. Billing — generate invoices, double-billing guard, reconciliation states.
4. Reports — all 6 execute without error, KPIs non-zero with demo data.
5. GPS — ingest/serve/purge.
6. RBAC — permission query per role (incl. the no-role case).
7. Schedulers — `bench execute` each job, no exception.

---

## 7. UAT matrix

| # | Role | Scenario | Expected |
|---|---|---|---|
| U1 | Employee | Book a cab ≥1h ahead, pick a matched route | Booking `Assigned`, OTP emailed |
| U2 | Employee | Attempt a 2nd booking while one is active | Blocked with clear message |
| U3 | Driver | Verify employee OTP, start trip | Status → `In Trip`; OTP consumed |
| U4 | Driver | Complete trip, record odometer | Status → `Completed`; `total_distance` set |
| U5 | Driver | Open another driver's trip | Denied |
| U6 | Fleet Manager | Open Cab Route & Cab Vendor Invoice | Accessible (Phase-5 RBAC fix) |
| U7 | Fleet Manager | Generate vendor invoices from reconciliation | Invoices created; trips marked Billed |
| U8 | No-role user | Open Cab Request list | **Must see nothing** *(DEF-01)* |
| U9 | Manager | Manager dashboard | KPI cards + charts populated |
| U10 | Driver | "Driver Route Tracking" shortcut | Opens `/driver_dashboard` |

---

## 8. Go-live readiness checklist

- [x] **DEF-01** — permission query returns `1=0` for no-role users — ✅ fixed & verified
- [x] **DEF-02** — legacy records editable (reqd relaxed + `validate_dates` scoped) — ✅ verified
- [x] DEF-03 — `status="Success"` row normalised — ✅ verified
- [x] DEF-04 — GPS vehicle-ownership check added — ✅ verified
- [x] DEF-05 / DEF-06 — booking row lock + SQL escaping — ✅ verified
- [x] DEF-07 / DEF-08 — debug `msgprint` and dead code removed — ✅ verified
- [x] DEF-10 — vendor-billing race closed (lock + re-check) — ✅ verified
- [ ] DEF-09 — `is_submittable` cleanup — deferred to a planned migration window
- [ ] **Scheduler resumed** — `bench --site cabtest.local scheduler resume`
- [ ] **SMTP configured** — required for compliance/booking emails to actually send
- [ ] Transport Settings — alert recipients & thresholds reviewed
- [ ] All Vehicles/Drivers have real compliance dates (demo data replaced)
- [x] Workspace shortcut URLs are relative — ✅ done
- [ ] Full regression suite (§6) green
- [ ] UAT matrix (§7) signed off
- [ ] Code committed and tagged
