frappe.ui.form.on("Cab Request", {

    setup: function(frm) {
        // Check roles once when the form sets up
        frm.is_employee = frappe.user.has_role("Employee");
        frm.is_driver = frappe.user.has_role("Driver");
        frm.is_manager = frappe.user.has_role("Fleet Manager") || frappe.user.has_role("System Manager");
    },

    onload: function(frm) {
        // 1. AUTO-FETCH EMPLOYEE DETAILS (Only for new documents created by Employees)
        if (frm.is_new() && frm.is_employee && !frm.is_manager) {
            frappe.call({
                method: "transport_management.transport_management.doctype.cab_request.cab_request.get_employee_basic_details",
                callback: function(r) {
                    if (r.message) {
                        frm.set_value("employee_id", r.message.name);
                        frm.set_value("employee_name", r.message.employee_name);
                        frm.set_value("department", r.message.department);
                        frm.set_value("contact_no", r.message.mobile_no);
                    }
                }
            });
        }

        // ── ROLE-BASED STATUS DROPDOWN FILTER ──
        if (frm.is_driver && !frm.is_manager) {
            frm.set_df_property("status", "options", "In Trip\nCompleted\nCancelled");
        } else if (frm.is_manager) {
            frm.set_df_property("status", "options", "Pending\nAssigned\nRejected\nCancelled\nIn Trip\nCompleted");
        } else {
            frm.set_df_property("status", "options", "Pending\nAssigned\nRejected\nCancelled");
        }
    },

    refresh: function(frm) {

        // 4. LOGIC FOR FLEET MANAGER VIEW — runs FIRST with return to prevent override
        if (frm.is_manager) {
            // Manager sees everything — unhide allocation fields
            frm.set_df_property("driver_id", "hidden", 0);
            frm.set_df_property("cab", "hidden", 0);
            frm.set_df_property("assigned_driver", "hidden", 0);
            frm.set_df_property("assigned_cab", "hidden", 0);

            // These are auto-set by code, so make them read-only for manager too
            frm.set_df_property("assigned_driver", "read_only", 1);
            frm.set_df_property("assigned_cab", "read_only", 1);

            // Force refresh so fields actually render visible
            frm.refresh_field("driver_id");
            frm.refresh_field("cab");
            frm.refresh_field("assigned_driver");
            frm.refresh_field("assigned_cab");

            // ── Force Manager status options on every refresh ──
            frm.set_df_property("status", "options", "Pending\nAssigned\nRejected\nCancelled\nIn Trip\nCompleted");
            frm.refresh_field("status");

            // Show/hide rejection reason based on status
            if (frm.doc.status === "Rejected") {
                frm.set_df_property("rejection_reason", "hidden", 0);
                frm.set_df_property("rejection_reason", "reqd", 1);
            } else {
                frm.set_df_property("rejection_reason", "hidden", 1);
                frm.set_df_property("rejection_reason", "reqd", 0);
            }
            frm.refresh_field("rejection_reason");

            return; // IMPORTANT: Stop here so Employee/Driver blocks don't override
        }

        // 3. LOGIC FOR DRIVER VIEW
        if (frm.is_driver) {
            // ── Force Driver status options on every refresh ──
            frm.set_df_property("status", "options", "In Trip\nCompleted\nCancelled");
            frm.refresh_field("status");

            // Make the ENTIRE form read-only
            frm.set_read_only(true);

            // Explicitly lock key fields
            frm.set_df_property("status", "read_only", 1);
            frm.set_df_property("pickup_location", "read_only", 1);
            frm.set_df_property("drop_location", "read_only", 1);
            frm.set_df_property("booking_datetime", "read_only", 1);
            frm.set_df_property("employee_name", "read_only", 1);
            frm.set_df_property("contact_no", "read_only", 1);

            // Hide internal allocation fields
            frm.set_df_property("rejection_reason", "hidden", 1);
            frm.set_df_property("driver_id", "hidden", 1);

            // Remove Save button
            frm.disable_save();

            // ── "Start Trip" button ──
            if (frm.doc.status === "Assigned") {
                frm.add_custom_button(__("Start Trip"), function() {
                    frappe.confirm(
                        "Are you sure you want to <b>Start</b> this trip? This will change status to <b>In Trip</b>.",
                        function() {
                            frappe.call({
                                method: "transport_management.transport_management.doctype.cab_request.cab_request.driver_start_trip",
                                args: { docname: frm.doc.name },
                                callback: function(r) {
                                    if (!r.exc) {
                                        frappe.show_alert({
                                            message: "Trip started! Status is now In Trip.",
                                            indicator: "blue"
                                        }, 5);
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }).addClass("btn-primary");
            }

            // ── "Complete Trip" button ──
            if (frm.doc.status === "In Trip") {
                frm.add_custom_button(__("Complete Trip"), function() {
                    frappe.confirm(
                        "Are you sure you want to mark this trip as <b>Completed</b>?",
                        function() {
                            frappe.call({
                                method: "transport_management.transport_management.doctype.cab_request.cab_request.driver_complete_trip",
                                args: { docname: frm.doc.name },
                                callback: function(r) {
                                    if (!r.exc) {
                                        frappe.show_alert({
                                            message: "Trip marked as Completed successfully!",
                                            indicator: "green"
                                        }, 5);
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }).addClass("btn-success");
            }

            return; // IMPORTANT: Stop here so Employee block doesn't override
        }

        // 2. LOGIC FOR EMPLOYEE VIEW (runs only if not Manager and not Driver)
        if (frm.is_employee) {
            // Hide the Manager's Allocation controls
            frm.set_df_property("driver_id", "hidden", 1);
            frm.set_df_property("cab", "hidden", 1);

            // Only show Rejection Reason if actually rejected
            if (frm.doc.status === "Rejected") {
                frm.set_df_property("rejection_reason", "hidden", 0);
            } else {
                frm.set_df_property("rejection_reason", "hidden", 1);
            }

            // Only show Assigned details if Assigned, In Trip or Completed
            if (["Assigned", "In Trip", "Completed"].includes(frm.doc.status)) {
                frm.set_df_property("assigned_driver", "hidden", 0);
                frm.set_df_property("assigned_cab", "hidden", 0);
            } else {
                frm.set_df_property("assigned_driver", "hidden", 1);
                frm.set_df_property("assigned_cab", "hidden", 1);
            }

            // Employee status is always read-only
            frm.set_df_property("status", "read_only", 1);

            // ── "Cancel Trip" button: Employee can cancel ONLY when status is Assigned ──
            if (frm.doc.status === "Assigned") {
                frm.add_custom_button(__("Cancel Trip"), function() {
                    frappe.confirm(
                        "Are you sure you want to <b>Cancel</b> this cab request?",
                        function() {
                            frappe.call({
                                method: "transport_management.transport_management.doctype.cab_request.cab_request.employee_cancel_trip",
                                args: { docname: frm.doc.name },
                                callback: function(r) {
                                    if (!r.exc) {
                                        frappe.show_alert({
                                            message: "Trip cancelled successfully.",
                                            indicator: "orange"
                                        }, 5);
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }).addClass("btn-danger");
            }
        }
    },

    // 5. VALIDATE: Driver and Cab must be assigned before saving when status is Assigned
    before_save: function(frm) {
        if (frm.is_manager && frm.doc.status === "Assigned") {
            if (!frm.doc.driver_id) {
                frappe.throw(__("Please assign a <b>Driver</b> before setting status to Assigned."));
            }
            if (!frm.doc.cab) {
                frappe.throw(__("Please assign a <b>Cab</b> before setting status to Assigned."));
            }
        }
    },

    // 6. UX: Show Rejection Reason box immediately when Manager selects "Rejected"
    status: function(frm) {
        if (frm.doc.status === "Rejected") {
            frm.set_df_property("rejection_reason", "hidden", 0);
            frm.set_df_property("rejection_reason", "reqd", 1);
        } else {
            frm.set_df_property("rejection_reason", "hidden", 1);
            frm.set_df_property("rejection_reason", "reqd", 0);
        }
    }
});
