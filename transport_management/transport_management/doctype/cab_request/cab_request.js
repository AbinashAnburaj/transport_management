frappe.ui.form.on('Cab Request', {
    onload: function (frm) {
        autofill_employee(frm);
    },
    refresh: function (frm) {
        autofill_employee(frm);
        _setup_manager_buttons(frm);
    },
});

// ── Manager-only action buttons ────────────────────────────────────────────
function _setup_manager_buttons(frm) {
    // Only show for Fleet Manager / System Manager on a saved, Assigned booking.
    const is_manager = (frappe.user_roles || []).some(function(r) {
        return r === "Fleet Manager" || r === "System Manager";
    });
    if (!is_manager) return;
    if (frm.is_new()) return;
    if (frm.doc.status !== "Assigned") return;

    frm.add_custom_button(__("Reset OTP Attempts"), function () {
        frappe.confirm(
            __("Clear the OTP attempt counter for <b>{0}</b>? The driver will be able to try again immediately.", [frm.doc.name]),
            function () {
                frappe.call({
                    method: "transport_management.transport_management.doctype.cab_request.cab_request.reset_otp_attempts",
                    args: { docname: frm.doc.name },
                    freeze: true,
                    freeze_message: __("Resetting OTP attempts..."),
                    callback: function (r) {
                        if (r.message && r.message.status === "success") {
                            frappe.show_alert({
                                message: __("OTP attempt counter reset. Driver can try again."),
                                indicator: "green",
                            }, 5);
                        } else {
                            frappe.msgprint({
                                title: __("Error"),
                                message: (r.message && r.message.message) || __("Could not reset OTP attempts."),
                                indicator: "red",
                            });
                        }
                    },
                });
            }
        );
    }, __("Actions"));
}

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
