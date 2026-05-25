// Copyright (c) 2026, our team and contributors
// For license information, please see license.txt
//
// Real-time driver location tracking — client-side wiring for Cab Request.
//
// Driver view  (user is the assigned driver, status Assigned|In Trip):
//   Starts navigator.geolocation.watchPosition and POSTs to
//   update_vehicle_location at most once per PING_INTERVAL_MS, plus a
//   keep-alive resend every PING_INTERVAL_MS when the driver is stationary.
//
// Viewer view  (manager OR the booking employee):
//   Fetches the latest known location once via get_my_driver_location, then
//   subscribes to the `tms_vehicle_location` realtime channel and to
//   `tms_geofence_event` for pickup/arrival notifications. If map.js stashes
//   a Leaflet map on `frm._tms_map`, a driver marker is dropped and moved.
//
// One-file module, no external deps. Safe to load alongside map.js.

(() => {
	"use strict";

	const PING_INTERVAL_MS = 10000;
	const NS = "transport_management.transport_management.api.gps";
	const ACTIVE_STATUSES = ["Assigned", "In Trip"];

	frappe.ui.form.on("Cab Request", {
		refresh(frm) {
			if (frm.is_new()) return;

			const active = ACTIVE_STATUSES.includes(frm.doc.status);

			// Trip is no longer Assigned / In Trip → tear down any running
			// pinger or viewer subscription so the driver's browser stops
			// posting GPS pings and the realtime channel is released.
			if (!active) {
				if (frm._tms_gps_stop) {
					frm._tms_gps_stop();
					const label = (frm.doc.status || "ended").toLowerCase();
					_panel(frm, `⏹️ Live tracking stopped — trip ${label}.`, "gray");
				}
				return;
			}

			// Already running (or mid-start) for this form — don't double-init.
			if (frm._tms_gps_stop || frm._tms_gps_starting) return;
			frm._tms_gps_starting = true;

			const roles = new Set(frappe.user_roles || []);
			const user = frappe.session.user;
			const isManager =
				roles.has("Fleet Manager") || roles.has("System Manager");
			const isDriver = roles.has("Driver");

			// Driver vs viewer is decided by the SERVER, because assigned_driver
			// can hold a user email, Driver doc name, Employee ID, or Employee
			// name — naive client-side compare would mis-route most drivers.
			if (isDriver && !isManager) {
				frappe.call({
					method: `${NS}.can_i_post_for_request`,
					args: { cab_request: frm.doc.name },
					callback: (r) => {
						frm._tms_gps_starting = false;
						// Status may have changed during the async round-trip;
						// re-check before we start watching geolocation.
						if (!ACTIVE_STATUSES.includes(frm.doc.status)) return;
						const res = (r && r.message) || {};
						if (res.can_post) {
							_startDriverPinger(frm, res.vehicle);
						} else {
							// Driver role but not assigned to this specific
							// request → treat them as a viewer.
							_startViewerSubscriber(frm);
						}
					},
				});
			} else if (isManager || _isOwnRequest(frm, user)) {
				frm._tms_gps_starting = false;
				_startViewerSubscriber(frm);
			} else {
				frm._tms_gps_starting = false;
			}
		},

		on_unload(frm) {
			if (frm._tms_gps_stop) frm._tms_gps_stop();
		},
	});

	// ─── identity helpers ────────────────────────────────────────────────────

	function _isOwnRequest(frm, user) {
		return frm.doc.owner === user;
	}

	// ─── DRIVER ──────────────────────────────────────────────────────────────

	function _startDriverPinger(frm, vehicle) {
		if (!navigator.geolocation) {
			_panel(frm, "❌ Geolocation not supported by this browser.", "red");
			return;
		}
		if (!vehicle) {
			_panel(
				frm,
				"⚠️ No vehicle assigned — cannot start live tracking.",
				"orange",
			);
			return;
		}

		_panel(frm, "📍 Requesting location permission…", "blue");

		const state = { lastSentAt: 0, lastPos: null };

		const onPos = (pos) => {
			state.lastPos = pos;
			_maybeSend(frm, vehicle, state);
		};
		const onErr = (err) => {
			_panel(frm, `⚠️ Location error: ${err.message}`, "red");
		};

		const watchId = navigator.geolocation.watchPosition(onPos, onErr, {
			enableHighAccuracy: true,
			maximumAge: 5000,
			timeout: 15000,
		});

		// Keep-alive resend so the manager map keeps a fresh timestamp even
		// when the driver is stationary and the browser stops firing onPos.
		const keepAlive = setInterval(() => {
			_maybeSend(frm, vehicle, state, /*force*/ true);
		}, PING_INTERVAL_MS);

		const stop = () => {
			navigator.geolocation.clearWatch(watchId);
			clearInterval(keepAlive);
			frm._tms_gps_stop = null;
		};
		frm._tms_gps_stop = stop;
		$(window).one("beforeunload", stop);
	}

	function _maybeSend(frm, vehicle, state, force) {
		if (!state.lastPos) return;
		const now = Date.now();
		if (!force && now - state.lastSentAt < PING_INTERVAL_MS) return;
		state.lastSentAt = now;

		const c = state.lastPos.coords;
		frappe.call({
			method: `${NS}.update_vehicle_location`,
			args: {
				vehicle: vehicle,
				latitude: c.latitude,
				longitude: c.longitude,
				speed_kmph:
					c.speed != null && !isNaN(c.speed)
						? Math.round(c.speed * 3.6)
						: null,
			},
			callback: (r) => {
				if (!r || r.exc) return;
				const t = new Date().toLocaleTimeString();
				const acc = c.accuracy ? ` · ±${Math.round(c.accuracy)}m` : "";
				_panel(
					frm,
					`🟢 Live · ping @ ${t}${acc}`,
					"green",
				);
			},
		});
	}

	// ─── VIEWER (employee / manager) ─────────────────────────────────────────

	function _startViewerSubscriber(frm) {
		const vehicle = frm.doc.assigned_cab;

		// One-shot initial fetch — fills the panel even before the first
		// realtime event arrives.
		frappe.call({
			method: `${NS}.get_my_driver_location`,
			args: { cab_request: frm.doc.name },
			callback: (r) => {
				const msg = (r && r.message) || {};
				if (msg.available) {
					_renderPing(frm, msg);
				} else {
					_panel(frm, msg.message || "No live location yet.", "gray");
				}
			},
		});

		if (!vehicle) return;

		// Subscribe to the doctype room so the server's `publish_realtime`
		// (scoped to doctype="Vehicle GPS Log") reaches us. Per-listener
		// `frappe.realtime.off` cleanup is enough — we deliberately do NOT
		// `doctype_unsubscribe` on teardown, because that command leaves the
		// shared SocketIO room for every tab in this session, breaking other
		// managers/employees currently viewing other trips.
		try {
			frappe.realtime.doctype_subscribe("Vehicle GPS Log");
		} catch (_e) {
			/* older Frappe — global subscription still works */
		}

		const onLocation = (data) => {
			if (!data || data.vehicle !== vehicle) return;
			_renderPing(frm, {
				latitude: data.latitude,
				longitude: data.longitude,
				speed_kmph: data.speed_kmph,
				recorded_at: data.recorded_at,
				seconds_ago: 0,
				is_stale: false,
			});
		};
		const onGeofence = (data) => {
			if (!data || data.cab_request !== frm.doc.name) return;
			frappe.show_alert(
				{ message: data.label, indicator: "blue" },
				12,
			);
		};

		frappe.realtime.on("tms_vehicle_location", onLocation);
		frappe.realtime.on("tms_geofence_event", onGeofence);

		const stop = () => {
			frappe.realtime.off("tms_vehicle_location", onLocation);
			frappe.realtime.off("tms_geofence_event", onGeofence);
			frm._tms_gps_stop = null;
		};
		frm._tms_gps_stop = stop;
		$(window).one("beforeunload", stop);
	}

	function _renderPing(frm, ping) {
		const speed =
			ping.speed_kmph != null
				? ` · ${Math.round(ping.speed_kmph)} km/h`
				: "";
		const age = _ageLabel(ping.seconds_ago);
		const stale = ping.is_stale ? " ⚠️ stale" : "";
		const mapsHref = `https://www.google.com/maps?q=${ping.latitude},${ping.longitude}`;
		const html = `
			<span style="font-weight:600;">🚗 Driver</span>
			· (${(+ping.latitude).toFixed(5)}, ${(+ping.longitude).toFixed(5)})${speed}${age}${stale}
			· <a href="${mapsHref}" target="_blank" rel="noopener">open in maps ↗</a>
		`;
		_panel(frm, html, ping.is_stale ? "orange" : "green");

		// If the existing map.js stashes a Leaflet map on the form, drop or
		// move a driver marker on it.
		const map = frm._tms_map;
		if (map && window.L) {
			const latlng = [ping.latitude, ping.longitude];
			if (!frm._tms_driver_marker) {
				const icon = L.divIcon({
					className: "tms-driver-marker",
					html:
						'<div style="background:#0d6efd;color:#fff;border-radius:50%;' +
						"width:30px;height:30px;display:flex;align-items:center;" +
						"justify-content:center;border:2px solid #fff;" +
						'box-shadow:0 1px 4px rgba(0,0,0,0.4);font-size:14px;">🚗</div>',
					iconSize: [30, 30],
					iconAnchor: [15, 15],
				});
				frm._tms_driver_marker = L.marker(latlng, { icon }).addTo(map);
			} else {
				frm._tms_driver_marker.setLatLng(latlng);
			}
		}
	}

	function _ageLabel(seconds) {
		if (seconds == null) return " · just now";
		if (seconds < 60) return ` · ${Math.round(seconds)}s ago`;
		return ` · ${Math.round(seconds / 60)}m ago`;
	}

	// ─── shared panel ────────────────────────────────────────────────────────

	function _panel(frm, html, color) {
		const colors = {
			green: "#28a745",
			red: "#dc3545",
			orange: "#fd7e14",
			blue: "#0d6efd",
			gray: "#6c757d",
		};
		const c = colors[color] || colors.gray;
		if (!frm._tms_gps_$panel) {
			const $p = $(
				'<div class="tms-live-panel" style="margin:10px 0;padding:10px 14px;' +
					"background:#f8f9fa;border-radius:4px;font-size:13px;" +
					'border-left:4px solid #ccc;"></div>',
			);
			$(frm.layout.wrapper).prepend($p);
			frm._tms_gps_$panel = $p;
		}
		frm._tms_gps_$panel.css("border-left-color", c).html(html);
	}
})();
