# Copyright (c) 2026, our team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class VehicleGPSLog(Document):
    """A single GPS position reading for a vehicle.

    Rows are created by the api.gps.update_vehicle_location ingest endpoint
    (driver app / GPS device) and pruned by the daily purge_old_gps_logs job.
    """

    def validate(self):
        self._validate_coordinates()
        if not self.recorded_at:
            self.recorded_at = now_datetime()

    def _validate_coordinates(self):
        if not (-90 <= flt(self.latitude) <= 90):
            frappe.throw(
                _("Latitude {0} is out of range — must be between -90 and 90.").format(
                    self.latitude),
                title=_("Invalid Coordinates"),
            )
        if not (-180 <= flt(self.longitude) <= 180):
            frappe.throw(
                _("Longitude {0} is out of range — must be between -180 and 180.").format(
                    self.longitude),
                title=_("Invalid Coordinates"),
            )
