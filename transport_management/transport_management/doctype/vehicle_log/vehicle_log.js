frappe.ui.form.on("Vehicle Log", {
	setup(frm) {
		if (!is_driver_only()) return;

		frm.set_query("license_plate", () => {
			if (!frm._driver_license_plate) return {};
			return { filters: { name: frm._driver_license_plate } };
		});
	},

	refresh(frm) {
		if (!is_driver_only()) return;

		lock_driver_fields(frm);
		load_driver_defaults(frm);
	},

	onload(frm) {
		if (!is_driver_only()) return;
		if (frm.is_new() && !frm.doc.approval_status) {
			frm.set_value("approval_status", "Pending");
		}
	},
});

function is_driver_only() {
	return (
		frappe.user.has_role("Driver") &&
		!frappe.user.has_role("Fleet Manager") &&
		!frappe.user.has_role("System Manager")
	);
}

function lock_driver_fields(frm) {
	["license_plate", "employee", "driver_id", "driver_name", "approval_status"].forEach((field) => {
		frm.set_df_property(field, "read_only", 1);
	});
}

function load_driver_defaults(frm) {
	frappe.call({
		method: "transport_management.transport_management.doctype.vehicle_log.vehicle_log.get_driver_vehicle_defaults",
		callback: (r) => {
			const d = r.message || {};
			if (!d) return;

			if (d.license_plate) {
				frm._driver_license_plate = d.license_plate;
				if (!frm.doc.license_plate) frm.set_value("license_plate", d.license_plate);
			}
			if (d.employee) frm.set_value("employee", d.employee);
			if (d.driver_id) frm.set_value("driver_id", d.driver_id);
			if (d.driver_name) frm.set_value("driver_name", d.driver_name);
			if (!frm.doc.approval_status) frm.set_value("approval_status", "Pending");
		},
	});
}
