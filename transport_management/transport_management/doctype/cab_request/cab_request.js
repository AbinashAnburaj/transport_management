frappe.ui.form.on('Cab Request', {

    onload: function(frm) {
        // Only for new document
        if (!frm.is_new()) return;

        frappe.call({
            method: "transport_management.transport_management.doctype.cab_request.cab_request.get_employee_basic_details",
            callback: function(r) {
                if (r.message) {
                    frm.set_value("employee_id", r.message.name);
                    frm.set_value("employee_name", r.message.employee_name);
                    frm.set_value("department", r.message.department);
                    frm.set_value("contact_no", r.message.cell_number);
                    }
            }
        });
    }

});