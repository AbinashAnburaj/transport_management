// Copyright (c) 2026, our team and contributors
// For license information, please see license.txt

frappe.query_reports["Driver Performance"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "driver",
			label: __("Driver"),
			fieldtype: "Data",
		},
	],
};
