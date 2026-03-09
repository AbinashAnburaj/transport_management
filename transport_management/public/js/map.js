// ============================================================
// Cab Request - Client Script v6 (Fixed)
// transport_management/public/js/cab_request.js
// hooks.py: doctype_js = {"Cab Request": "public/js/cab_request.js"}
// After editing: bench build --app transport_management && bench restart
// ============================================================

// ── Safe field setter ──────────────────────────────────────────────────────
function safe_set(frm, fieldname, value) {
    try {
        if (frm.fields_dict && frm.fields_dict[fieldname]) {
            frm.set_value(fieldname, value);
        } else {
            frm.doc[fieldname] = value;
        }
    } catch(e) { /* silently ignore */ }
}

// ── Role Check Helpers ─────────────────────────────────────────────────────
function user_has_role(role) {
    return frappe.user_roles && frappe.user_roles.includes(role);
}

function get_cab_user_type() {
    if (user_has_role('System Manager') || user_has_role('Fleet Manager')) return 'manager';
    if (user_has_role('Driver')) return 'driver';
    if (user_has_role('Employee')) return 'employee';
    return 'other';
}

// ── Hide default Save button for employees ─────────────────────────────────
function _hide_save_button(frm) {
    const ut = get_cab_user_type();
    // Employees don't need the Save button — booking auto-saves
    if (ut === 'employee') {
        frm.page.btn_primary && frm.page.btn_primary.hide();
        // Also hide via CSS as fallback
        if (!document.getElementById('cab-hide-save-style')) {
            $('<style id="cab-hide-save-style">').text(`
                .btn-primary[data-label="Save"],
                [data-label="Save"].btn-primary { display: none !important; }
            `).appendTo('head');
        }
    }
}

// ── Apply role-based restrictions ─────────────────────────────────────────
function apply_role_restrictions(frm) {
    const user_type = get_cab_user_type();
    _toggle_driver_only_fields(frm, user_type);

    if (user_type === 'manager') {
        return;
    }

    if (user_type === 'driver') {
        $('#cab-pickup-input, #cab-drop-input').each(function() {
            $(this).prop('readonly', true).css({
                'background': '#f8f9fa', 'color': '#6c757d',
                'cursor': 'not-allowed', 'border-color': '#e0e0e0'
            });
        });
        $('#cab-pickup-sug, #cab-drop-sug, #cab-save-loc-btn, #cab-load-loc-btn').hide();
        $('#cab-route-finder-section').hide();
        if (!$('#cab-readonly-notice').length) {
            $('#cab-map-widget').prepend(`
                <div id="cab-readonly-notice" style="background:#fff8e1;border-left:4px solid #f9a825;
                    border-radius:8px;padding:9px 14px;margin-bottom:10px;font-size:12.5px;
                    color:#795548;display:flex;align-items:center;gap:8px;">
                    <span>🚗 Driver view — location fields are read-only.</span>
                </div>`);
        }
        if (frm.fields_dict['pickup_location']) frm.set_df_property('pickup_location', 'read_only', 1);
        if (frm.fields_dict['drop_location'])   frm.set_df_property('drop_location', 'read_only', 1);
        _show_driver_map_panel(frm);
        return;
    }

    if (user_type === 'employee') {
        if (['Assigned', 'In Trip'].includes(frm.doc.status) && frm.doc.assigned_route) {
            setTimeout(function() { _show_employee_route_tracker(frm); }, 600);
        }
        return;
    }

    // Other: full readonly
    $('#cab-pickup-input, #cab-drop-input').each(function() {
        $(this).prop('readonly', true).css({
            'background': '#f8f9fa', 'color': '#6c757d',
            'cursor': 'not-allowed', 'border-color': '#e0e0e0'
        });
    });
    $('#cab-pickup-sug, #cab-drop-sug, #cab-save-loc-btn, #cab-load-loc-btn').hide();
    if (frm.fields_dict['pickup_location']) frm.set_df_property('pickup_location', 'read_only', 1);
    if (frm.fields_dict['drop_location'])   frm.set_df_property('drop_location', 'read_only', 1);
}

// ── Show OTP execution fields only for Driver ─────────────────────────────
function _toggle_driver_only_fields(frm, user_type) {
    const show_for_driver = (user_type === 'driver');
    ['enter_otp', 'verify'].forEach(function(fieldname) {
        if (frm.fields_dict && frm.fields_dict[fieldname]) {
            frm.set_df_property(fieldname, 'hidden', show_for_driver ? 0 : 1);
        }
    });
}

// ── Main Form Events ───────────────────────────────────────────────────────
frappe.ui.form.on('Cab Request', {
    onload: function(frm) {
        _auto_fetch_employee_details(frm);

        const _ut = get_cab_user_type();
        if (_ut === 'employee' || _ut === 'manager') {
            ['employee_id', 'employee_name', 'department', 'contact_no'].forEach(function(f) {
                if (frm.fields_dict[f]) frm.set_df_property(f, 'read_only', 0);
            });
        }

        load_leaflet_then_init(frm);
        _hide_save_button(frm);
    },
    refresh: function(frm) {
        _hide_save_button(frm);

        if (window.L) {
            init_map(frm);
        } else {
            load_leaflet_then_init(frm);
        }

        _maybe_show_booking_card(frm);
        _setup_action_buttons(frm);
    },
    pickup_location: function(frm) {
        if (frm._drop_coords && frm.doc.pickup_location) geocode_field(frm, 'pickup');
    },
    drop_location: function(frm) {
        if (frm._pickup_coords && frm.doc.drop_location) geocode_field(frm, 'drop');
    },
    before_save: function(frm) {
        const km = frm._route_distance_km;
        if (frm.doc.pickup_location && frm.doc.drop_location && km !== null && km !== undefined) {
            if (km < 3)  frappe.throw(`⚠️ Cannot save: Distance is ${km} km. Minimum allowed is 3 km.`);
            if (km > 70) frappe.throw(`⚠️ Cannot save: Distance is ${km} km. Maximum allowed is 70 km.`);
        }
    },
    after_save: function(frm) {
        const km = frm._route_distance_km;
        if (km && km >= 3 && km <= 70) {
            const eta_el = document.getElementById('cab-eta-val');
            const eta = eta_el ? eta_el.textContent : '';
            send_booking_notification(frm, km, eta);
        }
        // Re-hide save button after save
        _hide_save_button(frm);
    }
});

// ── Auto-fetch employee details ────────────────────────────────────────────
function _auto_fetch_employee_details(frm) {
    const user_type = get_cab_user_type();
    if (user_type !== 'employee' && user_type !== 'manager') return;
    if (user_type === 'manager' && frm.doc.employee_id) return;

    frappe.call({
        method: 'transport_management.transport_management.doctype.cab_request.cab_request.get_employee_basic_details',
        callback: function(r) {
            if (!r.message) return;
            const emp = r.message;
            if (!frm.doc.employee_id)   safe_set(frm, 'employee_id',   emp.name);
            if (!frm.doc.employee_name) safe_set(frm, 'employee_name', emp.employee_name);
            if (!frm.doc.department)    safe_set(frm, 'department',    emp.department);
            if (!frm.doc.contact_no)    safe_set(frm, 'contact_no',    emp.cell_number || emp.personal_email);
        }
    });
}

// ── Setup Action Buttons ───────────────────────────────────────────────────
function _setup_action_buttons(frm) {
    const user_type = get_cab_user_type();

    // OTP only visible to employee and fleet manager (NOT driver)
    if ((user_type === 'employee' || user_type === 'manager') && frm.doc.status === 'Assigned' && !frm.is_new()) {
        frm.add_custom_button('🔑 View Trip OTP', function() {
            frappe.call({
                method: 'transport_management.transport_management.doctype.cab_request.cab_request.get_otp',
                args: { docname: frm.doc.name },
                callback: function(r) {
                    if (r.message && r.message.otp) {
                        _show_otp_modal(r.message.otp, frm.doc.assigned_route || 'Your Route', frm.doc.name);
                    } else {
                        frappe.msgprint({ title: 'No OTP', message: 'OTP not found.', indicator: 'orange' });
                    }
                }
            });
        });
    }

    // Driver: Verify OTP & Start Trip (status Assigned)
    if (user_type === 'driver' && frm.doc.status === 'Assigned' && !frm.is_new()) {
        frm.add_custom_button('🔐 Verify OTP & Start Trip', function() {
            _driver_verify_otp_dialog(frm);
        }, 'Actions').addClass('btn-primary');
    }

    // Driver: Complete Trip (status In Trip)
    if (user_type === 'driver' && frm.doc.status === 'In Trip' && !frm.is_new()) {
        frm.add_custom_button('✅ Complete Trip', function() {
            frappe.confirm('Mark this trip as Completed?', function() {
                frappe.call({
                    method: 'transport_management.transport_management.doctype.cab_request.cab_request.driver_complete_trip',
                    args: { docname: frm.doc.name },
                    callback: function(r) {
                        frappe.show_alert({ message: '✅ Trip marked as Completed!', indicator: 'green' }, 4);
                        frm.reload_doc();
                    }
                });
            });
        }, 'Actions').addClass('btn-success');
    }
}

// ── Booking Card ───────────────────────────────────────────────────────────
// FIX: Removed the assigned_route/assigned_cab gate so employees always see
//      the card when status is Assigned/In Trip/Completed/Cancelled.
//      Uses get_booking_display_details to fetch ALL trip details in one call
//      including the human-readable route name, vehicle, driver, shift_time.
function _maybe_show_booking_card(frm) {
    if (!['Assigned', 'In Trip', 'Completed', 'Cancelled'].includes(frm.doc.status)) return;
    if (frm.is_new()) return;
    const ut = get_cab_user_type();
    if (ut !== 'employee' && ut !== 'manager') return;

    // FIX: Always fetch fresh details from server — ensures route display name,
    //      vehicle, driver, shift_time are all populated correctly.
    frappe.call({
        method: 'transport_management.transport_management.doctype.cab_request.cab_request.get_booking_display_details',
        args: { cab_request_name: frm.doc.name },
        callback: function(r) {
            if (r.message) {
                var d = r.message;
                // Merge server data into frm.doc so _render_booking_card sees it
                frm._route_display_name  = d.assigned_route || frm.doc.assigned_route || '—';
                frm.doc.assigned_cab     = d.assigned_cab     || frm.doc.assigned_cab     || '';
                frm.doc.assigned_driver  = d.assigned_driver  || frm.doc.assigned_driver  || '';
                frm.doc.shift_time       = d.shift_time       || frm.doc.shift_time       || '';
                frm.doc.distance_from_route = d.distance_from_route || frm.doc.distance_from_route || '';
                frm.doc.travel_date      = d.travel_date      || frm.doc.travel_date      || '';
            }
            _render_booking_card(frm);
        }
    });
}

function _render_booking_card(frm) {
    $('#cab-booking-status-card').remove();

    const status = frm.doc.status;
    const user_type = get_cab_user_type();
    const statusColors = {
        'Assigned':  { bg: '#d4edda', border: '#28a745', text: '#155724', icon: '✅' },
        'In Trip':   { bg: '#cce5ff', border: '#0d6efd', text: '#004085', icon: '🚗' },
        'Completed': { bg: '#e2e3e5', border: '#6c757d', text: '#383d41', icon: '🏁' },
        'Cancelled': { bg: '#f8d7da', border: '#dc3545', text: '#721c24', icon: '❌' },
    };
    const sc = statusColors[status] || statusColors['Assigned'];

    // FIX: Use fetched display name if available, fallback to frm.doc.assigned_route
    const route_display = frm._route_display_name || frm.doc.assigned_route || '—';

    const can_cancel = (status === 'Assigned') && (user_type === 'employee' || user_type === 'manager');
    const cancel_btn_html = can_cancel
        ? `<button id="cab-cancel-booking-btn" style="background:#dc3545;color:#fff;border:none;
            padding:9px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;
            display:flex;align-items:center;gap:6px;margin-top:10px;">
            ❌ Cancel Booking
           </button>`
        : '';

    const otp_btn_html = (status === 'Assigned') && (user_type === 'employee' || user_type === 'manager')
        ? `<button id="cab-view-otp-btn" style="background:#0d6efd;color:#fff;border:none;
            padding:9px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;
            display:flex;align-items:center;gap:6px;margin-top:10px;">
            🔑 View My OTP
           </button>`
        : '';

    const track_btn_html = ['Assigned', 'In Trip'].includes(status) && (user_type === 'employee' || user_type === 'manager')
        ? `<button id="cab-track-route-btn" style="background:#198754;color:#fff;border:none;
            padding:9px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;
            display:flex;align-items:center;gap:6px;margin-top:10px;">
            🗺️ Track My Route
           </button>`
        : '';

    const card_html = `
    <div id="cab-booking-status-card" style="margin:14px 0;border:2px solid ${sc.border};
        border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,0.08);">
        <div style="background:${sc.border};color:#fff;padding:12px 18px;
            display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="font-size:20px;">${sc.icon}</span>
                <div>
                    <div style="font-size:15px;font-weight:700;">Booking Status: ${status}</div>
                    <div style="font-size:12px;opacity:0.9;">Ref: ${frm.doc.name || '—'}</div>
                </div>
            </div>
            <div style="background:rgba(255,255,255,0.2);border-radius:8px;padding:6px 12px;font-size:12px;font-weight:600;">
                📅 ${frm.doc.travel_date || (frm.doc.booking_datetime ? frm.doc.booking_datetime.split(' ')[0] : '—')}
            </div>
        </div>
        <div style="background:rgba(0,0,0,0.04);padding:8px 18px;border-bottom:1px solid rgba(0,0,0,0.06);
            font-size:12px;color:#495057;display:flex;gap:20px;flex-wrap:wrap;">
            <span>👤 <b>${frm.doc.employee_name || '—'}</b></span>
            <span>🆔 ${frm.doc.employee_id || '—'}</span>
            <span>📞 ${frm.doc.contact_no || '—'}</span>
            <span>🏢 ${frm.doc.department || '—'}</span>
        </div>
        <div style="background:${sc.bg};padding:14px 18px;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px 20px;font-size:13px;color:${sc.text};">
                <div>🛣️ <b>Route:</b><br><span style="color:#333;">${route_display}</span></div>
                <div>🚌 <b>Vehicle:</b><br><span style="color:#333;">${frm.doc.assigned_cab || '—'}</span></div>
                <div>👨‍✈️ <b>Driver:</b><br><span style="color:#333;">${frm.doc.assigned_driver || '—'}</span></div>
                <div>⏰ <b>Shift Time:</b><br><span style="color:#333;">${frm.doc.shift_time || '—'}</span></div>
                <div>📍 <b>Pickup:</b><br><span style="color:#333;">${frm.doc.pickup_location || '—'}</span></div>
                <div>📏 <b>Distance from Route:</b><br><span style="color:#333;">${frm.doc.distance_from_route ? frm.doc.distance_from_route + ' km' : '—'}</span></div>
            </div>
            <div style="display:flex;gap:10px;flex-wrap:wrap;">
                ${otp_btn_html}
                ${track_btn_html}
                ${cancel_btn_html}
            </div>
        </div>
    </div>`;

    if ($('#cab-map-widget').length) {
        $('#cab-map-widget').before(card_html);
    } else {
        const $drop = frm.get_field('drop_location') && $(frm.get_field('drop_location').wrapper);
        if ($drop && $drop.length) $drop.before(card_html);
    }

    $('#cab-cancel-booking-btn').on('click', function() {
        frappe.confirm(
            '❗ Are you sure you want to cancel this cab booking?<br>This cannot be undone.',
            function() {
                frappe.call({
                    method: 'transport_management.transport_management.doctype.cab_request.cab_request.cancel_route_booking',
                    args: { cab_request_name: frm.doc.name },
                    freeze: true,
                    freeze_message: 'Cancelling booking...',
                    callback: function(r) {
                        if (r.message && r.message.status === 'success') {
                            frappe.show_alert({ message: '❌ Booking cancelled.', indicator: 'red' }, 4);
                            frm.reload_doc();
                        }
                    }
                });
            }
        );
    });

    $('#cab-view-otp-btn').on('click', function() {
        frappe.call({
            method: 'transport_management.transport_management.doctype.cab_request.cab_request.get_otp',
            args: { docname: frm.doc.name },
            callback: function(r) {
                if (r.message && r.message.otp) {
                    _show_otp_modal(r.message.otp, route_display, frm.doc.name);
                } else {
                    frappe.msgprint({ title: 'No OTP', message: 'OTP not found or already used.', indicator: 'orange' });
                }
            }
        });
    });

    $('#cab-track-route-btn').on('click', function() {
        $('#cab-emp-tracker-panel').show();
        _show_employee_route_tracker(frm);
        const $panel = $('#cab-emp-tracker-panel');
        if ($panel.length) {
            $('html, body').animate({ scrollTop: $panel.offset().top - 80 }, 400);
        }
    });
}

// ── Load Leaflet ───────────────────────────────────────────────────────────
function load_leaflet_then_init(frm) {
    if (!document.getElementById('leaflet-css')) {
        $('<link id="leaflet-css" rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">').appendTo('head');
    }
    if (!window.L) {
        $.getScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js', function() {
            setTimeout(() => init_map(frm), 200);
        });
    } else {
        init_map(frm);
    }
}

// ── Main Map Init ──────────────────────────────────────────────────────────
function init_map(frm) {
    if (frm._cab_map_done) {
        frm._map && frm._map.invalidateSize();
        return;
    }

    inject_styles();

    const $drop_field = frm.get_field('drop_location') && $(frm.get_field('drop_location').wrapper);
    if (!$drop_field || !$drop_field.length) {
        console.warn('[CabMap] drop_location field not found, retrying...');
        setTimeout(() => init_map(frm), 600);
        return;
    }

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
            <span>📏 <strong>Distance:</strong> <span id="cab-dist-val"></span></span>
            <span>⏱ <strong>Est. Travel Time:</strong> <span id="cab-eta-val"></span></span>
        </div>

        <div id="cab-dist-alert" style="display:none; margin-top:8px; padding:10px 16px; border-radius:8px; font-size:13px; font-weight:500;"></div>

        <div style="margin-top:6px; display:flex; gap:8px; flex-wrap:wrap;">
            <button id="cab-save-loc-btn" class="cab-btn" style="background:#198754;">💾 Save This Route</button>
            <button id="cab-load-loc-btn" class="cab-btn" style="background:#0d6efd;">📂 Load Saved Route</button>
        </div>

        <!-- ROUTE-BASED CAB FINDER -->
        <div id="cab-route-finder-section" style="margin-top:14px; border-top:1.5px dashed #dee2e6; padding-top:14px; display:none;">
            <div style="font-size:13px; font-weight:600; color:#495057; margin-bottom:6px;">
                🚌 Available Cabs Near Your Pickup Location
            </div>
            <div style="font-size:12px; color:#6c757d; margin-bottom:10px; background:#f8f9fa; padding:8px 12px; border-radius:6px;">
                📅 Travel date taken from <b>Booking Date/Time</b> &nbsp;|&nbsp;
                🔍 Searching within <b>2 km</b> of your pickup pin
            </div>
            <div style="display:flex; gap:8px; align-items:center; margin-bottom:10px; flex-wrap:wrap;">
                <div id="cab-rf-date-display" style="font-size:13px; color:#495057; background:#e9ecef; padding:7px 14px; border-radius:7px; flex:1; min-width:160px;">
                    📅 Travel Date: <b id="cab-rf-date-text"></b>
                </div>
                <button id="cab-rf-search-btn" style="background:#0d6efd; color:white; border:none; padding:8px 20px; border-radius:7px; font-size:13px; font-weight:600; cursor:pointer; white-space:nowrap;">
                    🔍 Search Cabs
                </button>
            </div>
            <div id="cab-rf-results"></div>
        </div>

        <!-- Route Map Modal -->
        <div id="cab-route-map-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%;
            background:rgba(0,0,0,0.6); z-index:99999; align-items:center; justify-content:center;">
            <div style="background:#fff; border-radius:12px; width:90%; max-width:900px; max-height:90vh;
                overflow:hidden; display:flex; flex-direction:column; box-shadow:0 20px 60px rgba(0,0,0,0.3);">
                <div style="display:flex; align-items:center; justify-content:space-between;
                    padding:14px 18px; border-bottom:1px solid #dee2e6; background:#f8f9fa;">
                    <div>
                        <div id="cab-rmap-title" style="font-size:15px; font-weight:700; color:#1a1a2e;"></div>
                        <div id="cab-rmap-subtitle" style="font-size:12px; color:#6c757d; margin-top:2px;"></div>
                    </div>
                    <button onclick="$('#cab-route-map-modal').hide(); if(window._cab_route_modal_map){window._cab_route_modal_map.remove(); window._cab_route_modal_map=null;}"
                        style="background:none; border:1.5px solid #dee2e6; border-radius:8px; padding:6px 12px; font-size:13px; cursor:pointer; color:#495057;">✕ Close</button>
                </div>
                <div id="cab-rmap-legend" style="padding:8px 16px; background:#fff; border-bottom:1px solid #f0f0f0;
                    display:flex; gap:16px; flex-wrap:wrap; font-size:12px; color:#495057;"></div>
                <div id="cab-route-map-el" style="flex:1; min-height:400px;"></div>
                <div id="cab-rmap-stops" style="max-height:160px; overflow-y:auto; padding:10px 16px;
                    border-top:1px solid #dee2e6; background:#f8f9fa; font-size:12px;"></div>
            </div>
        </div>

        <!-- DRIVER MAP PANEL -->
        <div id="cab-driver-map-panel" style="display:none; margin-top:16px; border-top:2px solid #198754; padding-top:14px;">
            <div style="font-size:14px; font-weight:700; color:#1a1a2e; margin-bottom:4px;">
                🚗 My Route & Passengers <span style="font-size:11px; font-weight:400; color:#6c757d;">(Driver View)</span>
            </div>
            <div style="font-size:12px; color:#6c757d; margin-bottom:10px;">
                Your assigned route, pickup stops, and today's passenger locations are shown below.
            </div>
            <div style="display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap;">
                <button id="cab-driver-refresh-btn" style="background:#198754; color:white; border:none;
                    padding:8px 18px; border-radius:7px; font-size:13px; font-weight:600; cursor:pointer;">
                    🔄 Refresh
                </button>
                <div id="cab-driver-info" style="font-size:12px; color:#495057; background:#e9ecef;
                    padding:7px 14px; border-radius:7px; flex:1;"></div>
            </div>
            <div id="cab-driver-map-el" style="height:480px; border-radius:10px; border:1.5px solid #dee2e6;
                overflow:hidden; background:#e8eaed;"></div>
            <div id="cab-driver-passengers" style="margin-top:10px;"></div>
        </div>

        <!-- EMPLOYEE ROUTE TRACKER PANEL -->
        <div id="cab-emp-tracker-panel" style="display:none; margin-top:16px; border-top:2px solid #28a745; padding-top:14px;">
            <div style="font-size:14px; font-weight:700; color:#1a1a2e; margin-bottom:4px;">
                🗺️ Track My Cab Route <span style="font-size:11px; font-weight:400; color:#6c757d;">(Your Booking)</span>
            </div>
            <div style="font-size:12px; color:#6c757d; margin-bottom:10px;">
                Your pickup location and the cab route are shown below. 🟢 = your pickup point on the route.
            </div>
            <div style="display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap; align-items:center;">
                <button id="cab-emp-tracker-refresh-btn" style="background:#28a745; color:white; border:none;
                    padding:8px 18px; border-radius:7px; font-size:13px; font-weight:600; cursor:pointer;">
                    🔄 Refresh
                </button>
                <div id="cab-emp-tracker-info" style="font-size:12px; color:#495057; background:#e9ecef;
                    padding:7px 14px; border-radius:7px; flex:1;"></div>
            </div>
            <div id="cab-emp-tracker-map-el" style="height:420px; border-radius:10px; border:1.5px solid #dee2e6;
                overflow:hidden; background:#e8eaed;"></div>
            <div id="cab-emp-tracker-stops" style="margin-top:10px;"></div>
        </div>

    </div>`;

    $drop_field.after(map_html);

    const map_field = frm.get_field('map');
    if (map_field) $(map_field.wrapper).hide();

    $(frm.get_field('pickup_location').wrapper).hide();
    $(frm.get_field('drop_location').wrapper).hide();

    const map = L.map('cab-map-el').setView([20.5937, 78.9629], 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>', maxZoom: 19
    }).addTo(map);

    frm._map              = map;
    frm._markers          = {};
    frm._route_layer      = null;
    frm._pickup_coords    = null;
    frm._drop_coords      = null;
    frm._cab_map_done     = true;
    frm._route_distance_km = null;

    if (frm.doc.pickup_location) {
        $('#cab-pickup-input').val(frm.doc.pickup_location);
        geocode_and_place(frm, frm.doc.pickup_location, 'pickup');
    }
    if (frm.doc.drop_location) {
        $('#cab-drop-input').val(frm.doc.drop_location);
        geocode_and_place(frm, frm.doc.drop_location, 'drop');
    }

    bind_search('cab-pickup-input', 'cab-pickup-sug', function(result) {
        frm._pickup_coords = [parseFloat(result.lat), parseFloat(result.lon)];
        place_marker(frm, 'pickup', frm._pickup_coords, result.display_name);
        safe_set(frm, 'pickup_location', result.display_name);
        safe_set(frm, 'pickup_lat', result.lat);
        safe_set(frm, 'pickup_lng', result.lon);
        try_draw_route(frm);
    });

    bind_search('cab-drop-input', 'cab-drop-sug', function(result) {
        frm._drop_coords = [parseFloat(result.lat), parseFloat(result.lon)];
        place_marker(frm, 'drop', frm._drop_coords, result.display_name);
        safe_set(frm, 'drop_location', result.display_name);
        try_draw_route(frm);
    });

    $('#cab-save-loc-btn').on('click', () => save_route_dialog(frm));
    $('#cab-load-loc-btn').on('click', () => load_route_dialog(frm));

    const _user_type = get_cab_user_type();
    if (_user_type === 'employee' || _user_type === 'manager') {
        if (!['Assigned', 'In Trip', 'Completed', 'Cancelled'].includes(frm.doc.status)) {
            $('#cab-route-finder-section').show();
            _rf_update_date_display(frm);
            $('#cab-rf-search-btn').on('click', function() { _rf_search_cabs(frm); });
        } else {
            $('#cab-route-finder-section').hide();
        }
    } else {
        $('#cab-route-finder-section').hide();
    }

    apply_role_restrictions(frm);
}

// ── Styles ─────────────────────────────────────────────────────────────────
function inject_styles() {
    if (document.getElementById('cab-map-styles')) return;
    $('<style id="cab-map-styles">').text(`
        .cab-sug-box { display:none; position:absolute; top:calc(100% + 2px); left:0; right:0;
            background:#fff; border:1px solid #ced4da; border-radius:8px; max-height:210px;
            overflow-y:auto; z-index:99999; box-shadow:0 6px 18px rgba(0,0,0,0.12); }
        .cab-sug-item { padding:9px 12px; font-size:13px; cursor:pointer;
            border-bottom:1px solid #f0f0f0; line-height:1.4; transition:background 0.12s; }
        .cab-sug-item:hover { background:#f0f7ff; }
        .cab-sug-item:last-child { border-bottom:none; }
        .cab-btn { color:#fff; border:none; padding:7px 14px; border-radius:7px;
            font-size:12px; cursor:pointer; font-weight:500; transition:opacity 0.15s; }
        .cab-btn:hover { opacity:0.85; }
        .cab-mgr-stat-card { background:#fff; border:1.5px solid #dee2e6; border-radius:10px;
            padding:12px 16px; flex:1; min-width:140px; text-align:center; }
        .cab-mgr-stat-card .stat-num { font-size:22px; font-weight:700; color:#0d6efd; }
        .cab-mgr-stat-card .stat-lbl { font-size:11px; color:#6c757d; margin-top:2px; }
        .cab-passenger-card { border:1.5px solid #dee2e6; border-radius:10px; padding:12px 14px;
            margin-bottom:8px; background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.05); }
        .cab-passenger-card:hover { border-color:#198754; }
    `).appendTo('head');
}

// ── Autocomplete Search ────────────────────────────────────────────────────
function bind_search(input_id, sug_id, on_select) {
    let timer;
    $('#' + input_id).on('input', function() {
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
                }).catch(() => {});
        }, 420);
    });
    $(document).on('click', function(e) {
        if (!$(e.target).is('#' + input_id)) $('#' + sug_id).hide();
    });
}

// ── Geocode helpers ────────────────────────────────────────────────────────
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
        }).catch(() => {});
}

function geocode_field(frm, type) {
    const val = type === 'pickup' ? frm.doc.pickup_location : frm.doc.drop_location;
    if (val) geocode_and_place(frm, val, type);
}

// ── Place Marker ───────────────────────────────────────────────────────────
function place_marker(frm, type, coords, label) {
    if (!frm._map) return;
    if (frm._markers[type]) frm._map.removeLayer(frm._markers[type]);
    const color = type === 'pickup' ? '#198754' : '#dc3545';
    const icon = L.divIcon({
        html: `<div style="width:18px;height:18px;background:${color};border-radius:50%;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.35);"></div>`,
        iconSize: [24, 24], iconAnchor: [12, 12], className: ''
    });
    frm._markers[type] = L.marker(coords, { icon })
        .addTo(frm._map)
        .bindPopup(`<b>${type === 'pickup' ? '📍 Pickup' : '🏁 Drop'}</b><br><small>${label}</small>`)
        .openPopup();
    const pts = Object.values(frm._markers).map(m => m.getLatLng());
    if (pts.length >= 2) frm._map.fitBounds(L.latLngBounds(pts).pad(0.2));
    else frm._map.setView(coords, 14);
}

// ── Distance Alert ─────────────────────────────────────────────────────────
function show_dist_alert(type, km) {
    const $alert = $('#cab-dist-alert');
    if (type === 'too_short') {
        $alert.css({ 'display':'flex', 'align-items':'center', 'gap':'8px',
            'background':'#fff3cd', 'border-left':'4px solid #ffc107', 'color':'#856404' })
            .html(`⚠️ <span>Distance is <strong>${km} km</strong> — too short. Minimum is <strong>3 km</strong>.</span>`);
    } else if (type === 'too_long') {
        $alert.css({ 'display':'flex', 'align-items':'center', 'gap':'8px',
            'background':'#f8d7da', 'border-left':'4px solid #dc3545', 'color':'#842029' })
            .html(`🚫 <span>Distance is <strong>${km} km</strong> — too far. Maximum is <strong>70 km</strong>.</span>`);
    } else {
        $alert.hide().empty();
    }
}

// ── Draw Route ─────────────────────────────────────────────────────────────
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

            frm._route_distance_km = km;
            $('#cab-dist-val').text(km + ' km');
            $('#cab-eta-val').text(eta);
            $('#cab-route-bar').css('display', 'flex');

            let route_color = '#0d6efd';
            if (km < 3) {
                show_dist_alert('too_short', km);
                safe_set(frm, 'distance', '');
                route_color = '#ffc107';
                if (frm._route_layer) frm._map.removeLayer(frm._route_layer);
                frm._route_layer = L.geoJSON(route.geometry, { style: { color: route_color, weight: 5, opacity: 0.85 } }).addTo(frm._map);
                frm._map.fitBounds(frm._route_layer.getBounds().pad(0.15));
                return;
            } else if (km > 70) {
                show_dist_alert('too_long', km);
                safe_set(frm, 'distance', '');
                route_color = '#dc3545';
                if (frm._route_layer) frm._map.removeLayer(frm._route_layer);
                frm._route_layer = L.geoJSON(route.geometry, { style: { color: route_color, weight: 5, opacity: 0.85 } }).addTo(frm._map);
                frm._map.fitBounds(frm._route_layer.getBounds().pad(0.15));
                return;
            } else {
                show_dist_alert('clear');
            }

            safe_set(frm, 'distance', km + ' km');
            if (frm.fields_dict && frm.fields_dict['estimated_arrival_time']) safe_set(frm, 'estimated_arrival_time', eta);
            else if (frm.fields_dict && frm.fields_dict['estimated_time']) safe_set(frm, 'estimated_time', eta);
            else frm.doc['estimated_arrival_time'] = eta;

            if (frm._route_layer) frm._map.removeLayer(frm._route_layer);
            frm._route_layer = L.geoJSON(route.geometry, { style: { color: '#0d6efd', weight: 5, opacity: 0.85 } }).addTo(frm._map);
            frm._map.fitBounds(frm._route_layer.getBounds().pad(0.15));
        })
        .catch(err => console.warn('[CabMap] Route error:', err));
}

// ── Booking Notification ───────────────────────────────────────────────────
function send_booking_notification(frm, km, eta) {
    frappe.realtime.publish('cab_booking_alert', {
        user: frappe.session.user,
        pickup: frm.doc.pickup_location,
        drop: frm.doc.drop_location,
        distance: km + ' km',
        eta: eta,
        docname: frm.doc.name || 'New'
    });
}

// ── Save / Load Route ──────────────────────────────────────────────────────
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
            const km = frm._route_distance_km;
            if (km !== null && km !== undefined) {
                if (km < 3) { frappe.show_alert({ message: `⚠️ Distance ${km} km below 3 km minimum.`, indicator: 'orange' }); return; }
                if (km > 70) { frappe.show_alert({ message: `🚫 Distance ${km} km exceeds 70 km maximum.`, indicator: 'red' }); return; }
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

function load_route_dialog(frm) {
    const key = 'cab_saved_routes_' + frappe.session.user;
    const list = JSON.parse(localStorage.getItem(key) || '[]');
    if (!list.length) { frappe.msgprint('No saved routes yet. Save one first!'); return; }
    const d = new frappe.ui.Dialog({
        title: '📂 Load Saved Route',
        fields: [{ fieldname: 'sel', fieldtype: 'Select', label: 'Choose a route', reqd: 1, options: list.map(r => r.label).join('\n') }],
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
//  ROUTE-BASED CAB FINDER
// ============================================================

var _rf_route_layers = [];
var _rf_cabs_data    = [];
var _RF_COLORS = ['#0d6efd','#198754','#dc3545','#fd7e14','#6f42c1','#0dcaf0','#e83e8c','#20c997'];

function _rf_update_date_display(frm) {
    var dt = frm.doc.booking_datetime;
    if (dt) {
        var date_str = dt.split(' ')[0];
        var display  = new Date(date_str + 'T00:00:00').toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' });
        $('#cab-rf-date-text').text(display);
    } else {
        $('#cab-rf-date-text').text('Not set — please fill Booking Date/Time first');
    }
}

function _rf_is_within_cutoff(shift_time) {
    if (!shift_time) return true;
    try {
        var now = new Date();
        var parts = shift_time.split(':');
        var shift = new Date();
        shift.setHours(parseInt(parts[0]), parseInt(parts[1]), parseInt(parts[2] || 0), 0);
        if (shift < now) shift.setDate(shift.getDate() + 1);
        return (shift - now) / (1000 * 60 * 60) > 2;
    } catch(e) { return true; }
}

// FIX: _rf_search_cabs now calls server for LIVE seat counts every time,
//      and re-renders cards fresh so cancellations are reflected immediately.
function _rf_search_cabs(frm) {
    if (!frm._pickup_coords) {
        frappe.show_alert({ message: '📍 Please set your Pickup Location on the map first.', indicator: 'orange' }, 5);
        return;
    }
    if (!frm.doc.booking_datetime) {
        frappe.show_alert({ message: '📅 Please fill Booking Date/Time first.', indicator: 'orange' }, 5);
        return;
    }

    var travel_date = frm.doc.booking_datetime.split(' ')[0];
    _rf_update_date_display(frm);

    var $results = $('#cab-rf-results');
    $results.html('<div style="text-align:center;padding:20px;color:#0d6efd;font-size:13px;">🔍 Searching cabs near your pickup...</div>');
    _rf_clear_route_layers(frm);

    // FIX: Always call server fresh — never use cached _rf_cabs_data for seat counts
    frappe.call({
        method: 'transport_management.transport_management.doctype.cab_request.cab_request.find_matching_cabs',
        args: { employee_lat: frm._pickup_coords[0], employee_lng: frm._pickup_coords[1], travel_date: travel_date, threshold_km: 2.0 },
        callback: function(r) {
            if (r.exc) { $results.html('<div style="color:#dc3545;padding:12px;font-size:13px;">⚠️ Error. Check console.</div>'); return; }
            _rf_cabs_data = r.message || [];
            _rf_render_cards(frm, _rf_cabs_data);
            _rf_draw_routes(frm, _rf_cabs_data);
        }
    });
}

function _rf_render_cards(frm, cabs) {
    var $results = $('#cab-rf-results');
    if (!cabs.length) {
        $results.html("<div style='background:#fff8e1;border-left:4px solid #ffc107;border-radius:8px;padding:12px 16px;font-size:13px;color:#795548'>No cabs found within 2 km of your pickup. Contact HR to add a route near you.</div>");
        return;
    }

    var html = "<div style='font-size:12px;color:#6c757d;margin-bottom:8px'>Found <b>" + cabs.length + "</b> cab route(s) near your pickup:</div>";

    cabs.forEach(function(cab, idx) {
        var color = _RF_COLORS[idx % _RF_COLORS.length];
        var pct   = Math.round((cab.booked_seats / cab.total_seats) * 100);
        var is_full = (cab.available_seats <= 0);
        var cutoff_passed = !_rf_is_within_cutoff(cab.shift_time);
        var aclr  = is_full ? '#842029' : cab.available_seats > 3 ? '#155724' : '#856404';
        var abg   = is_full ? '#f8d7da'  : cab.available_seats > 3 ? '#d4edda' : '#fff3cd';
        var bclr  = is_full ? '#dc3545'  : cab.available_seats > 3 ? '#28a745' : '#ffc107';
        var pickup_label = (frm.doc.pickup_location || 'Your Pickup').replace(/"/g, '&quot;');
        var r_id = String(cab.route || '').replace(/'/g, "\\'");
        var rn   = String(cab.route_name || '').replace(/'/g, "\\'");
        var fn   = String(frm.doc.name || '').replace(/'/g, "\\'");

        var status_badge = '';
        if (is_full) status_badge = "<span style='background:#dc3545;color:#fff;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:700;margin-left:8px;'>FULL</span>";
        else if (cutoff_passed) status_badge = "<span style='background:#fd7e14;color:#fff;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:700;margin-left:8px;'>BOOKING CLOSED</span>";
        else if (cab.available_seats <= 3) status_badge = "<span style='background:#ffc107;color:#212529;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:700;margin-left:8px;'>FILLING FAST</span>";

        var disabled_attr = (is_full || cutoff_passed) ? 'disabled' : '';
        var disabled_style = (is_full || cutoff_passed) ? 'opacity:0.5;cursor:not-allowed;background:#6c757d;' : '';

        // FIX: Show live seat count prominently with total seats context
        var seat_info_html = `
            <div style='background:#f8f9fa;border-radius:6px;padding:8px 12px;margin-bottom:10px;
                display:flex;align-items:center;justify-content:space-between;font-size:12px;'>
                <div>
                    <span style='font-weight:600;color:#495057;'>💺 Seat Availability:</span>
                    <span style='margin-left:8px;font-weight:700;font-size:14px;color:${aclr};'>
                        ${is_full ? '0' : cab.available_seats} available
                    </span>
                    <span style='color:#6c757d;'> / ${cab.total_seats} total</span>
                </div>
                <div style='background:${abg};color:${aclr};border-radius:6px;padding:3px 10px;font-size:11px;font-weight:600;'>
                    ${cab.booked_seats} booked
                </div>
            </div>`;

        html += `<div id='cab-card-${r_id}' style='border:1.5px solid #dee2e6;border-radius:10px;padding:13px;margin-bottom:10px;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.06);'
                     onmouseover="this.style.borderColor='${color}'" onmouseout="this.style.borderColor='#dee2e6'">
            <div style='display:flex;align-items:start;gap:10px;margin-bottom:10px;'>
                <div style='background:${color};color:#fff;border-radius:6px;padding:4px 10px;font-size:11px;font-weight:700;flex-shrink:0;'>#${idx+1}</div>
                <div style='flex:1;'>
                    <div style='font-size:14px;font-weight:600;color:#1a1a2e;'>${cab.route_name}${status_badge}</div>
                    <div style='font-size:11.5px;color:#6c757d;margin-top:2px;'>${cab.start_location} → ${cab.end_location}</div>
                </div>
            </div>
            ${seat_info_html}
            <div style='background:#f1f3f5;border-radius:4px;height:6px;margin-bottom:6px;'>
                <div style='background:${bclr};height:6px;border-radius:4px;width:${Math.min(pct,100)}%;transition:width 0.3s;'></div>
            </div>
            <div style='display:grid;grid-template-columns:1fr 1fr;gap:5px 16px;font-size:12px;color:#495057;margin-bottom:10px;'>
                <div>🚌 Vehicle: <b>${cab.license_plate || cab.vehicle}</b></div>
                <div>⏰ Shift: <b>${cab.shift_time || '—'}</b></div>
                <div>👤 Driver: ${cab.driver_name || 'TBD'}</div>
                <div>📞 Phone: ${cab.driver_contact || '—'}</div>
                <div>📏 From route: <b>${cab.distance_from_route} km</b></div>
                <div>📍 Pickup: ${pickup_label}</div>
            </div>
            <div style='display:flex;gap:8px;'>
                <button class='cab-btn' style='flex:1;background:#6c757d;font-size:12px;'
                    onclick="_rf_view_route_on_map('${r_id}')">🗺️ View on Map</button>
                <button id='cab-bookbtn-${r_id}' class='cab-btn' style='flex:2;background:${color};font-size:12px;${disabled_style}' ${disabled_attr}
                    onclick="${(is_full || cutoff_passed) ? '' : `_rf_book_cab('${fn}','${r_id}','${rn}',${cab.distance_from_route})`}">
                    ${is_full ? '🚫 Cab Full' : cutoff_passed ? '⏰ Booking Closed' : '✅ Book This Cab'}
                </button>
            </div>
        </div>`;
    });

    $results.html(html);
}

function _rf_draw_routes(frm, cabs) {
    if (!frm._map) return;
    cabs.forEach(function(cab, idx) {
        var color = _RF_COLORS[idx % _RF_COLORS.length];
        var wps   = (cab.waypoints || []).slice().sort(function(a,b){ return a.sequence - b.sequence; });
        if (wps.length < 2) return;
        var poly = L.polyline(wps.map(function(wp){ return [wp.latitude, wp.longitude]; }),
            { color: color, weight: 4, opacity: 0.85, dashArray: '8,5' }).addTo(frm._map)
            .bindPopup('<b>' + cab.route_name + '</b><br><small>' + cab.start_location + ' → ' + cab.end_location + '</small>');
        _rf_route_layers.push(poly);
        wps.forEach(function(wp) {
            if (!wp.latitude || !wp.longitude) return;
            var dot = L.circleMarker([wp.latitude, wp.longitude], { radius: 6, color: '#fff', fillColor: color, fillOpacity: 1, weight: 2 })
                .addTo(frm._map).bindPopup('<b>' + (wp.stop_name || '') + '</b>' + (wp.pickup_time ? '<br>⏰ ' + wp.pickup_time : ''));
            _rf_route_layers.push(dot);
        });
    });
}

function _rf_clear_route_layers(frm) {
    _rf_route_layers.forEach(function(l) { if (frm._map) frm._map.removeLayer(l); });
    _rf_route_layers = [];
}

window._rf_view_route_on_map = function(route_name) {
    var cab = (_rf_cabs_data || []).find(function(c){ return c.route === route_name; });
    var frm = cur_frm;
    if (!cab) return;

    $('#cab-rmap-title').text(cab.route_name);
    $('#cab-rmap-subtitle').text(cab.start_location + ' → ' + cab.end_location +
        ' | Vehicle: ' + (cab.license_plate || cab.vehicle || '—') +
        ' | Driver: ' + (cab.driver_name || 'TBD') + ' | Shift: ' + (cab.shift_time || '—'));
    $('#cab-route-map-modal').css('display', 'flex');

    if (window._cab_route_modal_map) { window._cab_route_modal_map.remove(); window._cab_route_modal_map = null; }

    var modal_map = L.map('cab-route-map-el').setView([20.5937, 78.9629], 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap', maxZoom: 19 }).addTo(modal_map);
    window._cab_route_modal_map = modal_map;

    var wps = (cab.waypoints || []).slice().sort(function(a,b){ return a.sequence - b.sequence; });
    var valid_wps = wps.filter(function(w){ return w.latitude && w.longitude; });
    if (!valid_wps.length) { $('#cab-route-map-modal').hide(); frappe.show_alert({ message: 'No waypoint data.', indicator: 'orange' }); return; }

    var color = '#0d6efd', bounds_pts = [];
    valid_wps.forEach(function(wp, i) {
        bounds_pts.push([wp.latitude, wp.longitude]);
        var is_start = (i === 0), is_end = (i === valid_wps.length - 1);
        var lbl = is_start ? 'S' : is_end ? 'E' : String(i+1);
        var bg  = is_start ? '#198754' : is_end ? '#dc3545' : color;
        var m = L.marker([wp.latitude, wp.longitude], {
            icon: L.divIcon({ html: `<div style="background:${bg};color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3);">${lbl}</div>`, iconSize: [24,24], iconAnchor: [12,12], className: '' })
        }).addTo(modal_map).bindPopup('<b>' + (wp.stop_name || 'Stop '+(i+1)) + '</b>' + (wp.pickup_time ? '<br>⏰ <b>' + wp.pickup_time + '</b>' : ''));
    });

    if (frm._pickup_coords) {
        bounds_pts.push(frm._pickup_coords);
        var emp_m = L.marker(frm._pickup_coords, {
            icon: L.divIcon({ html: `<div style="background:#6f42c1;color:#fff;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:12px;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3);">👤</div>`, iconSize: [24,24], iconAnchor: [12,12], className: '' })
        }).addTo(modal_map).bindPopup('<b>Your Pickup</b><br>' + (frm.doc.pickup_location || ''));
        var nearest = valid_wps.reduce(function(best, wp) {
            var d = Math.pow(wp.latitude - frm._pickup_coords[0], 2) + Math.pow(wp.longitude - frm._pickup_coords[1], 2);
            return d < best.d ? {wp, d} : best;
        }, {wp: valid_wps[0], d: Infinity}).wp;
        L.polyline([frm._pickup_coords, [nearest.latitude, nearest.longitude]], { color: '#6f42c1', weight: 2.5, opacity: 0.7, dashArray: '6,4' }).addTo(modal_map);
    }

    if (valid_wps.length >= 2) {
        var coords_str = valid_wps.map(function(wp){ return wp.longitude + ',' + wp.latitude; }).join(';');
        fetch('https://router.project-osrm.org/route/v1/driving/' + coords_str + '?overview=full&geometries=geojson')
            .then(r => r.json()).then(function(data) {
                if (!data.routes || !data.routes.length) return;
                var km = parseFloat((data.routes[0].distance / 1000).toFixed(1));
                var total_min = Math.round(data.routes[0].duration / 60);
                var h = Math.floor(total_min/60), m = total_min%60;
                var eta = h > 0 ? h+'h '+m+'m' : m+' min';
                L.geoJSON(data.routes[0].geometry, { style: { color, weight: 5, opacity: 0.85 } }).addTo(modal_map);
                modal_map.fitBounds(L.latLngBounds(bounds_pts).pad(0.15));
                $('#cab-rmap-legend').html(
                    '<span>🟢 Start</span><span>🔴 End</span>' +
                    (frm._pickup_coords ? '<span>🟣 Your Location</span>' : '') +
                    '<span style="font-weight:600;color:#0d6efd;">📏 ' + km + ' km</span>' +
                    '<span style="font-weight:600;color:#198754;">⏱ ' + eta + '</span>'
                );
            }).catch(function() {
                L.polyline(valid_wps.map(w => [w.latitude, w.longitude]), { color, weight: 4, opacity: 0.8, dashArray: '8,5' }).addTo(modal_map);
                modal_map.fitBounds(L.latLngBounds(bounds_pts).pad(0.15));
            });
    } else { modal_map.fitBounds(L.latLngBounds(bounds_pts).pad(0.25)); }

    var stops_html = '<b style="font-size:12px;">Route Stops:</b><div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;">';
    valid_wps.forEach(function(wp, i) {
        stops_html += '<div style="background:#fff;border:1px solid #dee2e6;border-radius:6px;padding:4px 10px;font-size:11.5px;">' +
            '<b>' + (i+1) + '.</b> ' + (wp.stop_name || 'Stop '+(i+1)) +
            (wp.pickup_time ? ' <span style="color:#0d6efd;">⏰ '+wp.pickup_time+'</span>' : '') + '</div>';
    });
    $('#cab-rmap-stops').html(stops_html + '</div>');
    setTimeout(function(){ modal_map.invalidateSize(); }, 200);
};

window._rf_zoom_route = function(route_name) { window._rf_view_route_on_map(route_name); };

// ── Book Cab ───────────────────────────────────────────────────────────────
window._rf_book_cab = function(cab_request_name, route_name, route_display, distance_from_route) {
    var frm = cur_frm;
    var cab = (_rf_cabs_data || []).find(function(c){ return c.route === route_name; });

    if (cab && cab.available_seats <= 0) {
        frappe.msgprint({ title: 'Cab Full', message: 'No seats available. Please choose another.', indicator: 'red' }); return;
    }
    if (cab && !_rf_is_within_cutoff(cab.shift_time)) {
        frappe.msgprint({ title: 'Booking Closed', message: 'Bookings close 2 hours before shift time (' + (cab.shift_time || '—') + ').', indicator: 'orange' }); return;
    }

    // Validate required fields before attempting to book
    if (!frm.doc.pickup_location) {
        frappe.show_alert({ message: '📍 Please set your Pickup Location first.', indicator: 'orange' }, 5); return;
    }
    if (!frm.doc.booking_datetime) {
        frappe.show_alert({ message: '📅 Please fill Booking Date/Time first.', indicator: 'orange' }, 5); return;
    }
    if (!frm.doc.employee_name) {
        frappe.show_alert({ message: '👤 Employee name is required.', indicator: 'orange' }, 5); return;
    }

    frappe.confirm(
        `Book <b>${route_display}</b>?<br>📍 Pickup: <b>${frm.doc.pickup_location || '—'}</b><br>📏 Distance from route: <b>${distance_from_route} km</b>${cab ? '<br>💺 Seats remaining: <b>' + cab.available_seats + '</b>' : ''}`,
        function() {
            var _do_booking = function(saved_name) {
                frappe.call({
                    method: 'transport_management.transport_management.doctype.cab_request.cab_request.book_route_cab',
                    args: {
                        cab_request_name: saved_name,
                        route_name:        route_name,
                        distance_from_route: distance_from_route
                    },
                    freeze: true,
                    freeze_message: '🔄 Booking your cab...',
                    callback: function(r) {
                        if (r.exc || !r.message) {
                            frappe.msgprint({ title: 'Booking Error', message: 'An unexpected error occurred. Please try again.', indicator: 'red' });
                            return;
                        }
                        if (r.message.status === 'success') {
                            // Hide cab finder — booking done
                            $('#cab-route-finder-section').hide();
                            $('#cab-rf-results').empty();

                            // Show OTP modal
                            _show_otp_modal(r.message.otp, route_display, saved_name);

                            // Reload the form to reflect Assigned status
                            frappe.show_alert({ message: '✅ Cab booked! Status updated to Assigned.', indicator: 'green' }, 5);
                            setTimeout(function() { cur_frm.reload_doc(); }, 1500);

                        } else {
                            frappe.msgprint({
                                title: 'Booking Failed',
                                message: r.message.message || 'Booking failed. Please try again.',
                                indicator: 'red'
                            });
                        }
                    }
                });
            };

            // Check if form is new (unsaved) — if so, save first
            if (frm.is_new() || !frm.doc.name || frm.doc.name.indexOf('new-') === 0) {
                frappe.show_alert({ message: '💾 Saving your request...', indicator: 'blue' }, 2);

                // Temporarily set status to Pending so save doesn't fail
                frm.doc.status = 'Pending';

                frappe.call({
                    method: 'frappe.desk.form.save.savedocs',
                    args: {
                        doc: frm.doc,
                        action: 'Save'
                    },
                    freeze: true,
                    freeze_message: '💾 Saving request...',
                    callback: function(r) {
                        if (r.exc) {
                            frappe.msgprint({
                                title: '⚠️ Cannot Save',
                                message: 'Please ensure Booking Date/Time is at least 1 hour from now, then try again.',
                                indicator: 'orange'
                            });
                            return;
                        }
                        // Doc saved — update local frm state
                        frappe.model.sync(r.message && r.message.docs ? r.message.docs : []);
                        frm.refresh();
                        _do_booking(frm.doc.name);
                    }
                });
            } else {
                // Doc already saved — book directly without re-saving
                _do_booking(frm.doc.name);
            }
        }
    );
};

// ── Inline Cancel ──────────────────────────────────────────────────────────
window._rf_inline_cancel = function(cab_request_name) {
    frappe.confirm(
        '❗ Are you sure you want to cancel this cab booking?<br>This cannot be undone.',
        function() {
            frappe.call({
                method: 'transport_management.transport_management.doctype.cab_request.cab_request.cancel_route_booking',
                args: { cab_request_name: cab_request_name },
                freeze: true, freeze_message: 'Cancelling booking...',
                callback: function(r) {
                    if (r.message && r.message.status === 'success') {
                        frappe.show_alert({ message: '❌ Booking cancelled.', indicator: 'red' }, 4);
                        cur_frm.reload_doc();
                    } else {
                        frappe.msgprint({ title: 'Error', message: (r.message && r.message.message) || 'Cancellation failed.', indicator: 'red' });
                    }
                }
            });
        }
    );
};

// ── OTP Modal ─────────────────────────────────────────────────────────────
function _show_otp_modal(otp, route_display, docname) {
    $('#cab-otp-modal').remove();
    $('body').append(`
    <div id="cab-otp-modal" style="position:fixed;top:0;left:0;width:100%;height:100%;
        background:rgba(0,0,0,0.65);z-index:999999;display:flex;align-items:center;justify-content:center;">
        <div style="background:#fff;border-radius:16px;padding:32px 28px;max-width:420px;width:92%;text-align:center;box-shadow:0 24px 64px rgba(0,0,0,0.35);">
            <div style="width:56px;height:56px;background:#d4edda;border-radius:50%;margin:0 auto 14px;display:flex;align-items:center;justify-content:center;font-size:28px;">✅</div>
            <div style="font-size:18px;font-weight:700;color:#155724;margin-bottom:6px;">Booking Confirmed!</div>
            <div style="font-size:13px;color:#495057;margin-bottom:18px;">${route_display || '—'}</div>
            <div style="background:linear-gradient(135deg,#0d6efd,#0a58ca);border-radius:12px;padding:20px 16px;margin-bottom:16px;">
                <div style="font-size:11px;font-weight:600;color:rgba(255,255,255,0.8);letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">Your Trip OTP</div>
                <div style="font-size:42px;font-weight:900;color:#fff;letter-spacing:10px;font-family:monospace;">${otp || '------'}</div>
                <div style="font-size:11px;color:rgba(255,255,255,0.7);margin-top:8px;">Share this OTP with your driver to start the trip</div>
            </div>
            <div style="background:#fff3cd;border-radius:8px;padding:10px 14px;font-size:12px;color:#856404;margin-bottom:18px;text-align:left;">
                ⚠️ <b>Do not share</b> this OTP with anyone except your assigned driver.
            </div>
            <div style="display:flex;gap:10px;">
                <button onclick="navigator.clipboard&&navigator.clipboard.writeText('${otp}').then(()=>frappe.show_alert({message:'OTP copied!',indicator:'green'},2))"
                    style="flex:1;background:#e9ecef;color:#495057;border:none;padding:10px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">📋 Copy OTP</button>
                <button onclick="$('#cab-otp-modal').remove()"
                    style="flex:1;background:#0d6efd;color:#fff;border:none;padding:10px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">Got it ✓</button>
            </div>
        </div>
    </div>`);
}

// ── Driver OTP Dialog ──────────────────────────────────────────────────────
function _driver_verify_otp_dialog(frm) {
    var d = new frappe.ui.Dialog({
        title: '🔐 Verify Employee OTP to Start Trip',
        fields: [
            { fieldtype: 'HTML', fieldname: 'otp_info', options: '<div style="background:#e8f4fd;border-radius:8px;padding:12px 14px;font-size:13px;color:#0c5480;margin-bottom:4px;">Ask the employee for their 6-digit OTP and enter it below to start the trip.</div>' },
            { fieldname: 'otp_input', fieldtype: 'Data', label: 'Enter Employee OTP', reqd: 1, description: '6-digit code from employee booking confirmation' }
        ],
        primary_action_label: '✅ Verify & Start Trip',
        primary_action: function(vals) {
            if (!vals.otp_input || vals.otp_input.trim().length !== 6) {
                frappe.show_alert({ message: 'Please enter a valid 6-digit OTP.', indicator: 'orange' }); return;
            }
            frappe.call({
                method: 'transport_management.transport_management.doctype.cab_request.cab_request.verify_otp_and_start_trip',
                args: { docname: frm.doc.name, entered_otp: vals.otp_input.trim() },
                freeze: true, freeze_message: 'Verifying OTP...',
                callback: function(r) {
                    if (r.message && r.message.status === 'success') {
                        d.hide();
                        frappe.show_alert({ message: '🚗 OTP verified! Trip has started.', indicator: 'green' }, 5);
                        frm.reload_doc();
                        // After trip starts, show Complete Trip dialog for driver
                        setTimeout(function() {
                            _driver_complete_trip_dialog(frm);
                        }, 1200);
                    } else if (r.message && r.message.status === 'invalid') {
                        d.fields_dict.otp_input.$input.css({ 'border-color': '#dc3545', 'background': '#fff5f5' });
                        frappe.show_alert({ message: '❌ ' + (r.message.message || 'Invalid OTP.'), indicator: 'red' }, 5);
                    } else {
                        frappe.msgprint({ title: 'Error', message: (r.message && r.message.message) || 'Verification failed.', indicator: 'red' });
                    }
                }
            });
        }
    });
    d.show();
}

// ── Driver Complete Trip Dialog ────────────────────────────────────────────
// Shown automatically after OTP is verified and trip starts
function _driver_complete_trip_dialog(frm) {
    var d = new frappe.ui.Dialog({
        title: '🚗 Trip In Progress',
        fields: [
            { fieldtype: 'HTML', fieldname: 'trip_info', options: `
                <div style="text-align:center;padding:16px 0;">
                    <div style="font-size:40px;margin-bottom:10px;">🚗</div>
                    <div style="font-size:16px;font-weight:700;color:#0d6efd;margin-bottom:6px;">Trip has started!</div>
                    <div style="font-size:13px;color:#495057;margin-bottom:16px;">
                        Click <b>Complete Trip</b> when you have dropped off the passenger.
                    </div>
                    <div style="background:#e8f4fd;border-radius:8px;padding:10px 14px;font-size:12px;color:#0c5480;">
                        ℹ️ You can also complete the trip later using the <b>✅ Complete Trip</b> button on the form.
                    </div>
                </div>`
            }
        ],
        primary_action_label: '✅ Complete Trip Now',
        secondary_action_label: 'Later',
        secondary_action: function() { d.hide(); },
        primary_action: function() {
            frappe.call({
                method: 'transport_management.transport_management.doctype.cab_request.cab_request.driver_complete_trip',
                args: { docname: frm.doc.name },
                freeze: true, freeze_message: 'Completing trip...',
                callback: function(r) {
                    d.hide();
                    frappe.show_alert({ message: '✅ Trip marked as Completed!', indicator: 'green' }, 4);
                    frm.reload_doc();
                }
            });
        }
    });
    d.show();
}


// ============================================================
//  DRIVER MAP PANEL
// ============================================================

var _driver_map      = null;
var _driver_layers   = [];

function _show_driver_map_panel(frm) {
    $('#cab-driver-map-panel').show();

    if (!_driver_map) {
        _driver_map = L.map('cab-driver-map-el').setView([13.0827, 80.2707], 11);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap', maxZoom: 19
        }).addTo(_driver_map);
    }

    _driver_load_route(frm);

    $('#cab-driver-refresh-btn').off('click').on('click', function() {
        _driver_load_route(frm);
    });
}

function _driver_clear_layers() {
    _driver_layers.forEach(function(l){ if (_driver_map) _driver_map.removeLayer(l); });
    _driver_layers = [];
}

function _driver_load_route(frm) {
    $('#cab-driver-info').html('<span style="color:#0d6efd;">🔄 Loading your route...</span>');
    $('#cab-driver-passengers').html('');
    _driver_clear_layers();

    frappe.call({
        method: 'transport_management.transport_management.doctype.cab_request.cab_request.get_driver_route_details',
        callback: function(r) {
            if (r.exc || !r.message) {
                $('#cab-driver-info').html('<span style="color:#dc3545;">⚠️ Error loading route. Check console.</span>');
                return;
            }
            if (!r.message.has_route) {
                $('#cab-driver-info').html('<span style="color:#856404;">⚠️ No active route assigned to you for today.</span>');
                return;
            }
            _driver_render_route(r.message);
        }
    });
}

function _driver_render_route(data) {
    var route     = data.route;
    var employees = data.employees || [];
    var ROUTE_COLOR = '#198754';
    var bounds_pts  = [];

    $('#cab-driver-info').html(
        '🛣️ <b>' + route.route_name + '</b> &nbsp;|&nbsp; ' +
        '🚌 ' + (route.vehicle || '—') + ' &nbsp;|&nbsp; ' +
        '⏰ Shift: ' + (route.shift_time || '—') + ' &nbsp;|&nbsp; ' +
        '💺 Passengers today: <b>' + employees.length + '</b>'
    );

    var wps = (route.waypoints || []).slice().sort(function(a,b){ return a.sequence - b.sequence; });
    var valid_wps = wps.filter(function(w){ return w.latitude && w.longitude; });

    valid_wps.forEach(function(wp, i) {
        bounds_pts.push([wp.latitude, wp.longitude]);
        var is_start = (i === 0), is_end = (i === valid_wps.length - 1);
        var lbl = is_start ? 'S' : is_end ? 'E' : String(i+1);
        var bg  = is_start ? '#198754' : is_end ? '#dc3545' : ROUTE_COLOR;
        var m = L.marker([wp.latitude, wp.longitude], {
            icon: L.divIcon({
                html: `<div style="background:${bg};color:#fff;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.3);">${lbl}</div>`,
                iconSize: [26, 26], iconAnchor: [13, 13], className: ''
            })
        }).addTo(_driver_map)
          .bindPopup(
            '<b>' + (wp.stop_name || 'Stop ' + (i+1)) + '</b>' +
            (wp.pickup_time ? '<br>⏰ Pickup Time: <b>' + wp.pickup_time + '</b>' : '') +
            '<br><small>' + (is_start ? '🟢 START' : is_end ? '🔴 END' : '🔵 STOP') + '</small>'
          );
        _driver_layers.push(m);
    });

    if (valid_wps.length >= 2) {
        var coords_str = valid_wps.map(function(wp){ return wp.longitude + ',' + wp.latitude; }).join(';');
        fetch('https://router.project-osrm.org/route/v1/driving/' + coords_str + '?overview=full&geometries=geojson')
            .then(function(r){ return r.json(); })
            .then(function(osrm) {
                if (!osrm.routes || !osrm.routes.length) return;
                var km = parseFloat((osrm.routes[0].distance / 1000).toFixed(1));
                var road_line = L.geoJSON(osrm.routes[0].geometry, {
                    style: { color: ROUTE_COLOR, weight: 5, opacity: 0.85 }
                }).addTo(_driver_map).bindPopup('🛣️ ' + route.route_name + '<br>📏 ' + km + ' km (road distance)');
                _driver_layers.push(road_line);
                _driver_map.fitBounds(road_line.getBounds().pad(0.15));
            }).catch(function() {
                var poly = L.polyline(valid_wps.map(function(wp){ return [wp.latitude, wp.longitude]; }),
                    { color: ROUTE_COLOR, weight: 4, opacity: 0.8, dashArray: '8,5' }).addTo(_driver_map);
                _driver_layers.push(poly);
                if (bounds_pts.length) _driver_map.fitBounds(L.latLngBounds(bounds_pts).pad(0.15));
            });
    }

    employees.forEach(function(emp, idx) {
        if (!emp.pickup_lat || !emp.pickup_lng) return;
        bounds_pts.push([emp.pickup_lat, emp.pickup_lng]);

        var emp_color = emp.status === 'In Trip' ? '#0d6efd' : emp.status === 'Assigned' ? '#198754' : '#fd7e14';

        var emp_icon = L.divIcon({
            html: `<div style="background:${emp_color};color:#fff;border-radius:50%;width:28px;height:28px;
                   display:flex;align-items:center;justify-content:center;font-size:14px;
                   border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.3);">👤</div>`,
            iconSize: [30, 30], iconAnchor: [15, 15], className: ''
        });

        var emp_m = L.marker([emp.pickup_lat, emp.pickup_lng], { icon: emp_icon })
            .addTo(_driver_map)
            .bindPopup(
                `<div style="min-width:200px;">
                <b style="font-size:13px;">👤 ${emp.employee_name || '—'}</b>
                <hr style="margin:5px 0;">
                <table style="font-size:12px;width:100%;border-collapse:collapse;">
                    <tr><td>📍 Pickup:</td><td><b>${emp.pickup_location || '—'}</b></td></tr>
                    <tr><td>📞 Contact:</td><td><b>${emp.contact_no || '—'}</b></td></tr>
                    <tr><td>🔘 Status:</td><td><span style="background:${emp_color};color:#fff;padding:1px 6px;border-radius:4px;font-size:11px;">${emp.status}</span></td></tr>
                    <tr><td>📏 From route:</td><td>${emp.distance_from_route ? emp.distance_from_route + ' km' : '—'}</td></tr>
                    <tr><td>📋 Booking:</td><td><small>${emp.docname}</small></td></tr>
                </table>
                </div>`
            );
        _driver_layers.push(emp_m);

        if (valid_wps.length) {
            var nearest = valid_wps.reduce(function(best, wp) {
                var d = Math.pow(wp.latitude - emp.pickup_lat, 2) + Math.pow(wp.longitude - emp.pickup_lng, 2);
                return d < best.d ? {wp, d} : best;
            }, {wp: valid_wps[0], d: Infinity}).wp;
            var dash_line = L.polyline([[emp.pickup_lat, emp.pickup_lng], [nearest.latitude, nearest.longitude]], {
                color: emp_color, weight: 2, opacity: 0.6, dashArray: '5,5'
            }).addTo(_driver_map);
            _driver_layers.push(dash_line);
        }
    });

    setTimeout(function(){ _driver_map.invalidateSize(); }, 200);

    var pax_html = '';
    if (employees.length) {
        pax_html = '<div style="font-size:13px;font-weight:600;color:#495057;margin-bottom:8px;">👥 Today\'s Passengers (' + employees.length + '):</div>';
        employees.forEach(function(emp) {
            var emp_color = emp.status === 'In Trip' ? '#0d6efd' : emp.status === 'Assigned' ? '#198754' : '#fd7e14';
            pax_html += `<div class="cab-passenger-card">
                <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:6px;">
                    <div style="font-size:13px;font-weight:600;color:#1a1a2e;">👤 ${emp.employee_name || '—'}</div>
                    <span style="background:${emp_color};color:#fff;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:700;">${emp.status}</span>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;font-size:12px;color:#495057;">
                    <div>📍 ${emp.pickup_location || '—'}</div>
                    <div>📞 ${emp.contact_no || '—'}</div>
                    <div>📏 ${emp.distance_from_route ? emp.distance_from_route + ' km from route' : '—'}</div>
                    <div>🗓️ ${emp.booking_datetime ? emp.booking_datetime.split(' ')[0] : '—'}</div>
                </div>
                <button onclick="_driver_zoom_to_emp(${emp.pickup_lat}, ${emp.pickup_lng})"
                    style="margin-top:8px;background:#198754;color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:12px;cursor:pointer;">
                    📍 Show on Map
                </button>
            </div>`;
        });
    } else {
        pax_html = '<div style="background:#fff8e1;border-left:4px solid #ffc107;border-radius:8px;padding:10px 14px;font-size:13px;color:#795548;">No passengers booked on your route for today.</div>';
    }
    $('#cab-driver-passengers').html(pax_html);
}

window._driver_zoom_to_emp = function(lat, lng) {
    if (_driver_map) _driver_map.setView([lat, lng], 16);
};


// ============================================================
//  EMPLOYEE ROUTE TRACKER
// ============================================================

var _emp_tracker_map    = null;
var _emp_tracker_layers = [];

function _show_employee_route_tracker(frm) {
    $('#cab-emp-tracker-panel').show();

    if (!_emp_tracker_map) {
        _emp_tracker_map = L.map('cab-emp-tracker-map-el').setView([13.0827, 80.2707], 11);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap', maxZoom: 19
        }).addTo(_emp_tracker_map);
    }

    _emp_tracker_load(frm);

    $('#cab-emp-tracker-refresh-btn').off('click').on('click', function() {
        _emp_tracker_load(frm);
    });
}

function _emp_tracker_clear() {
    _emp_tracker_layers.forEach(function(l){ if (_emp_tracker_map) _emp_tracker_map.removeLayer(l); });
    _emp_tracker_layers = [];
}

function _emp_tracker_load(frm) {
    $('#cab-emp-tracker-info').html('<span style="color:#28a745;">🔄 Loading your route...</span>');
    $('#cab-emp-tracker-stops').html('');
    _emp_tracker_clear();

    const route_name = frm.doc.assigned_route;

    if (!route_name) {
        $('#cab-emp-tracker-info').html('<span style="color:#856404;">⚠️ No route assigned yet.</span>');
        return;
    }

    frappe.call({
        method: 'frappe.client.get',
        args: { doctype: 'Cab Route', name: route_name },
        callback: function(r) {
            if (!r.message) {
                $('#cab-emp-tracker-info').html('<span style="color:#dc3545;">⚠️ Could not load route details.</span>');
                return;
            }
            _emp_tracker_render(frm, r.message);
        }
    });
}

function _emp_tracker_render(frm, route) {
    const ROUTE_COLOR = '#0d6efd';
    const bounds_pts  = [];

    const waypoints_raw = route.waypoints || [];
    const sorted_wps = waypoints_raw.slice().sort(function(a, b){ return (a.sequence || 0) - (b.sequence || 0); });

    const all_wps = [
        { stop_name: route.start_location, latitude: parseFloat(route.start_lat),  longitude: parseFloat(route.start_lng),  sequence: 0,    pickup_time: route.shift_time || '', is_start: true  },
        ...sorted_wps.map(w => ({ ...w, latitude: parseFloat(w.latitude), longitude: parseFloat(w.longitude) })),
        { stop_name: route.end_location,   latitude: parseFloat(route.end_lat),    longitude: parseFloat(route.end_lng),    sequence: 9999, pickup_time: '',                    is_end: true    }
    ].filter(w => w.latitude && w.longitude && !isNaN(w.latitude) && !isNaN(w.longitude));

    if (all_wps.length < 2) {
        $('#cab-emp-tracker-info').html('<span style="color:#856404;">⚠️ Route has insufficient waypoints.</span>');
        return;
    }

    const status_color = frm.doc.status === 'In Trip' ? '#0d6efd' : '#28a745';
    $('#cab-emp-tracker-info').html(
        `🛣️ <b>${route.route_name || frm.doc.assigned_route}</b> &nbsp;|&nbsp; ` +
        `🚌 <b>${frm.doc.assigned_cab || '—'}</b> &nbsp;|&nbsp; ` +
        `👤 Driver: <b>${frm.doc.assigned_driver || '—'}</b> &nbsp;|&nbsp; ` +
        `⏰ Shift: <b>${route.shift_time || '—'}</b> &nbsp;|&nbsp; ` +
        `<span style="background:${status_color};color:#fff;padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700;">${frm.doc.status}</span>`
    );

    all_wps.forEach(function(wp, i) {
        bounds_pts.push([wp.latitude, wp.longitude]);
        const is_start = (i === 0);
        const is_end   = (i === all_wps.length - 1);
        const lbl = is_start ? 'S' : is_end ? 'E' : String(i);
        const bg  = is_start ? '#198754' : is_end ? '#dc3545' : ROUTE_COLOR;

        const m = L.marker([wp.latitude, wp.longitude], {
            icon: L.divIcon({
                html: `<div style="background:${bg};color:#fff;border-radius:50%;width:22px;height:22px;
                       display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;
                       border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3);">${lbl}</div>`,
                iconSize: [24, 24], iconAnchor: [12, 12], className: ''
            })
        }).addTo(_emp_tracker_map)
          .bindPopup(
            `<b>${wp.stop_name || 'Stop ' + i}</b>` +
            (wp.pickup_time ? `<br>⏰ Pickup: <b>${wp.pickup_time}</b>` : '') +
            `<br><small>${is_start ? '🟢 START' : is_end ? '🔴 END' : '🔵 STOP'}</small>`
          );
        _emp_tracker_layers.push(m);
    });

    const coords_str = all_wps.map(w => `${w.longitude},${w.latitude}`).join(';');
    fetch(`https://router.project-osrm.org/route/v1/driving/${coords_str}?overview=full&geometries=geojson`)
        .then(r => r.json())
        .then(function(osrm) {
            if (!osrm.routes || !osrm.routes.length) return;
            const km = parseFloat((osrm.routes[0].distance / 1000).toFixed(1));
            const total_min = Math.round(osrm.routes[0].duration / 60);
            const h = Math.floor(total_min / 60), m = total_min % 60;
            const eta = h > 0 ? `${h}h ${m}m` : `${m} min`;

            const road_line = L.geoJSON(osrm.routes[0].geometry, {
                style: { color: ROUTE_COLOR, weight: 5, opacity: 0.85 }
            }).addTo(_emp_tracker_map)
              .bindPopup(`🛣️ ${route.route_name || frm.doc.assigned_route}<br>📏 ${km} km &nbsp;|&nbsp; ⏱ ${eta}`);
            _emp_tracker_layers.push(road_line);

            const all_pts = [...bounds_pts];
            if (frm._pickup_coords) all_pts.push(frm._pickup_coords);
            if (all_pts.length) _emp_tracker_map.fitBounds(L.latLngBounds(all_pts).pad(0.15));
        })
        .catch(function() {
            const poly = L.polyline(all_wps.map(w => [w.latitude, w.longitude]),
                { color: ROUTE_COLOR, weight: 4, opacity: 0.8, dashArray: '8,5' }).addTo(_emp_tracker_map);
            _emp_tracker_layers.push(poly);
            if (bounds_pts.length) _emp_tracker_map.fitBounds(L.latLngBounds(bounds_pts).pad(0.15));
        });

    let emp_lat = frm._pickup_coords ? frm._pickup_coords[0] : parseFloat(frm.doc.pickup_lat);
    let emp_lng = frm._pickup_coords ? frm._pickup_coords[1] : parseFloat(frm.doc.pickup_lng);

    if (emp_lat && emp_lng && !isNaN(emp_lat) && !isNaN(emp_lng)) {
        bounds_pts.push([emp_lat, emp_lng]);

        const emp_icon = L.divIcon({
            html: `<div style="background:#6f42c1;color:#fff;border-radius:50%;width:28px;height:28px;
                   display:flex;align-items:center;justify-content:center;font-size:15px;
                   border:3px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.35);">📍</div>`,
            iconSize: [30, 30], iconAnchor: [15, 15], className: ''
        });

        const emp_m = L.marker([emp_lat, emp_lng], { icon: emp_icon })
            .addTo(_emp_tracker_map)
            .bindPopup(
                `<div style="min-width:180px;">
                <b>📍 Your Pickup</b><br>
                <span style="font-size:12px;color:#495057;">${frm.doc.pickup_location || '—'}</span><br>
                <span style="font-size:11px;color:#6c757d;">📏 ${frm.doc.distance_from_route ? frm.doc.distance_from_route + ' km from route' : '—'}</span>
                </div>`
            )
            .openPopup();
        _emp_tracker_layers.push(emp_m);

        if (all_wps.length) {
            const nearest = all_wps.reduce(function(best, wp) {
                const d = Math.pow(wp.latitude - emp_lat, 2) + Math.pow(wp.longitude - emp_lng, 2);
                return d < best.d ? { wp, d } : best;
            }, { wp: all_wps[0], d: Infinity }).wp;

            const dash = L.polyline([[emp_lat, emp_lng], [nearest.latitude, nearest.longitude]], {
                color: '#6f42c1', weight: 2.5, opacity: 0.75, dashArray: '6,5'
            }).addTo(_emp_tracker_map)
              .bindPopup(`📏 ~${frm.doc.distance_from_route || '?'} km to nearest stop`);
            _emp_tracker_layers.push(dash);
        }
    } else if (frm.doc.pickup_location) {
        fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(frm.doc.pickup_location)}&format=json&limit=1`,
            { headers: { 'Accept-Language': 'en' } })
            .then(r => r.json())
            .then(function(data) {
                if (!data || !data[0]) return;
                emp_lat = parseFloat(data[0].lat);
                emp_lng = parseFloat(data[0].lon);
                frm._pickup_coords = [emp_lat, emp_lng];
                _emp_tracker_render(frm, route);
            }).catch(() => {});
        return;
    }

    setTimeout(function(){ _emp_tracker_map.invalidateSize(); }, 200);

    let stops_html = '<div style="font-size:12px;font-weight:600;color:#495057;margin-bottom:8px;">🛑 Route Stops:</div>';
    stops_html += '<div style="display:flex;flex-wrap:wrap;gap:6px;">';
    all_wps.forEach(function(wp, i) {
        const is_start = (i === 0), is_end = (i === all_wps.length - 1);
        const bg = is_start ? '#d4edda' : is_end ? '#f8d7da' : '#e9ecef';
        const clr = is_start ? '#155724' : is_end ? '#721c24' : '#495057';
        stops_html += `<div style="background:${bg};color:${clr};border-radius:8px;padding:6px 12px;font-size:12px;font-weight:500;">
            <b>${i + 1}.</b> ${wp.stop_name || 'Stop ' + i}
            ${wp.pickup_time ? `<br><span style="font-size:10px;opacity:0.8;">⏰ ${wp.pickup_time}</span>` : ''}
        </div>`;
    });
    stops_html += '</div>';

    if (emp_lat && emp_lng && !isNaN(emp_lat)) {
        const nearest = all_wps.reduce(function(best, wp, i) {
            const d = Math.pow(wp.latitude - emp_lat, 2) + Math.pow(wp.longitude - emp_lng, 2);
            return d < best.d ? { wp, d, i } : best;
        }, { wp: all_wps[0], d: Infinity, i: 0 });
        stops_html += `<div style="margin-top:8px;background:#e8f4fd;border-left:4px solid #0d6efd;border-radius:6px;padding:8px 12px;font-size:12px;color:#0c5480;">
            📍 Your nearest boarding stop: <b>${nearest.wp.stop_name || 'Stop ' + nearest.i}</b>
            ${nearest.wp.pickup_time ? ` &nbsp;⏰ <b>${nearest.wp.pickup_time}</b>` : ''}
        </div>`;
    }

    $('#cab-emp-tracker-stops').html(stops_html);
}


// ── END OF FILE ────────────────────────────────────────────────────────────
