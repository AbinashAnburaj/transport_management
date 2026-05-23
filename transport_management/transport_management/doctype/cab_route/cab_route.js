// Copyright (c) 2026, our team and contributors
// For license information, please see license.txt
//
// Cab Route — interactive map picker for Start, End and Waypoints.
// Pick a mode, then search a place or click the map; coordinates are filled
// automatically (no manual lat/lng typing).

frappe.ui.form.on('Cab Route', {
    refresh: function (frm) {
        ensure_leaflet(function () {
            if ($('#croute-picker').length && frm._croute_map) {
                frm._croute_map.invalidateSize();
                redraw_route_map(frm);
            } else {
                build_route_picker(frm);
            }
        });
    },
});

// ── Leaflet loader ──────────────────────────────────────────────────────────
function ensure_leaflet(cb) {
    if (window.L && window.L.map) { cb(); return; }
    if (!document.getElementById('leaflet-css')) {
        $('<link id="leaflet-css" rel="stylesheet" ' +
          'href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">').appendTo('head');
    }
    if (window._leaflet_loading) {
        const t = setInterval(function () {
            if (window.L && window.L.map) { clearInterval(t); cb(); }
        }, 120);
        return;
    }
    window._leaflet_loading = true;
    const s = document.createElement('script');
    s.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    s.onload = cb;
    document.head.appendChild(s);
}

// ── Photon geocoding helper ─────────────────────────────────────────────────
function photon_label(f) {
    const p = (f && f.properties) || {};
    const parts = [p.name, p.street, p.district, p.city, p.county, p.state, p.country];
    const seen = [];
    parts.forEach(function (x) { if (x && seen[seen.length - 1] !== x) seen.push(x); });
    return seen.join(', ');
}

// ── Build the picker panel ──────────────────────────────────────────────────
function build_route_picker(frm) {
    const anchor = frm.fields_dict.route_name && $(frm.fields_dict.route_name.wrapper);
    if (!anchor || !anchor.length) {
        setTimeout(function () { build_route_picker(frm); }, 500);
        return;
    }
    $('#croute-picker').remove();

    anchor.after(`
      <div id="croute-picker" style="margin:14px 0;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px;">
          <button type="button" class="croute-mode" data-mode="start"
            style="border:none;color:#fff;background:#198754;padding:7px 13px;border-radius:7px;font-size:12px;font-weight:600;cursor:pointer;">📍 Set Start</button>
          <button type="button" class="croute-mode" data-mode="end"
            style="border:none;color:#fff;background:#dc3545;padding:7px 13px;border-radius:7px;font-size:12px;font-weight:600;cursor:pointer;">🏁 Set End</button>
          <button type="button" class="croute-mode" data-mode="waypoint"
            style="border:none;color:#fff;background:#0d6efd;padding:7px 13px;border-radius:7px;font-size:12px;font-weight:600;cursor:pointer;">➕ Add Waypoint</button>
          <span id="croute-mode-label" style="font-size:12px;color:#6c757d;font-weight:600;"></span>
        </div>
        <div style="position:relative;margin-bottom:8px;">
          <input id="croute-search" type="text" autocomplete="off"
            placeholder="Search a place — it sets the selected point…"
            style="width:100%;padding:9px 12px;border:1.5px solid #ced4da;border-radius:8px;font-size:13px;box-sizing:border-box;outline:none;">
          <div id="croute-sug" style="position:absolute;z-index:1000;left:0;right:0;background:#fff;border:1px solid #dee2e6;border-radius:8px;margin-top:2px;max-height:210px;overflow:auto;display:none;box-shadow:0 4px 14px rgba(0,0,0,.14);"></div>
        </div>
        <div id="croute-map" style="height:390px;border-radius:10px;border:1.5px solid #dee2e6;overflow:hidden;background:#e8eaed;"></div>
        <div style="font-size:11px;color:#6c757d;margin-top:6px;">
          Choose a mode, then search a place or click the map. Start/End pins are draggable to fine-tune.
        </div>
      </div>
    `);

    frm._croute_mode = 'start';

    const map = L.map('croute-map').setView([20.5937, 78.9629], 5);
    const street = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        { attribution: '© OpenStreetMap', maxZoom: 19 });
    const satellite = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { attribution: '© Esri World Imagery', maxZoom: 19 });
    street.addTo(map);
    L.control.layers({ 'Street': street, 'Satellite': satellite }, {},
        { position: 'topright' }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    frm._croute_map = map;
    frm._croute_layers = [];

    map.on('click', function (e) {
        apply_point(frm, frm._croute_mode, e.latlng.lat, e.latlng.lng, null);
    });

    set_mode(frm, 'start');
    $('.croute-mode').on('click', function () { set_mode(frm, $(this).data('mode')); });
    bind_route_search(frm);

    setTimeout(function () { map.invalidateSize(); redraw_route_map(frm); }, 250);
}

function set_mode(frm, mode) {
    frm._croute_mode = mode;
    const labels = {
        start: 'Setting the route START point',
        end: 'Setting the route END point',
        waypoint: 'Each pick ADDS a waypoint stop',
    };
    $('#croute-mode-label').text('— ' + labels[mode]);
    $('.croute-mode').css('opacity', '0.6').css('outline', 'none');
    $('.croute-mode[data-mode="' + mode + '"]').css('opacity', '1')
        .css('outline', '3px solid rgba(0,0,0,0.18)');
}

// ── Search box ──────────────────────────────────────────────────────────────
function bind_route_search(frm) {
    let timer;
    $('#croute-search').on('input', function () {
        clearTimeout(timer);
        const q = $(this).val().trim();
        if (q.length < 3) { $('#croute-sug').hide().empty(); return; }
        timer = setTimeout(function () {
            fetch('https://photon.komoot.io/api/?q=' + encodeURIComponent(q) + '&limit=6&lang=en')
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    const $box = $('#croute-sug').empty();
                    const feats = (data && data.features) || [];
                    if (!feats.length) { $box.hide(); return; }
                    feats.forEach(function (f) {
                        const label = photon_label(f);
                        const c = (f.geometry && f.geometry.coordinates) || [0, 0];
                        if (!label) { return; }
                        $('<div>').text(label)
                            .css({ padding: '8px 11px', cursor: 'pointer',
                                   'font-size': '12px', 'border-bottom': '1px solid #f0f0f0' })
                            .hover(function () { $(this).css('background', '#f1f5fb'); },
                                   function () { $(this).css('background', '#fff'); })
                            .appendTo($box)
                            .on('click', function () {
                                $('#croute-search').val('');
                                $box.hide().empty();
                                apply_point(frm, frm._croute_mode,
                                    parseFloat(c[1]), parseFloat(c[0]), label);
                            });
                    });
                    $box.show();
                }).catch(function () {});
        }, 250);
    });
    $(document).on('click', function (e) {
        if (!$(e.target).is('#croute-search')) $('#croute-sug').hide();
    });
}

// ── Apply a picked point to Start / End / Waypoint ──────────────────────────
function apply_point(frm, mode, lat, lng, label) {
    function finish(name) {
        if (mode === 'start') {
            frm.set_value('start_location', name);
            frm.set_value('start_lat', lat);
            frm.set_value('start_lng', lng);
        } else if (mode === 'end') {
            frm.set_value('end_location', name);
            frm.set_value('end_lat', lat);
            frm.set_value('end_lng', lng);
        } else {
            let seq = 0;
            (frm.doc.waypoints || []).forEach(function (w) {
                if ((w.sequence || 0) > seq) seq = w.sequence || 0;
            });
            frm.add_child('waypoints', {
                stop_name: name, latitude: lat, longitude: lng, sequence: seq + 1,
            });
            frm.refresh_field('waypoints');
        }
        redraw_route_map(frm);
    }

    if (label) {
        finish(label);
    } else {
        fetch('https://photon.komoot.io/reverse?lat=' + lat + '&lon=' + lng + '&lang=en')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                const f = d && d.features && d.features[0];
                finish(f ? photon_label(f) : lat.toFixed(5) + ', ' + lng.toFixed(5));
            })
            .catch(function () { finish(lat.toFixed(5) + ', ' + lng.toFixed(5)); });
    }
}

// ── Draw all markers + the route line ───────────────────────────────────────
function pin_icon(color, glyph) {
    return L.divIcon({
        className: '',
        html: '<div style="position:relative;width:30px;height:40px;">' +
              '<div style="position:absolute;left:0;top:0;width:30px;height:30px;background:' + color +
              ';border:3px solid #fff;border-radius:50% 50% 50% 0;transform:rotate(-45deg);' +
              'box-shadow:0 3px 7px rgba(0,0,0,.4);"></div>' +
              '<div style="position:absolute;left:0;top:3px;width:30px;height:22px;text-align:center;' +
              'font-size:13px;font-weight:700;color:#fff;">' + glyph + '</div></div>',
        iconSize: [30, 40], iconAnchor: [15, 40], popupAnchor: [0, -36],
    });
}

function redraw_route_map(frm) {
    const map = frm._croute_map;
    if (!map) return;
    (frm._croute_layers || []).forEach(function (l) { map.removeLayer(l); });
    frm._croute_layers = [];

    const pts = [];
    const add = function (layer) { layer.addTo(map); frm._croute_layers.push(layer); };
    const line_pts = [];

    if (frm.doc.start_lat && frm.doc.start_lng) {
        const c = [frm.doc.start_lat, frm.doc.start_lng];
        const m = L.marker(c, { icon: pin_icon('#198754', 'S'), draggable: true })
            .bindPopup('<b>Start</b><br>' + (frm.doc.start_location || ''));
        m.on('dragend', function (e) {
            const ll = e.target.getLatLng();
            apply_point(frm, 'start', ll.lat, ll.lng, null);
        });
        add(m); pts.push(c); line_pts.push(c);
    }

    const wps = (frm.doc.waypoints || []).slice().sort(function (a, b) {
        return (a.sequence || 0) - (b.sequence || 0);
    });
    wps.forEach(function (w, i) {
        if (!w.latitude || !w.longitude) return;
        const c = [w.latitude, w.longitude];
        add(L.marker(c, { icon: pin_icon('#0d6efd', String(i + 1)) })
            .bindPopup('<b>Stop ' + (i + 1) + '</b><br>' + (w.stop_name || '')));
        pts.push(c); line_pts.push(c);
    });

    if (frm.doc.end_lat && frm.doc.end_lng) {
        const c = [frm.doc.end_lat, frm.doc.end_lng];
        const m = L.marker(c, { icon: pin_icon('#dc3545', 'E'), draggable: true })
            .bindPopup('<b>End</b><br>' + (frm.doc.end_location || ''));
        m.on('dragend', function (e) {
            const ll = e.target.getLatLng();
            apply_point(frm, 'end', ll.lat, ll.lng, null);
        });
        add(m); pts.push(c); line_pts.push(c);
    }

    if (line_pts.length >= 2) {
        add(L.polyline(line_pts, { color: '#0d6efd', weight: 4, opacity: 0.8, dashArray: '8,5' }));
    }
    if (pts.length === 1) map.setView(pts[0], 14);
    else if (pts.length >= 2) map.fitBounds(L.latLngBounds(pts).pad(0.2));
}
