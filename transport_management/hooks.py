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
 }

has_permission = {
    "Cab Request": "transport_management.transport_management.doctype.cab_request.cab_request.has_permission",
}
doctype_js = {"Cab Request": "public/js/map.js"}

# --------------------------
# Document Events
# --------------------------

# We moved all logic (validation, emails, etc.) into the Controller Class (cab_request.py).
# So, we do NOT need doc_events here anymore. Keeping them would cause errors.


doc_events = {
    "Cab Request": {
        "after_save": "transport_management.api.whatsapp.notify_users"
    }
}
doc_events = {
    "Cab Route": {
        "before_save": "transport_management.transport_management.doctype.cab_request.cab_request.generate_route_geojson"
    }
}
