frappe.ui.form.on('Cab Request', {
    onload: function (frm) {
        autofill_employee(frm);
    },
    refresh: function (frm) {
        autofill_employee(frm);
    },
});

function autofill_employee(frm) {
    // Auto-fetch the logged-in employee's details on a NEW Cab Request.
    // Runs on both onload and refresh so the values reliably stick, and
    // skips once filled so a manually-changed value is never clobbered.
    if (!frm.is_new() || frm.__employee_autofilled) {
        return;
    }
    if (frm.doc.employee_name && frm.doc.contact_no) {
        frm.__employee_autofilled = true;
        return;
    }

    frappe.call({
        method: "transport_management.transport_management.doctype.cab_request.cab_request.get_employee_basic_details",
        callback: function (r) {
            const emp = r && r.message;
            if (!emp) {
                return;
            }
            frm.__employee_autofilled = true;
            if (emp.name)           frm.set_value("employee_id", emp.name);
            if (emp.employee_name)  frm.set_value("employee_name", emp.employee_name);
            if (emp.department)     frm.set_value("department", emp.department);
            if (emp.cell_number)    frm.set_value("contact_no", emp.cell_number);
            if (emp.personal_email) frm.set_value("employee_mail_id", emp.personal_email);
        },
    });
}
