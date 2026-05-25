app_name = "transport_management"
app_title = "Transport Management"  # <--- THIS LINE IS MISSING IN YOUR FILE
app_publisher = "our team"
app_description = "Internal cab management system"
app_email = "anbuabinash1@gmail.com"
app_license = "mit"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/transport_management/css/transport_management.css"
# app_include_js = "/assets/transport_management/js/transport_management.js"

# --------------------------
# Permissions
# --------------------------

# This connects the permission logic we wrote in your python file
# permission_query_conditions = {
#     "Cab Request": "transport_management.transport_management.doctype.cab_request.cab_request.get_permission_query_conditions",
# }

permission_query_conditions = {
    "Cab Request": "transport_management.transport_management.doctype.cab_request.cab_request.get_permission_query_conditions",
    "Vehicle Log": "transport_management.transport_management.doctype.vehicle_log.vehicle_log.get_permission_query_conditions",
 }

has_permission = {
    "Cab Request": "transport_management.transport_management.doctype.cab_request.cab_request.has_permission",
    "Vehicle Log": "transport_management.transport_management.doctype.vehicle_log.vehicle_log.has_permission",
    "File": "transport_management.transport_management.permissions.file.has_permission",
}
doctype_js = {
    "Cab Request": ["public/js/map.js", "public/js/driver_gps_pinger.js"],
    "Vehicle Log": "public/js/vehicle_log.js",
}

override_doctype_class = {
    "Vehicle Log": "transport_management.transport_management.doctype.vehicle_log.vehicle_log.VehicleLog",
}

# --------------------------
# Document Events
# --------------------------

doc_events = {
    "Vehicle": {
        "on_update": "transport_management.transport_management.api.vehicle.sync_vehicle_status"
    },
    "Has Role": {
        "after_insert": "transport_management.transport_management.doctype.vehicle_log.vehicle_log.ensure_vehicle_log_permission_for_driver_role"
    },
    "Cab Route": {
        "before_save": "transport_management.transport_management.doctype.cab_request.cab_request.generate_route_geojson"
    },
}

# --------------------------
# Scheduled Tasks
# --------------------------

scheduler_events = {
    "daily": [
        "transport_management.transport_management.automation.compliance.daily_compliance_check",
        "transport_management.transport_management.automation.maintenance.daily_maintenance_check",
        "transport_management.transport_management.api.gps.purge_old_gps_logs",
    ],
    "monthly": [
        "transport_management.transport_management.billing.vendor_billing.monthly_vendor_billing",
    ],
}

# --------------------------
# Fixtures (round-trip the Manager Live Map block and friends through git)
# --------------------------

fixtures = [
    {
        "doctype": "Custom HTML Block",
        "filters": [["name", "in", ["Manager Live Map"]]],
    },
]
