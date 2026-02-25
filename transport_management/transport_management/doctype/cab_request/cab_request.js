frappe.ui.form.on("Cab Request", {

    setup: function(frm) {
        // Check roles once when the form sets up
        frm.is_employee = frappe.user.has_role("Employee");
        frm.is_driver = frappe.user.has_role("Driver");
        frm.is_manager = frappe.user.has_role("Fleet Manager") || frappe.user.has_role("System Manager");
    },

    onload: function(frm) {
        // 1. AUTO-FETCH EMPLOYEE DETAILS (Only for new documents created by Employees)
        if (frm.is_new() && frm.is_employee && !frm.is_manager) {
            frappe.call({
                method: "transport_management.transport_management.doctype.cab_request.cab_request.get_employee_basic_details",
                callback: function(r) {
                    if (r.message) {
                        frm.set_value("employee_id", r.message.name);
                        frm.set_value("employee_name", r.message.employee_name);
                        frm.set_value("department", r.message.department);
                        frm.set_value("contact_no", r.message.mobile_no);
                    }
                }
            });
        }

        // ── ROLE-BASED STATUS DROPDOWN FILTER ──
        if (frm.is_driver && !frm.is_manager) {
            frm.set_df_property("status", "options", "In Trip\nCompleted\nCancelled");
        } else if (frm.is_manager) {
            frm.set_df_property("status", "options", "Pending\nAssigned\nRejected\nCancelled\nIn Trip\nCompleted");
        } else {
            frm.set_df_property("status", "options", "Pending\nAssigned\nRejected\nCancelled");
        }
    },

    refresh: function(frm) {

        // 4. LOGIC FOR FLEET MANAGER VIEW — runs FIRST with return to prevent override
        if (frm.is_manager) {
            // Manager sees everything — unhide allocation fields
            frm.set_df_property("driver_id", "hidden", 0);
            frm.set_df_property("cab", "hidden", 0);
            frm.set_df_property("assigned_driver", "hidden", 0);
            frm.set_df_property("assigned_cab", "hidden", 0);

            // These are auto-set by code, so make them read-only for manager too
            frm.set_df_property("assigned_driver", "read_only", 1);
            frm.set_df_property("assigned_cab", "read_only", 1);

            // Force refresh so fields actually render visible
            frm.refresh_field("driver_id");
            frm.refresh_field("cab");
            frm.refresh_field("assigned_driver");
            frm.refresh_field("assigned_cab");

            // ── Force Manager status options on every refresh ──
            frm.set_df_property("status", "options", "Pending\nAssigned\nRejected\nCancelled\nIn Trip\nCompleted");
            frm.refresh_field("status");

            // Show/hide rejection reason based on status
            if (frm.doc.status === "Rejected") {
                frm.set_df_property("rejection_reason", "hidden", 0);
                frm.set_df_property("rejection_reason", "reqd", 1);
            } else {
                frm.set_df_property("rejection_reason", "hidden", 1);
                frm.set_df_property("rejection_reason", "reqd", 0);
            }
            frm.refresh_field("rejection_reason");

            return; // IMPORTANT: Stop here so Employee/Driver blocks don't override
        }

        // 3. LOGIC FOR DRIVER VIEW
        if (frm.is_driver) {
            // ── Force Driver status options on every refresh ──
            frm.set_df_property("status", "options", "In Trip\nCompleted\nCancelled");
            frm.refresh_field("status");

            // Make the ENTIRE form read-only
            frm.set_read_only(true);

            // Explicitly lock key fields
            frm.set_df_property("status", "read_only", 1);
            frm.set_df_property("pickup_location", "read_only", 1);
            frm.set_df_property("drop_location", "read_only", 1);
            frm.set_df_property("booking_datetime", "read_only", 1);
            frm.set_df_property("employee_name", "read_only", 1);
            frm.set_df_property("contact_no", "read_only", 1);

            // Hide internal allocation fields
            frm.set_df_property("rejection_reason", "hidden", 1);
            frm.set_df_property("driver_id", "hidden", 1);

            // Remove Save button
            frm.disable_save();

            // ── "Start Trip" button ──
            if (frm.doc.status === "Assigned") {
                frm.add_custom_button(__("Start Trip"), function() {
                    frappe.confirm(
                        "Are you sure you want to <b>Start</b> this trip? This will change status to <b>In Trip</b>.",
                        function() {
                            frappe.call({
                                method: "transport_management.transport_management.doctype.cab_request.cab_request.driver_start_trip",
                                args: { docname: frm.doc.name },
                                callback: function(r) {
                                    if (!r.exc) {
                                        frappe.show_alert({
                                            message: "Trip started! Status is now In Trip.",
                                            indicator: "blue"
                                        }, 5);
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }).addClass("btn-primary");
            }

            // ── "Complete Trip" button ──
            if (frm.doc.status === "In Trip") {
                frm.add_custom_button(__("Complete Trip"), function() {
                    frappe.confirm(
                        "Are you sure you want to mark this trip as <b>Completed</b>?",
                        function() {
                            frappe.call({
                                method: "transport_management.transport_management.doctype.cab_request.cab_request.driver_complete_trip",
                                args: { docname: frm.doc.name },
                                callback: function(r) {
                                    if (!r.exc) {
                                        frappe.show_alert({
                                            message: "Trip marked as Completed successfully!",
                                            indicator: "green"
                                        }, 5);
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }).addClass("btn-success");
            }

            return; // IMPORTANT: Stop here so Employee block doesn't override
        }

        // 2. LOGIC FOR EMPLOYEE VIEW (runs only if not Manager and not Driver)
        if (frm.is_employee) {
            // Hide the Manager's Allocation controls
            frm.set_df_property("driver_id", "hidden", 1);
            frm.set_df_property("cab", "hidden", 1);

            // Only show Rejection Reason if actually rejected
            if (frm.doc.status === "Rejected") {
                frm.set_df_property("rejection_reason", "hidden", 0);
            } else {
                frm.set_df_property("rejection_reason", "hidden", 1);
            }

            // Only show Assigned details if Assigned, In Trip or Completed
            if (["Assigned", "In Trip", "Completed"].includes(frm.doc.status)) {
                frm.set_df_property("assigned_driver", "hidden", 0);
                frm.set_df_property("assigned_cab", "hidden", 0);
            } else {
                frm.set_df_property("assigned_driver", "hidden", 1);
                frm.set_df_property("assigned_cab", "hidden", 1);
            }

            // Employee status is always read-only
            frm.set_df_property("status", "read_only", 1);

            // ── "Cancel Trip" button: Employee can cancel ONLY when status is Assigned ──
            if (frm.doc.status === "Assigned") {
                frm.add_custom_button(__("Cancel Trip"), function() {
                    frappe.confirm(
                        "Are you sure you want to <b>Cancel</b> this cab request?",
                        function() {
                            frappe.call({
                                method: "transport_management.transport_management.doctype.cab_request.cab_request.employee_cancel_trip",
                                args: { docname: frm.doc.name },
                                callback: function(r) {
                                    if (!r.exc) {
                                        frappe.show_alert({
                                            message: "Trip cancelled successfully.",
                                            indicator: "orange"
                                        }, 5);
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }).addClass("btn-danger");
            }
        }
    },

    // 5. VALIDATE: Driver and Cab must be assigned before saving when status is Assigned
    before_save: function(frm) {
        if (frm.is_manager && frm.doc.status === "Assigned") {
            if (!frm.doc.driver_id) {
                frappe.throw(__("Please assign a <b>Driver</b> before setting status to Assigned."));
            }
            if (!frm.doc.cab) {
                frappe.throw(__("Please assign a <b>Cab</b> before setting status to Assigned."));
            }
        }
    },

    // 6. UX: Show Rejection Reason box immediately when Manager selects "Rejected"
    status: function(frm) {
        if (frm.doc.status === "Rejected") {
            frm.set_df_property("rejection_reason", "hidden", 0);
            frm.set_df_property("rejection_reason", "reqd", 1);
        } else {
            frm.set_df_property("rejection_reason", "hidden", 1);
            frm.set_df_property("rejection_reason", "reqd", 0);
        }
    }
});


// =============================================================
//  ROUTE-BASED CAB FINDER  (OpenStreetMap / Leaflet)
//  All new code below — nothing above is changed
// =============================================================

// ── Leaflet loader (CDN, no install needed) ───────────────────
function _load_leaflet(cb) {
    if (window.L) return cb();
    var css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    var js = document.createElement("script");
    js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    js.onload = cb;
    document.head.appendChild(js);
}

// ── Dialog-scoped state ───────────────────────────────────────
var _dlg_map           = null;
var _dlg_pickup_marker = null;
var _dlg_route_layers  = [];
var _dlg_cabs          = [];
var _dlg_pickup_lat    = null;
var _dlg_pickup_lng    = null;
var _dlg_pickup_addr   = null;

var _ROUTE_COLORS = ["#2563eb","#dc2626","#059669","#d97706","#7c3aed","#0891b2"];

// ── "Find Cab by Route" button — wired via secondary refresh listener ─────────
frappe.ui.form.on("Cab Request", {
    refresh: function(frm) {
        // Only show for Employees on new / Pending docs
        if (
            frm.is_employee &&
            !frm.is_manager &&
            !frm.is_driver &&
            (!frm.doc.status || frm.doc.status === "Pending")
        ) {
            frm.add_custom_button(__("🔍 Find Cab by Route"), function() {
                _open_cab_finder(frm);
            });
        }
    }
});


// ── Main dialog ───────────────────────────────────────────────
function _open_cab_finder(frm) {
    _dlg_map = null; _dlg_pickup_marker = null;
    _dlg_route_layers = []; _dlg_cabs = [];
    _dlg_pickup_lat = null; _dlg_pickup_lng = null; _dlg_pickup_addr = null;

    var dialog = new frappe.ui.Dialog({
        title: "🚕 Find Cab by Route",
        size: "extra-large",
        fields: [
            {
                fieldname: "map_html",
                fieldtype: "HTML",
                options:
                    '<div style="margin-bottom:10px">' +
                    '<div style="position:relative;margin-bottom:6px">' +
                    '<input id="_dlg_addr_input" type="text" placeholder="🔍 Search your pickup address…" ' +
                    'style="width:100%;padding:10px 70px 10px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:13px;box-sizing:border-box"/>' +
                    '<button id="_dlg_addr_btn" style="position:absolute;right:6px;top:6px;background:#2563eb;color:white;border:none;padding:4px 14px;border-radius:6px;cursor:pointer;font-size:13px">Search</button>' +
                    '</div>' +
                    '<div id="_dlg_addr_results" style="background:white;border:1px solid #e5e7eb;border-radius:6px;max-height:140px;overflow-y:auto;display:none;box-shadow:0 4px 12px rgba(0,0,0,0.1);margin-bottom:6px"></div>' +
                    '<div id="_dlg_map" style="height:300px;border-radius:10px;border:1px solid #e5e7eb"></div>' +
                    '<p style="color:#6b7280;font-size:12px;margin:5px 0 0">📍 Click on map or search above to set your pickup location</p>' +
                    '<p id="_dlg_selected_addr" style="color:#059669;font-size:13px;font-weight:500;min-height:16px;margin:2px 0 0"></p>' +
                    '</div>'
            },
            { fieldname: "shift_type",   fieldtype: "Select", label: "Shift Type",
              options: "Morning\nEvening\nNight\nGeneral", reqd: 1 },
            { fieldname: "travel_date",  fieldtype: "Date", label: "Travel Date", reqd: 1,
              default: frappe.datetime.get_today() },
            { fieldname: "threshold_km", fieldtype: "Float", label: "Search Radius (km)", default: 1.5,
              description: "Cabs whose route passes within this distance from your pin" },
            { fieldname: "cabs_html",    fieldtype: "HTML",
              options: '<div id="_dlg_cabs_list" style="margin-top:10px"></div>' }
        ],
        primary_action_label: "Search Cabs",
        primary_action: function(vals) {
            if (!_dlg_pickup_lat || !_dlg_pickup_lng) {
                frappe.msgprint({ message: "Please pin your pickup location on the map first.", indicator: "orange" });
                return;
            }
            if (!vals.shift_type || !vals.travel_date) {
                frappe.msgprint({ message: "Please fill Shift Type and Travel Date.", indicator: "orange" });
                return;
            }
            _search_cabs(frm, dialog, vals);
        }
    });

    dialog.show();
    setTimeout(function() {
        _load_leaflet(function() { _init_dlg_map(); });
        _attach_address_search();
    }, 350);
}


// ── Map init ──────────────────────────────────────────────────
function _init_dlg_map() {
    var el = document.getElementById("_dlg_map");
    if (!el || _dlg_map) return;

    _dlg_map = L.map("_dlg_map", { zoomControl: true });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: "© OpenStreetMap contributors"
    }).addTo(_dlg_map);

    _dlg_map.setView([12.9716, 77.5946], 12); // ← Change to your city's lat/lng

    _dlg_map.on("click", function(e) {
        _set_pickup(e.latlng.lat, e.latlng.lng);
        _reverse_geocode(e.latlng.lat, e.latlng.lng);
    });
}

function _set_pickup(lat, lng, address) {
    _dlg_pickup_lat = lat;
    _dlg_pickup_lng = lng;
    if (address) _dlg_pickup_addr = address;

    if (_dlg_pickup_marker) _dlg_map.removeLayer(_dlg_pickup_marker);

    _dlg_pickup_marker = L.marker([lat, lng], { icon: _pickup_icon(), draggable: true })
        .addTo(_dlg_map).bindPopup("📍 Your Pickup").openPopup();

    _dlg_pickup_marker.on("dragend", function(e) {
        var pos = e.target.getLatLng();
        _set_pickup(pos.lat, pos.lng);
        _reverse_geocode(pos.lat, pos.lng);
    });

    if (address) {
        var el = document.getElementById("_dlg_selected_addr");
        if (el) el.textContent = "📍 " + address;
    }
}

function _reverse_geocode(lat, lng) {
    fetch("https://nominatim.openstreetmap.org/reverse?lat=" + lat + "&lon=" + lng + "&format=json")
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var addr = d.display_name || (lat.toFixed(5) + ", " + lng.toFixed(5));
            _dlg_pickup_addr = addr;
            var inp = document.getElementById("_dlg_addr_input");
            if (inp) inp.value = addr;
            var el = document.getElementById("_dlg_selected_addr");
            if (el) el.textContent = "📍 " + addr;
        })
        .catch(function() {});
}


// ── Address search (Nominatim / OSM — no API key needed) ─────
function _attach_address_search() {
    var input   = document.getElementById("_dlg_addr_input");
    var btn     = document.getElementById("_dlg_addr_btn");
    var resList = document.getElementById("_dlg_addr_results");
    if (!input || !btn) return;

    var _timer;
    input.addEventListener("input", function() {
        clearTimeout(_timer);
        var q = input.value.trim();
        if (q.length < 3) { resList.style.display = "none"; return; }
        _timer = setTimeout(function() { _nominatim_search(q, resList); }, 450);
    });
    btn.addEventListener("click", function() { _nominatim_search(input.value.trim(), resList); });
    input.addEventListener("keydown", function(e) {
        if (e.key === "Enter") _nominatim_search(input.value.trim(), resList);
    });
}

function _nominatim_search(q, resList) {
    if (!q) return;
    fetch("https://nominatim.openstreetmap.org/search?q=" + encodeURIComponent(q) + "&format=json&limit=6")
        .then(function(r) { return r.json(); })
        .then(function(results) {
            resList.innerHTML = "";
            if (!results.length) {
                resList.innerHTML = '<div style="padding:8px 12px;color:#6b7280;font-size:13px">No results found</div>';
                resList.style.display = "block";
                return;
            }
            results.forEach(function(res) {
                var item = document.createElement("div");
                item.style.cssText = "padding:8px 12px;cursor:pointer;border-bottom:1px solid #f3f4f6;font-size:13px";
                item.textContent = res.display_name;
                item.onmouseover = function() { item.style.background = "#eff6ff"; };
                item.onmouseout  = function() { item.style.background = "white"; };
                item.onclick = function() {
                    var lat = parseFloat(res.lat);
                    var lng = parseFloat(res.lon);
                    _set_pickup(lat, lng, res.display_name);
                    _dlg_map.setView([lat, lng], 16);
                    resList.style.display = "none";
                    document.getElementById("_dlg_addr_input").value = res.display_name;
                };
                resList.appendChild(item);
            });
            resList.style.display = "block";
        })
        .catch(function() {});
}


// ── Call backend & render results ────────────────────────────
function _search_cabs(frm, dialog, vals) {
    var listEl = document.getElementById("_dlg_cabs_list");
    listEl.innerHTML = '<div style="text-align:center;padding:30px;color:#2563eb">🔍 Searching cabs near your location…</div>';

    frappe.call({
        method: "transport_management.transport_management.doctype.cab_request.cab_request.find_matching_cabs",
        args: {
            employee_lat:  _dlg_pickup_lat,
            employee_lng:  _dlg_pickup_lng,
            travel_date:   vals.travel_date,
            shift_type:    vals.shift_type,
            threshold_km:  vals.threshold_km || 1.5
        },
        callback: function(r) {
            if (r.exc) {
                listEl.innerHTML = '<div style="color:#dc2626;padding:16px">Error finding cabs. Please check console.</div>';
                return;
            }
            _dlg_cabs = r.message || [];
            _render_cab_cards(frm, dialog, vals);
            _render_routes_on_map(_dlg_cabs);
        }
    });
}


// ── Cab cards ─────────────────────────────────────────────────
function _render_cab_cards(frm, dialog, vals) {
    var listEl = document.getElementById("_dlg_cabs_list");

    if (!_dlg_cabs.length) {
        listEl.innerHTML =
            '<div style="text-align:center;padding:30px;background:#fef3c7;border-radius:10px;color:#92400e">' +
            '<div style="font-size:30px;margin-bottom:8px">😔</div>' +
            '<h4 style="margin:0 0 4px">No cabs found near your location</h4>' +
            '<p style="margin:0;font-size:13px">Try increasing the search radius or contact HR.</p></div>';
        return;
    }

    var cards = _dlg_cabs.map(function(cab, idx) {
        var color    = _ROUTE_COLORS[idx % _ROUTE_COLORS.length];
        var pct      = Math.round((cab.booked_seats / cab.total_seats) * 100);
        var aclr     = cab.available_seats > 3 ? "#065f46" : "#92400e";
        var abg      = cab.available_seats > 3 ? "#d1fae5" : "#fef3c7";
        var bclr     = cab.available_seats > 3 ? "#10b981" : "#f59e0b";
        var stopTime = cab.nearest_pickup_time ? " @ " + cab.nearest_pickup_time : "";

        return '<div style="border:2px solid #e5e7eb;border-radius:10px;padding:14px;margin-bottom:10px;' +
               'background:white;box-shadow:0 1px 4px rgba(0,0,0,0.07)" ' +
               'onmouseover="this.style.borderColor=\'' + color + '\'" onmouseout="this.style.borderColor=\'#e5e7eb\'">' +

               '<div style="display:flex;align-items:start;gap:10px">' +
               '<div style="background:' + color + ';color:white;border-radius:8px;padding:6px 12px;font-size:12px;font-weight:bold;white-space:nowrap;flex-shrink:0">#' + (idx+1) + '</div>' +
               '<div style="flex:1">' +
               '<div style="font-size:15px;font-weight:600;color:#1e40af">🚌 ' + cab.route_name + '</div>' +
               '<div style="font-size:12px;color:#6b7280;margin-top:2px">' + cab.start_location + ' → ' + cab.end_location + '</div>' +
               '</div>' +
               '<div style="background:' + abg + ';color:' + aclr + ';border-radius:10px;text-align:center;padding:6px 12px;flex-shrink:0">' +
               '<div style="font-size:20px;font-weight:700">' + cab.available_seats + '</div>' +
               '<div style="font-size:10px">seats left</div></div></div>' +

               '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:10px 0;font-size:12px;color:#374151">' +
               '<div>🚗 <b>' + (cab.license_plate || cab.vehicle) + '</b></div>' +
               '<div>🕐 <b>' + cab.shift_time + '</b></div>' +
               '<div>📏 <b>' + cab.distance_from_route + ' km</b> away</div>' +
               '<div>👤 ' + (cab.driver_name || "Driver TBD") + '</div>' +
               '<div>📞 ' + (cab.driver_contact || "—") + '</div>' +
               '<div>🛑 Stop: <b>' + (cab.nearest_stop || "On Route") + '</b>' + stopTime + '</div></div>' +

               '<div style="background:#f3f4f6;border-radius:4px;height:5px;margin-bottom:4px">' +
               '<div style="background:' + bclr + ';height:5px;border-radius:4px;width:' + pct + '%"></div></div>' +
               '<div style="font-size:11px;color:#9ca3af;margin-bottom:10px">' + cab.booked_seats + ' / ' + cab.total_seats + ' seats booked</div>' +

               '<div style="display:flex;gap:8px">' +
               '<button onclick="_cab_view_on_map(\'' + cab.route + '\')" ' +
               'style="flex:1;background:white;color:' + color + ';border:1.5px solid ' + color + ';padding:7px 0;border-radius:7px;cursor:pointer;font-size:13px;font-weight:500">🗺 View on Map</button>' +
               '<button onclick="_cab_book_now(\'' + frm.doc.name + '\',\'' + cab.route + '\',\'' + cab.route_name + '\',' +
               '\'' + (cab.nearest_stop || "") + '\',' + (cab.nearest_stop_lat || null) + ',' + (cab.nearest_stop_lng || null) + ',' +
               '\'' + (cab.nearest_pickup_time || "") + '\',' + cab.distance_from_route + ')" ' +
               'style="flex:2;background:' + color + ';color:white;border:none;padding:7px 0;border-radius:7px;cursor:pointer;font-size:13px;font-weight:600">✅ Book This Cab</button>' +
               '</div></div>';
    }).join("");

    listEl.innerHTML =
        '<div style="margin-bottom:10px;font-weight:600;color:#374151">Found <span style="color:#2563eb">' +
        _dlg_cabs.length + '</span> cab(s) matching your route:</div>' + cards;
}


// ── Draw routes on map ────────────────────────────────────────
function _render_routes_on_map(cabs) {
    _dlg_route_layers.forEach(function(l) { if (_dlg_map) _dlg_map.removeLayer(l); });
    _dlg_route_layers = [];
    if (!_dlg_map) return;

    cabs.forEach(function(cab, idx) {
        var color = _ROUTE_COLORS[idx % _ROUTE_COLORS.length];
        var wps   = (cab.waypoints || []).slice().sort(function(a,b){ return a.sequence - b.sequence; });
        if (wps.length < 2) return;

        var path = wps.map(function(wp) { return [wp.latitude, wp.longitude]; });
        var poly = L.polyline(path, { color: color, weight: 4, opacity: 0.8, dashArray: "6,3" })
            .addTo(_dlg_map)
            .bindPopup("<b>" + cab.route_name + "</b><br>" + cab.start_location + " → " + cab.end_location);
        _dlg_route_layers.push(poly);

        wps.forEach(function(wp) {
            if (!wp.latitude || !wp.longitude) return;
            var circle = L.circleMarker([wp.latitude, wp.longitude], {
                radius: 6, color: "white", fillColor: color, fillOpacity: 1, weight: 2
            }).addTo(_dlg_map).bindPopup("<b>" + wp.stop_name + "</b>" + (wp.pickup_time ? "<br>⏰ " + wp.pickup_time : ""));
            _dlg_route_layers.push(circle);
        });
    });
}

window._cab_view_on_map = function(route_name) {
    var cab = (_dlg_cabs || []).find(function(c) { return c.route === route_name; });
    if (!cab || !_dlg_map) return;
    var wps = (cab.waypoints || []).filter(function(w) { return w.latitude && w.longitude; });
    if (!wps.length) return;
    _dlg_map.fitBounds(L.latLngBounds(wps.map(function(w) { return [w.latitude, w.longitude]; })), { padding: [40, 40] });
};


// ── Book button ───────────────────────────────────────────────
window._cab_book_now = function(
    cab_request_name, route_name, route_display,
    nearest_stop, nearest_stop_lat, nearest_stop_lng,
    nearest_pickup_time, distance_from_route
) {
    frappe.confirm(
        "Book <b>" + route_display + "</b>?<br>Nearest stop: <b>" + (nearest_stop || "On Route") + "</b>" +
        (nearest_pickup_time ? " @ " + nearest_pickup_time : ""),
        function() {
            frappe.call({
                method: "transport_management.transport_management.doctype.cab_request.cab_request.book_route_cab",
                args: {
                    cab_request_name:    cab_request_name,
                    route_name:          route_name,
                    pickup_lat:          _dlg_pickup_lat,
                    pickup_lng:          _dlg_pickup_lng,
                    pickup_address:      _dlg_pickup_addr || "",
                    nearest_stop:        nearest_stop,
                    nearest_stop_lat:    nearest_stop_lat,
                    nearest_stop_lng:    nearest_stop_lng,
                    nearest_pickup_time: nearest_pickup_time,
                    distance_from_route: distance_from_route
                },
                freeze: true,
                freeze_message: "Booking your cab…",
                callback: function(r) {
                    if (r.message && r.message.status === "success") {
                        frappe.msgprint({ title: "Cab Booked! 🎉", message: r.message.message, indicator: "green" });
                        var closeBtn = document.querySelector(".modal.show .btn-modal-close");
                        if (closeBtn) closeBtn.click();
                        cur_frm.reload_doc();
                    }
                }
            });
        }
    );
};


// ── Pickup icon ───────────────────────────────────────────────
function _pickup_icon() {
    return L.divIcon({
        className: "",
        html: '<div style="background:#2563eb;color:white;font-size:16px;width:34px;height:34px;' +
              'border-radius:50% 50% 50% 0;transform:rotate(-45deg);display:flex;align-items:center;' +
              'justify-content:center;border:3px solid white;box-shadow:0 3px 8px rgba(0,0,0,0.4)">' +
              '<span style="transform:rotate(45deg)">📍</span></div>',
        iconSize: [34, 34],
        iconAnchor: [17, 34]
    });
}

