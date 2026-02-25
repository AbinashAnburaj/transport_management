// ============================================================
// Cab Request - Client Script v3 (Field-safe, Portal + Desk)
// Place this in: transport_management/public/js/cab_request.js
// hooks.py: doctype_js = {"Cab Request": "public/js/cab_request.js"}
// After editing: bench build --app transport_management && bench restart
// ============================================================
 
// ── Safe field setter — silently skips fields that don't exist ──
function safe_set(frm, fieldname, value) {
    try {
        if (frm.fields_dict && frm.fields_dict[fieldname]) {
            frm.set_value(fieldname, value);
        } else {
            // Field not in form — set directly on doc so it's saved
            frm.doc[fieldname] = value;
        }
    } catch(e) {
        // Silently ignore
    }
}
 
// ── Role Check Helpers ───────────────────────────────────────
function user_has_role(role) {
    return frappe.user_roles && frappe.user_roles.includes(role);
}
 
function get_cab_user_type() {
    // Returns: 'employee', 'driver', 'manager', or 'other'
    if (user_has_role('Employee')) return 'employee';
    if (user_has_role('Driver'))   return 'driver';
    if (user_has_role('Manager'))  return 'manager';
    return 'other';
}
 
// ── Apply role-based restrictions to the map widget inputs ───
function apply_role_restrictions(frm) {
    const user_type = get_cab_user_type();
    const can_edit_location = (user_type === 'employee');
 
    if (!can_edit_location) {
        // Lock pickup & drop search inputs (read-only style)
        $('#cab-pickup-input, #cab-drop-input').each(function() {
            $(this)
                .prop('readonly', true)
                .css({
                    'background': '#f8f9fa',
                    'color': '#6c757d',
                    'cursor': 'not-allowed',
                    'border-color': '#e0e0e0'
                });
        });
 
        // Hide the suggestion dropdowns so nothing can be triggered
        $('#cab-pickup-sug, #cab-drop-sug').hide();
 
        // Hide Save/Load route buttons — only employee needs these
        $('#cab-save-loc-btn, #cab-load-loc-btn').hide();
 
        // Show a read-only notice
        if (!$('#cab-readonly-notice').length) {
            $('#cab-map-widget').prepend(`
                <div id="cab-readonly-notice" style="
                    background:#fff8e1; border-left:4px solid #f9a825;
                    border-radius:8px; padding:9px 14px; margin-bottom:10px;
                    font-size:12.5px; color:#795548; display:flex; align-items:center; gap:8px;">
                    🔒 <span>You have <strong>view-only</strong> access to location details.
                    Only the <strong>Employee</strong> can set pickup &amp; drop locations.</span>
                </div>
            `);
        }
    }
 
    // Also lock the underlying Frappe fields for non-employees
    // so they can't be edited even if someone bypasses the UI
    if (!can_edit_location) {
        if (frm.fields_dict['pickup_location']) {
            frm.set_df_property('pickup_location', 'read_only', 1);
        }
        if (frm.fields_dict['drop_location']) {
            frm.set_df_property('drop_location', 'read_only', 1);
        }
    }
}
 
frappe.ui.form.on('Cab Request', {
    onload: function(frm) {
        load_leaflet_then_init(frm);
    },
    refresh: function(frm) {
        if (window.L) {
            init_map(frm);
        } else {
            load_leaflet_then_init(frm);
        }
    },
    pickup_location: function(frm) {
        if (frm._drop_coords && frm.doc.pickup_location) {
            geocode_field(frm, 'pickup');
        }
    },
    drop_location: function(frm) {
        if (frm._pickup_coords && frm.doc.drop_location) {
            geocode_field(frm, 'drop');
        }
    }
});
 
// ── Load Leaflet CSS + JS ────────────────────────────────────
function load_leaflet_then_init(frm) {
    if (!document.getElementById('leaflet-css')) {
        $('<link id="leaflet-css" rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">')
            .appendTo('head');
    }
    if (!window.L) {
        $.getScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', function() {
            setTimeout(() => init_map(frm), 200);
        });
    } else {
        init_map(frm);
    }
}
 
// ── Main Init ────────────────────────────────────────────────
function init_map(frm) {
    if (frm._cab_map_done) {
        frm._map && frm._map.invalidateSize();
        return;
    }
 
    inject_styles();
 
    // Find the blank "map" area — the HTML field or the gap between Drop Location and Distance
    // Strategy: insert our UI after the drop_location field row
    const $drop_field = frm.get_field('drop_location') && $(frm.get_field('drop_location').wrapper);
    if (!$drop_field || !$drop_field.length) {
        console.warn('[CabMap] drop_location field not found, retrying...');
        setTimeout(() => init_map(frm), 600);
        return;
    }
 
    // Remove any existing map widget we inserted
    $('#cab-map-widget').remove();
 
    const map_html = `
    <div id="cab-map-widget" style="margin: 12px 0 4px;">
        <div style="display:flex; gap:10px; margin-bottom:8px; flex-wrap:wrap;">
            <div style="flex:1; min-width:200px; position:relative;">
                <div style="font-size:11px; font-weight:600; color:#6c757d; margin-bottom:4px;">📍 PICKUP LOCATION</div>
                <input id="cab-pickup-input" type="text" autocomplete="off" placeholder="Type to search pickup..."
                    style="width:100%;padding:9px 12px;border:1.5px solid #ced4da;border-radius:8px;font-size:13px;box-sizing:border-box;outline:none;"/>
                <div id="cab-pickup-sug" class="cab-sug-box"></div>
            </div>
            <div style="flex:1; min-width:200px; position:relative;">
                <div style="font-size:11px; font-weight:600; color:#6c757d; margin-bottom:4px;">🏁 DROP LOCATION</div>
                <input id="cab-drop-input" type="text" autocomplete="off" placeholder="Type to search drop..."
                    style="width:100%;padding:9px 12px;border:1.5px solid #ced4da;border-radius:8px;font-size:13px;box-sizing:border-box;outline:none;"/>
                <div id="cab-drop-sug" class="cab-sug-box"></div>
            </div>
        </div>
 
        <div id="cab-map-el" style="height:400px; border-radius:10px; border:1.5px solid #dee2e6; overflow:hidden; background:#e8eaed;"></div>
 
        <div id="cab-route-bar" style="display:none; margin-top:8px; padding:10px 16px;
            background:linear-gradient(135deg,#e8f4fd,#f0f9ff); border-radius:8px;
            border-left:4px solid #0d6efd; font-size:13px; color:#333; display:flex; gap:24px; flex-wrap:wrap;">
            <span>🛣️ <strong>Distance:</strong> <span id="cab-dist-val">—</span></span>
            <span>⏱️ <strong>Est. Travel Time:</strong> <span id="cab-eta-val">—</span></span>
        </div>

        <!-- ── NEW: Distance Validation Alert ── -->
        <div id="cab-dist-alert" style="display:none; margin-top:8px; padding:10px 16px;
            border-radius:8px; font-size:13px; font-weight:500;"></div>
 
        <div style="margin-top:6px; display:flex; gap:8px; flex-wrap:wrap;">
            <button id="cab-save-loc-btn" class="cab-btn" style="background:#198754;">💾 Save This Route</button>
            <button id="cab-load-loc-btn" class="cab-btn" style="background:#0d6efd;">📂 Load Saved Route</button>
        </div>

        <!-- ── ROUTE-BASED CAB FINDER (added below existing buttons) ── -->
        <div id="cab-route-finder-section" style="margin-top:14px; border-top:1.5px dashed #dee2e6; padding-top:14px; display:none;">
            <div style="font-size:13px; font-weight:600; color:#495057; margin-bottom:10px;">
                🚌 Available Cabs Matching Your Pickup Route
            </div>
            <div style="display:flex; gap:10px; flex-wrap:wrap; margin-bottom:10px;">
                <div style="flex:1; min-width:140px;">
                    <div style="font-size:11px; font-weight:600; color:#6c757d; margin-bottom:4px;">SHIFT TYPE</div>
                    <select id="cab-rf-shift" style="width:100%; padding:8px 10px; border:1.5px solid #ced4da; border-radius:7px; font-size:13px; background:white;">
                        <option value="">-- Select --</option>
                        <option value="Morning">Morning</option>
                        <option value="Evening">Evening</option>
                        <option value="Night">Night</option>
                        <option value="General">General</option>
                    </select>
                </div>
                <div style="flex:1; min-width:140px;">
                    <div style="font-size:11px; font-weight:600; color:#6c757d; margin-bottom:4px;">TRAVEL DATE</div>
                    <input id="cab-rf-date" type="date" style="width:100%; padding:8px 10px; border:1.5px solid #ced4da; border-radius:7px; font-size:13px; box-sizing:border-box;"/>
                </div>
                <div style="flex:1; min-width:120px;">
                    <div style="font-size:11px; font-weight:600; color:#6c757d; margin-bottom:4px;">SEARCH RADIUS (km)</div>
                    <input id="cab-rf-radius" type="number" value="1.5" min="0.5" max="10" step="0.5" style="width:100%; padding:8px 10px; border:1.5px solid #ced4da; border-radius:7px; font-size:13px; box-sizing:border-box;"/>
                </div>
                <div style="display:flex; align-items:flex-end; padding-bottom:1px;">
                    <button id="cab-rf-search-btn" style="background:#0d6efd; color:white; border:none; padding:8px 18px; border-radius:7px; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap;">
                        🔍 Search Cabs
                    </button>
                </div>
            </div>
            <div id="cab-rf-results"></div>
        </div>
        <!-- ── END ROUTE-BASED CAB FINDER ── -->

    </div>`;
 
    // Insert right after drop_location field
    $drop_field.after(map_html);
 
    // Hide the Frappe "Map" field (HTML type blank space)
    const map_field = frm.get_field('map');
    if (map_field) {
        $(map_field.wrapper).hide();
    }
 
    // Also hide original pickup/drop location text boxes (they are now replaced by our search inputs)
    // But keep them hidden only visually so frappe still tracks the values
    $(frm.get_field('pickup_location').wrapper).hide();
    $(frm.get_field('drop_location').wrapper).hide();
 
    // Init Leaflet
    const map = L.map('cab-map-el').setView([20.5937, 78.9629], 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>',
        maxZoom: 19
    }).addTo(map);
 
    frm._map = map;
    frm._markers = {};
    frm._route_layer = null;
    frm._pickup_coords = null;
    frm._drop_coords = null;
    frm._cab_map_done = true;
    frm._route_distance_km = null; // ── NEW: stores parsed km float
 
    // Pre-fill from existing doc values
    if (frm.doc.pickup_location) {
        $('#cab-pickup-input').val(frm.doc.pickup_location);
        geocode_and_place(frm, frm.doc.pickup_location, 'pickup');
    }
    if (frm.doc.drop_location) {
        $('#cab-drop-input').val(frm.doc.drop_location);
        geocode_and_place(frm, frm.doc.drop_location, 'drop');
    }
 
    // Bind search inputs
    bind_search('cab-pickup-input', 'cab-pickup-sug', function(result) {
        frm._pickup_coords = [parseFloat(result.lat), parseFloat(result.lon)];
        place_marker(frm, 'pickup', frm._pickup_coords, result.display_name);
        safe_set(frm, 'pickup_location', result.display_name);
        safe_set(frm, 'pickup_latitude', result.lat);
        safe_set(frm, 'pickup_longitude', result.lon);
        try_draw_route(frm);
    });
 
    bind_search('cab-drop-input', 'cab-drop-sug', function(result) {
        frm._drop_coords = [parseFloat(result.lat), parseFloat(result.lon)];
        place_marker(frm, 'drop', frm._drop_coords, result.display_name);
        safe_set(frm, 'drop_location', result.display_name);
        try_draw_route(frm);
    });
 
    // Save/Load buttons
    $('#cab-save-loc-btn').on('click', () => save_route_dialog(frm));
    $('#cab-load-loc-btn').on('click', () => load_route_dialog(frm));

    // ── Wire Find Cab by Route section ──────────────────────────────────────────
    // Show the section only for employees (non-manager, non-driver)
    const _user_type = get_cab_user_type();
    if (_user_type === 'employee') {
        $('#cab-route-finder-section').show();
        // Set today as default travel date
        const _today = new Date().toISOString().split('T')[0];
        $('#cab-rf-date').val(_today);
    }

    $('#cab-rf-search-btn').on('click', function() {
        _rf_search_cabs(frm);
    });
 
    // ── Apply role restrictions AFTER widget is fully built ──
    apply_role_restrictions(frm);
}
 
// ── Styles ───────────────────────────────────────────────────
function inject_styles() {
    if (document.getElementById('cab-map-styles')) return;
    $('<style id="cab-map-styles">').text(`
        .cab-sug-box {
            display:none; position:absolute; top:calc(100% + 2px); left:0; right:0;
            background:#fff; border:1px solid #ced4da; border-radius:8px;
            max-height:210px; overflow-y:auto; z-index:99999;
            box-shadow:0 6px 18px rgba(0,0,0,0.12);
        }
        .cab-sug-item {
            padding:9px 12px; font-size:13px; cursor:pointer;
            border-bottom:1px solid #f0f0f0; line-height:1.4;
            transition: background 0.12s;
        }
        .cab-sug-item:hover { background:#f0f7ff; }
        .cab-sug-item:last-child { border-bottom:none; }
        .cab-btn {
            color:#fff; border:none; padding:7px 14px; border-radius:7px;
            font-size:12px; cursor:pointer; font-weight:500;
            transition: opacity 0.15s;
        }
        .cab-btn:hover { opacity:0.85; }
    `).appendTo('head');
}
 
// ── Autocomplete Search ───────────────────────────────────────
function bind_search(input_id, sug_id, on_select) {
    let timer;
    $('#' + input_id).on('input', function() {
        // Block input if field is read-only (non-employee)
        if ($(this).prop('readonly')) return;
 
        clearTimeout(timer);
        const q = $(this).val().trim();
        if (q.length < 3) { $('#' + sug_id).hide().empty(); return; }
        timer = setTimeout(() => {
            fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=6&addressdetails=1`,
                { headers: { 'Accept-Language': 'en' } })
                .then(r => r.json())
                .then(results => {
                    const $box = $('#' + sug_id).empty();
                    if (!results.length) { $box.hide(); return; }
                    results.forEach(r => {
                        $('<div class="cab-sug-item">').text(r.display_name).appendTo($box)
                            .on('click', function() {
                                $('#' + input_id).val(r.display_name);
                                $box.hide().empty();
                                on_select(r);
                            });
                    });
                    $box.show();
                })
                .catch(() => { });
        }, 420);
    });
 
    $(document).on('click', function(e) {
        if (!$(e.target).is('#' + input_id)) $('#' + sug_id).hide();
    });
}
 
// ── Geocode + Place from text ─────────────────────────────────
function geocode_and_place(frm, text, type) {
    fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(text)}&format=json&limit=1`,
        { headers: { 'Accept-Language': 'en' } })
        .then(r => r.json())
        .then(data => {
            if (data && data[0]) {
                const coords = [parseFloat(data[0].lat), parseFloat(data[0].lon)];
                if (type === 'pickup') frm._pickup_coords = coords;
                else frm._drop_coords = coords;
                place_marker(frm, type, coords, data[0].display_name);
                try_draw_route(frm);
            }
        }).catch(() => { });
}
 
// ── Geocode from form field value ────────────────────────────
function geocode_field(frm, type) {
    const val = type === 'pickup' ? frm.doc.pickup_location : frm.doc.drop_location;
    if (val) geocode_and_place(frm, val, type);
}
 
// ── Place Marker ─────────────────────────────────────────────
function place_marker(frm, type, coords, label) {
    if (!frm._map) return;
    if (frm._markers[type]) frm._map.removeLayer(frm._markers[type]);
 
    const color = type === 'pickup' ? '#198754' : '#dc3545';
    const icon = L.divIcon({
        html: `<div style="width:18px;height:18px;background:${color};border-radius:50%;
               border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.35);"></div>`,
        iconSize: [24, 24], iconAnchor: [12, 12], className: ''
    });
 
    frm._markers[type] = L.marker(coords, { icon })
        .addTo(frm._map)
        .bindPopup(`<b>${type === 'pickup' ? '📍 Pickup' : '🏁 Drop'}</b><br><small>${label}</small>`)
        .openPopup();
 
    // Fit both markers
    const pts = Object.values(frm._markers).map(m => m.getLatLng());
    if (pts.length >= 2) {
        frm._map.fitBounds(L.latLngBounds(pts).pad(0.2));
    } else {
        frm._map.setView(coords, 14);
    }
}
 
// ── NEW: Show/Hide Distance Validation Alert ─────────────────
function show_dist_alert(type, km) {
    const $alert = $('#cab-dist-alert');
    if (type === 'too_short') {
        $alert.css({
            'display': 'flex',
            'align-items': 'center',
            'gap': '8px',
            'background': '#fff3cd',
            'border-left': '4px solid #ffc107',
            'color': '#856404'
        }).html(`⚠️ <span>Distance is <strong>${km} km</strong> — too short. Minimum allowed distance is <strong>3 km</strong>. Please choose locations farther apart.</span>`);
    } else if (type === 'too_long') {
        $alert.css({
            'display': 'flex',
            'align-items': 'center',
            'gap': '8px',
            'background': '#f8d7da',
            'border-left': '4px solid #dc3545',
            'color': '#842029'
        }).html(`🚫 <span>Distance is <strong>${km} km</strong> — too far. Maximum allowed distance is <strong>70 km</strong>. Please choose closer locations.</span>`);
    } else {
        $alert.hide().empty();
    }
}

// ── NEW: Send Booking Notification via Frappe ─────────────────
function send_booking_notification(frm, km, eta) {
    // Send a Frappe notification to relevant roles (Manager, Driver)
    frappe.call({
        method: 'frappe.client.insert',
        args: {
            doc: {
                doctype: 'Notification Log',
                subject: '🚖 New Cab Booking Request',
                email_content: `
                    <p>A new cab booking has been submitted.</p>
                    <ul>
                        <li><strong>Employee:</strong> ${frappe.session.user}</li>
                        <li><strong>Pickup:</strong> ${frm.doc.pickup_location || '—'}</li>
                        <li><strong>Drop:</strong> ${frm.doc.drop_location || '—'}</li>
                        <li><strong>Distance:</strong> ${km} km</li>
                        <li><strong>Est. Travel Time:</strong> ${eta}</li>
                        <li><strong>Document:</strong> ${frm.doc.name || 'New'}</li>
                    </ul>
                `,
                for_user: frappe.session.user,
                type: 'Alert',
                document_type: 'Cab Request',
                document_name: frm.doc.name || ''
            }
        },
        callback: function(r) {
            if (!r.exc) {
                frappe.show_alert({
                    message: '🔔 Booking notification sent to Manager & Driver!',
                    indicator: 'green'
                }, 5);
            }
        },
        error: function() {
            // Fallback: show a toast alert if Notification Log insert fails
            frappe.show_alert({
                message: '🚖 Cab booked! Pickup: ' + (frm.doc.pickup_location || '—') +
                         ' → Drop: ' + (frm.doc.drop_location || '—') +
                         ' | Distance: ' + km + ' km | ETA: ' + eta,
                indicator: 'blue'
            }, 8);
        }
    });

    // Also send real-time desk notification
    frappe.realtime.publish('cab_booking_alert', {
        user: frappe.session.user,
        pickup: frm.doc.pickup_location,
        drop: frm.doc.drop_location,
        distance: km + ' km',
        eta: eta,
        docname: frm.doc.name || 'New'
    });
}

// ── Draw Route ────────────────────────────────────────────────
function try_draw_route(frm) {
    if (!frm._pickup_coords || !frm._drop_coords) return;
    const [plat, plng] = frm._pickup_coords;
    const [dlat, dlng] = frm._drop_coords;
    const url = `https://router.project-osrm.org/route/v1/driving/${plng},${plat};${dlng},${dlat}?overview=full&geometries=geojson`;
 
    fetch(url)
        .then(r => r.json())
        .then(data => {
            if (!data.routes || !data.routes.length) return;
            const route = data.routes[0];
            const km = parseFloat((route.distance / 1000).toFixed(1));
            const total_min = Math.round(route.duration / 60);
            const h = Math.floor(total_min / 60), m = total_min % 60;
            const eta = h > 0 ? `${h}h ${m}m` : `${m} min`;

            // ── NEW: Store parsed km on frm for validation ──
            frm._route_distance_km = km;
 
            // Update the bar UI
            $('#cab-dist-val').text(km + ' km');
            $('#cab-eta-val').text(eta);
            $('#cab-route-bar').css('display', 'flex');

            // ── NEW: Distance Validation ──────────────────────
            if (km < 3) {
                show_dist_alert('too_short', km);
                // Clear the distance/eta fields so invalid data isn't saved
                safe_set(frm, 'distance', '');
                if (frm.fields_dict && frm.fields_dict['estimated_arrival_time']) {
                    safe_set(frm, 'estimated_arrival_time', '');
                } else if (frm.fields_dict && frm.fields_dict['estimated_time']) {
                    safe_set(frm, 'estimated_time', '');
                }
                // Draw route in red to visually indicate invalid
                if (frm._route_layer) frm._map.removeLayer(frm._route_layer);
                frm._route_layer = L.geoJSON(route.geometry, {
                    style: { color: '#ffc107', weight: 5, opacity: 0.85 }
                }).addTo(frm._map);
                frm._map.fitBounds(frm._route_layer.getBounds().pad(0.15));
                return; // Stop — don't save fields
            } else if (km > 70) {
                show_dist_alert('too_long', km);
                safe_set(frm, 'distance', '');
                if (frm.fields_dict && frm.fields_dict['estimated_arrival_time']) {
                    safe_set(frm, 'estimated_arrival_time', '');
                } else if (frm.fields_dict && frm.fields_dict['estimated_time']) {
                    safe_set(frm, 'estimated_time', '');
                }
                // Draw route in red to visually indicate invalid
                if (frm._route_layer) frm._map.removeLayer(frm._route_layer);
                frm._route_layer = L.geoJSON(route.geometry, {
                    style: { color: '#dc3545', weight: 5, opacity: 0.85 }
                }).addTo(frm._map);
                frm._map.fitBounds(frm._route_layer.getBounds().pad(0.15));
                return; // Stop — don't save fields
            } else {
                // ✅ Valid distance — clear any previous alert
                show_dist_alert('clear');
            }
            // ── END Distance Validation ───────────────────────
 
            // Safe-set fields — works even if field name differs in your DocType
            safe_set(frm, 'distance', km + ' km');
            // Try both common field names for ETA
            if (frm.fields_dict && frm.fields_dict['estimated_arrival_time']) {
                safe_set(frm, 'estimated_arrival_time', eta);
            } else if (frm.fields_dict && frm.fields_dict['estimated_time']) {
                safe_set(frm, 'estimated_time', eta);
            } else {
                // Just store on doc directly
                frm.doc['estimated_arrival_time'] = eta;
            }
 
            if (frm._route_layer) frm._map.removeLayer(frm._route_layer);
            frm._route_layer = L.geoJSON(route.geometry, {
                style: { color: '#0d6efd', weight: 5, opacity: 0.85 }
            }).addTo(frm._map);
 
            frm._map.fitBounds(frm._route_layer.getBounds().pad(0.15));

            // ── NEW: Auto-send notification when valid route is confirmed ──
            // Only trigger notification when both locations are freshly set (not on page load)
            if (frm._notify_on_route) {
                send_booking_notification(frm, km, eta);
                frm._notify_on_route = false;
            }
        })
        .catch(err => console.warn('[CabMap] Route error:', err));
}

// ── NEW: Override frm.save to validate distance before saving ─
// Patch the save button to block if distance is invalid
frappe.ui.form.on('Cab Request', {
    before_save: function(frm) {
        const km = frm._route_distance_km;

        // Only validate if both locations are set and a route was computed
        if (frm.doc.pickup_location && frm.doc.drop_location && km !== null && km !== undefined) {
            if (km < 3) {
                frappe.throw(`❌ Cannot save: Distance is ${km} km. Minimum allowed distance is 3 km.`);
            }
            if (km > 70) {
                frappe.throw(`❌ Cannot save: Distance is ${km} km. Maximum allowed distance is 70 km.`);
            }
        }
    },
    after_save: function(frm) {
        // ── NEW: Send notification after successful save ──
        const km = frm._route_distance_km;
        if (km && km >= 3 && km <= 70) {
            const eta_el = document.getElementById('cab-eta-val');
            const eta = eta_el ? eta_el.textContent : '—';
            send_booking_notification(frm, km, eta);
        }
    }
});
 
// ── Save Route ───────────────────────────────────────────────
function save_route_dialog(frm) {
    const d = new frappe.ui.Dialog({
        title: '💾 Save This Route',
        fields: [
            { fieldname: 'rname', fieldtype: 'Data', label: 'Route Label (e.g. "Home → Office")', reqd: 1 },
            { fieldname: 'pickup', fieldtype: 'Data', label: 'Pickup', default: frm.doc.pickup_location, read_only: 1 },
            { fieldname: 'drop', fieldtype: 'Data', label: 'Drop', default: frm.doc.drop_location, read_only: 1 }
        ],
        primary_action_label: 'Save',
        primary_action(v) {
            if (!frm.doc.pickup_location || !frm.doc.drop_location) {
                frappe.show_alert({ message: 'Set pickup & drop first!', indicator: 'orange' }); return;
            }

            // ── NEW: Block saving route if distance is invalid ──
            const km = frm._route_distance_km;
            if (km !== null && km !== undefined) {
                if (km < 3) {
                    frappe.show_alert({ message: `⚠️ Cannot save: Distance ${km} km is below the 3 km minimum.`, indicator: 'orange' });
                    return;
                }
                if (km > 70) {
                    frappe.show_alert({ message: `🚫 Cannot save: Distance ${km} km exceeds the 70 km maximum.`, indicator: 'red' });
                    return;
                }
            }

            const key = 'cab_saved_routes_' + frappe.session.user;
            const list = JSON.parse(localStorage.getItem(key) || '[]');
            list.push({ label: v.rname, pickup: frm.doc.pickup_location, drop: frm.doc.drop_location });
            localStorage.setItem(key, JSON.stringify(list));
            frappe.show_alert({ message: `✅ Route "${v.rname}" saved!`, indicator: 'green' }, 4);
            d.hide();
        }
    });
    d.show();
}
 
// ── Load Route ───────────────────────────────────────────────
function load_route_dialog(frm) {
    const key = 'cab_saved_routes_' + frappe.session.user;
    const list = JSON.parse(localStorage.getItem(key) || '[]');
    if (!list.length) { frappe.msgprint('No saved routes yet. Save one first!'); return; }
 
    const d = new frappe.ui.Dialog({
        title: '📂 Load Saved Route',
        fields: [{
            fieldname: 'sel', fieldtype: 'Select', label: 'Choose a route', reqd: 1,
            options: list.map(r => r.label).join('\n')
        }],
        primary_action_label: 'Load',
        primary_action(v) {
            const found = list.find(r => r.label === v.sel);
            if (found) {
                safe_set(frm, 'pickup_location', found.pickup);
                safe_set(frm, 'drop_location', found.drop);
                $('#cab-pickup-input').val(found.pickup);
                $('#cab-drop-input').val(found.drop);
                geocode_and_place(frm, found.pickup, 'pickup');
                geocode_and_place(frm, found.drop, 'drop');
                frappe.show_alert({ message: `Loaded: ${found.label}`, indicator: 'blue' }, 3);
            }
            d.hide();
        }
    });
    d.show();
}


// ============================================================
//  ROUTE-BASED CAB FINDER FUNCTIONS
//  Added below — all existing code above is untouched
//  Uses frm._pickup_coords already set by your existing map code
// ============================================================

var _rf_route_layers = [];   // Leaflet layers for matched cab routes
var _rf_cabs_data    = [];   // Last search results
var _RF_COLORS = ['#0d6efd','#198754','#dc3545','#fd7e14','#6f42c1','#0dcaf0'];

// ── Search cabs via backend ──────────────────────────────────
function _rf_search_cabs(frm) {
    // Use the pickup coords already set by your existing map code
    if (!frm._pickup_coords) {
        frappe.show_alert({ message: '📍 Please set your Pickup Location on the map first.', indicator: 'orange' }, 5);
        return;
    }

    const shift = $('#cab-rf-shift').val();
    const date  = $('#cab-rf-date').val();
    const radius = parseFloat($('#cab-rf-radius').val()) || 1.5;

    if (!shift) { frappe.show_alert({ message: 'Please select a Shift Type.', indicator: 'orange' }, 4); return; }
    if (!date)  { frappe.show_alert({ message: 'Please select a Travel Date.', indicator: 'orange' }, 4); return; }

    const $results = $('#cab-rf-results');
    $results.html('<div style="text-align:center;padding:20px;color:#0d6efd;font-size:13px;">🔍 Searching cabs near your pickup…</div>');

    // Clear previous route overlays from the existing map
    _rf_clear_route_layers(frm);

    frappe.call({
        method: 'transport_management.transport_management.doctype.cab_request.cab_request.find_matching_cabs',
        args: {
            employee_lat:  frm._pickup_coords[0],
            employee_lng:  frm._pickup_coords[1],
            travel_date:   date,
            shift_type:    shift,
            threshold_km:  radius
        },
        callback: function(r) {
            if (r.exc) {
                $results.html('<div style="color:#dc3545;padding:12px;font-size:13px;">⚠️ Error fetching cabs. Please check console.</div>');
                return;
            }
            _rf_cabs_data = r.message || [];
            _rf_render_cards(frm, _rf_cabs_data);
            _rf_draw_routes(frm, _rf_cabs_data);
        }
    });
}

// ── Render cab result cards ───────────────────────────────────
function _rf_render_cards(frm, cabs) {
    const $results = $('#cab-rf-results');

    if (!cabs.length) {
        $results.html(
            '<div style="background:#fff8e1;border-left:4px solid #ffc107;border-radius:8px;' +
            'padding:12px 16px;font-size:13px;color:#795548;margin-top:4px;">' +
            '😔 No cabs found near your pickup location. Try increasing the search radius or contact HR.</div>'
        );
        return;
    }

    var html = '<div style="font-size:12.5px;color:#6c757d;margin-bottom:8px;font-weight:500;">' +
               '✅ ' + cabs.length + ' cab(s) found near your pickup:</div>';

    cabs.forEach(function(cab, idx) {
        var color   = _RF_COLORS[idx % _RF_COLORS.length];
        var pct     = Math.round((cab.booked_seats / cab.total_seats) * 100);
        var aclr    = cab.available_seats > 3 ? '#155724' : '#856404';
        var abg     = cab.available_seats > 3 ? '#d4edda'  : '#fff3cd';
        var bclr    = cab.available_seats > 3 ? '#28a745'  : '#ffc107';
        var stoptime = cab.nearest_pickup_time ? ' @ ' + cab.nearest_pickup_time : '';

        html +=
            '<div style="border:1.5px solid #dee2e6;border-radius:10px;padding:13px;margin-bottom:10px;' +
            'background:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.06);" ' +
            'onmouseover="this.style.borderColor=\'' + color + '\'" ' +
            'onmouseout="this.style.borderColor=\'#dee2e6\'">' +

            // Header row
            '<div style="display:flex;align-items:start;gap:10px;margin-bottom:10px;">' +
            '<div style="background:' + color + ';color:white;border-radius:6px;padding:4px 10px;' +
            'font-size:11px;font-weight:700;flex-shrink:0;">#' + (idx+1) + '</div>' +
            '<div style="flex:1;">' +
            '<div style="font-size:14px;font-weight:600;color:#1a1a2e;">🚌 ' + cab.route_name + '</div>' +
            '<div style="font-size:11.5px;color:#6c757d;margin-top:2px;">' + cab.start_location + ' → ' + cab.end_location + '</div>' +
            '</div>' +
            '<div style="background:' + abg + ';color:' + aclr + ';border-radius:8px;text-align:center;padding:5px 10px;flex-shrink:0;">' +
            '<div style="font-size:18px;font-weight:700;line-height:1;">' + cab.available_seats + '</div>' +
            '<div style="font-size:10px;margin-top:1px;">seats left</div></div>' +
            '</div>' +

            // Details grid
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:5px 16px;font-size:12px;color:#495057;margin-bottom:10px;">' +
            '<div>🚗 <b>' + (cab.license_plate || cab.vehicle) + '</b></div>' +
            '<div>🕐 Shift: <b>' + cab.shift_time + '</b></div>' +
            '<div>👤 ' + (cab.driver_name || 'Driver TBD') + '</div>' +
            '<div>📏 <b>' + cab.distance_from_route + ' km</b> from route</div>' +
            '<div>🛑 Stop: <b>' + (cab.nearest_stop || 'On Route') + '</b>' + stoptime + '</div>' +
            '<div>📞 ' + (cab.driver_contact || '—') + '</div>' +
            '</div>' +

            // Seat bar
            '<div style="background:#f1f3f5;border-radius:4px;height:5px;margin-bottom:4px;">' +
            '<div style="background:' + bclr + ';height:5px;border-radius:4px;width:' + pct + '%;transition:width .4s;"></div></div>' +
            '<div style="font-size:11px;color:#adb5bd;margin-bottom:10px;">' + cab.booked_seats + ' of ' + cab.total_seats + ' seats booked</div>' +

            // Action buttons
            '<div style="display:flex;gap:8px;">' +
            '<button class="cab-btn" onclick="_rf_zoom_route(\'' + cab.route + '\')" ' +
            'style="flex:1;background:#6c757d;font-size:12px;">🗺 View on Map</button>' +
            '<button class="cab-btn" onclick="_rf_book_cab(\'' + frm.doc.name + '\',\'' + cab.route + '\',\'' +
            cab.route_name + '\',\'' + (cab.nearest_stop || '') + '\',' +
            (cab.nearest_stop_lat || null) + ',' + (cab.nearest_stop_lng || null) + ',\'' +
            (cab.nearest_pickup_time || '') + '\',' + cab.distance_from_route + ')" ' +
            'style="flex:2;background:' + color + ';font-size:12px;">✅ Book This Cab</button>' +
            '</div></div>';
    });

    $results.html(html);
}

// ── Draw matched cab routes on the EXISTING frm._map ─────────
function _rf_draw_routes(frm, cabs) {
    if (!frm._map) return;

    cabs.forEach(function(cab, idx) {
        var color = _RF_COLORS[idx % _RF_COLORS.length];
        var wps   = (cab.waypoints || []).slice().sort(function(a,b){ return a.sequence - b.sequence; });
        if (wps.length < 2) return;

        var path = wps.map(function(wp){ return [wp.latitude, wp.longitude]; });

        // Dashed polyline for cab route (distinct from the employee's OSRM route in solid blue)
        var poly = L.polyline(path, {
            color: color, weight: 4, opacity: 0.85,
            dashArray: '8, 5'
        }).addTo(frm._map)
          .bindPopup('<b>' + cab.route_name + '</b><br><small>' + cab.start_location + ' → ' + cab.end_location + '</small>');

        _rf_route_layers.push(poly);

        // Stop markers
        wps.forEach(function(wp) {
            if (!wp.latitude || !wp.longitude) return;
            var dot = L.circleMarker([wp.latitude, wp.longitude], {
                radius: 6, color: '#fff', fillColor: color,
                fillOpacity: 1, weight: 2
            }).addTo(frm._map)
              .bindPopup('<b>' + (wp.stop_name || '') + '</b>' + (wp.pickup_time ? '<br>⏰ ' + wp.pickup_time : ''));
            _rf_route_layers.push(dot);
        });
    });
}

function _rf_clear_route_layers(frm) {
    _rf_route_layers.forEach(function(l) { if (frm._map) frm._map.removeLayer(l); });
    _rf_route_layers = [];
}

// ── Zoom to a specific cab route on the map ───────────────────
window._rf_zoom_route = function(route_name) {
    var cab = (_rf_cabs_data || []).find(function(c){ return c.route === route_name; });
    var frm = cur_frm;
    if (!cab || !frm._map) return;
    var wps = (cab.waypoints || []).filter(function(w){ return w.latitude && w.longitude; });
    if (!wps.length) return;
    var bounds = L.latLngBounds(wps.map(function(w){ return [w.latitude, w.longitude]; }));
    frm._map.fitBounds(bounds, { padding: [40, 40] });
};

// ── Book cab ─────────────────────────────────────────────────
window._rf_book_cab = function(
    cab_request_name, route_name, route_display,
    nearest_stop, nearest_stop_lat, nearest_stop_lng,
    nearest_pickup_time, distance_from_route
) {
    var frm = cur_frm;
    frappe.confirm(
        'Book <b>' + route_display + '</b>?<br>Nearest stop: <b>' + (nearest_stop || 'On Route') + '</b>' +
        (nearest_pickup_time ? ' @ ' + nearest_pickup_time : ''),
        function() {
            frappe.call({
                method: 'transport_management.transport_management.doctype.cab_request.cab_request.book_route_cab',
                args: {
                    cab_request_name:    cab_request_name,
                    route_name:          route_name,
                    pickup_lat:          frm._pickup_coords ? frm._pickup_coords[0] : null,
                    pickup_lng:          frm._pickup_coords ? frm._pickup_coords[1] : null,
                    pickup_address:      frm.doc.pickup_location || '',
                    nearest_stop:        nearest_stop,
                    nearest_stop_lat:    nearest_stop_lat,
                    nearest_stop_lng:    nearest_stop_lng,
                    nearest_pickup_time: nearest_pickup_time,
                    distance_from_route: distance_from_route
                },
                freeze: true,
                freeze_message: 'Booking your cab…',
                callback: function(r) {
                    if (r.message && r.message.status === 'success') {
                        frappe.show_alert({ message: '🎉 ' + r.message.message, indicator: 'green' }, 6);
                        cur_frm.reload_doc();
                    }
                }
            });
        }
    );
};

