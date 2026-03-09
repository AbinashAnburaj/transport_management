frappe.ui.form.on("Vehicle Log", {
	odometer(frm) {
		set_daily_distance(frm);
	},

	last_odometer(frm) {
		set_daily_distance(frm);
	},

	end_odometer(frm) {
		set_daily_distance(frm);
	},

	license_plate(frm) {
		clear_last_odometer_if_driver_new(frm);
	},

	setup(frm) {
		if (!is_driver_only()) return;

		frm.set_query("license_plate", () => {
			if (!frm._driver_license_plate) return {};
			return { filters: { name: frm._driver_license_plate } };
		});
	},

	refresh(frm) {
		toggle_invoice_bill_upload(frm);
		if (!is_driver_only()) return;

		lock_driver_fields(frm);
		load_driver_defaults(frm);
	},

	onload(frm) {
		toggle_invoice_bill_upload(frm);
		if (!is_driver_only()) return;
		clear_last_odometer_if_driver_new(frm);
		if (frm.is_new() && !frm.doc.approval_status) {
			frm.set_value("approval_status", "Pending");
		}
		set_daily_distance(frm);
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
		if (frm.get_field(field)) {
			frm.set_df_property(field, "read_only", 1);
		}
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
				if (frm.get_field("license_plate") && !frm.doc.license_plate) {
					frm.set_value("license_plate", d.license_plate);
				}
			}
			if (d.employee && frm.get_field("employee")) frm.set_value("employee", d.employee);
			if (d.driver_id && frm.get_field("driver_id")) frm.set_value("driver_id", d.driver_id);
			if (d.driver_name && frm.get_field("driver_name")) frm.set_value("driver_name", d.driver_name);
			if (!frm.doc.approval_status && frm.get_field("approval_status")) {
				frm.set_value("approval_status", "Pending");
			}
		},
	});
}

function set_daily_distance(frm) {
	const current = frm.doc.odometer;
	let last = frm.doc.last_odometer;
	if (last == null) last = frm.doc.end_odometer;
	if (current == null || last == null) return;

	const start = flt(frm.doc.odometer);
	const prior = flt(last);
	const distance = Math.max(start - prior, 0);
	if (frm.get_field("daily_distance")) {
		frm.set_value("daily_distance", distance);
	} else if (frm.get_field("total_distance")) {
		frm.set_value("total_distance", distance);
	}
}

function toggle_invoice_bill_upload(frm) {
	const field = frm.get_field("invoice_bill");
	if (!field) return;

	frm.set_df_property("invoice_bill", "hidden", 0);

	if (frm.is_new()) {
		frm.set_df_property("invoice_bill", "read_only", 1);
		frm.set_df_property("invoice_bill", "description", "Save this Vehicle Log once, then attach invoice bill.");
		return;
	}

	frm.set_df_property("invoice_bill", "read_only", 0);
	frm.set_df_property("invoice_bill", "description", "");
}

function clear_last_odometer_if_driver_new(frm) {
	if (!is_driver_only() || !frm.is_new()) return;
	if (!frm.get_field("last_odometer")) return;
	if (frm.doc.last_odometer) {
		frm.set_value("last_odometer", null);
	}
}
