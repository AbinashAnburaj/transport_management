// Copyright (c) 2026, our team and contributors
// For license information, please see license.txt

frappe.query_reports["Vendor Billing Reconciliation"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "vendor",
			label: __("Vendor"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			fieldname: "billing_status",
			label: __("Billing Status"),
			fieldtype: "Select",
			options: ["", "Pending", "Billed", "No Vendor", "No Rate", "No Distance"].join("\n"),
		},
	],

	onload: function (report) {
		report.page.add_inner_button(__("Generate Vendor Invoices"), function () {
			const vendor = report.get_filter_value("vendor");
			frappe.confirm(
				__("Generate vendor invoices for all billable (Pending) trips{0}?", [
					vendor ? __(" for {0}", [vendor]) : "",
				]),
				function () {
					frappe.call({
						method: "transport_management.transport_management.billing.vendor_billing.generate_vendor_invoices",
						args: { vendor: vendor || null },
						freeze: true,
						freeze_message: __("Generating vendor invoices..."),
						callback: function () {
							report.refresh();
						},
					});
				}
			);
		}).addClass("btn-primary");
	},
};
