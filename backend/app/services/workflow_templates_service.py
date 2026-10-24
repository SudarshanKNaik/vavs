from __future__ import annotations

"""Prebuilt workflow templates exposed to frontend quick-start UI."""

from typing import Any


def _n(
    node_id: str,
    node_type: str,
    label: str,
    description: str,
    react_flow_type: str,
    x: int,
    y: int,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": react_flow_type,
        "position": {"x": x, "y": y},
        "data": {
            "label": label,
            "nodeType": node_type,
            "description": description,
            "params": params or {},
        },
    }


def _e(
    edge_id: str,
    source: str,
    target: str,
    source_handle: str | None = None,
) -> dict[str, Any]:
    style = {"stroke": "#C43B3B", "strokeWidth": 2}
    if source_handle == "true":
        style = {"stroke": "#10b981", "strokeWidth": 2}
    elif source_handle == "false":
        style = {"stroke": "#ef4444", "strokeWidth": 2}

    edge: dict[str, Any] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "animated": True,
        "style": style,
    }
    if source_handle:
        edge["sourceHandle"] = source_handle
    return edge


TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "lab-call-schedule-complete",
        "name": "Lab Call to Appointment",
        "description": "When lab results arrive, call patient, schedule appointment, and log completion.",
        "category": "Clinical",
        "use_case": "Lab follow-up booking",
        "nodes": [
            _n(
                "l1",
                "lab_results_received",
                "Lab Results Received",
                "Trigger when a new lab report is received",
                "trigger",
                260,
                40,
            ),
            _n(
                "l2",
                "call_patient",
                "Call Patient",
                "Call patient to discuss lab findings",
                "action",
                260,
                180,
                {
                    "lab_result_summary": "Your lab report is ready. We would like to schedule a consultation.",
                },
            ),
            _n(
                "l3",
                "schedule_appointment",
                "Schedule Appointment",
                "Create follow-up consultation slot",
                "action",
                260,
                320,
            ),
            _n(
                "l4",
                "log_completion",
                "Log Completion",
                "Mark workflow as completed",
                "endpoint",
                260,
                460,
            ),
        ],
        "edges": [
            _e("e1", "l1", "l2"),
            _e("e2", "l2", "l3"),
            _e("e3", "l3", "l4"),
        ],
    },
    {
        "id": "abnormal-lab-follow-up",
        "name": "Abnormal Lab Follow-Up",
        "description": "Escalate abnormal lab reports with immediate patient call and staff notification.",
        "category": "Clinical",
        "use_case": "Lab value monitoring",
        "nodes": [
            _n("t1", "lab_results_received", "Lab Results Received", "Trigger on new lab report", "trigger", 260, 40),
            _n(
                "t2",
                "check_result_values",
                "Check Result Values",
                "Check if HbA1c is above threshold",
                "conditional",
                260,
                180,
                {"test_name": "HbA1c", "operator": "greater_than", "threshold": "8", "threshold_max": ""},
            ),
            _n(
                "t3",
                "call_patient",
                "Call Patient",
                "Call patient for urgent follow-up",
                "action",
                80,
                330,
                {"lab_result_summary": "Your latest lab values need a follow-up review with your doctor."},
            ),
            _n("t4", "send_notification", "Send Notification", "Alert triage staff", "action", 80, 470, {"message": "Abnormal HbA1c detected. Please triage today.", "recipient": "staff", "priority": "urgent"}),
            _n("t5", "send_summary_to_doctor", "Send Summary to Doctor", "Send execution summary", "endpoint", 80, 610),
            _n("t6", "send_sms", "Send SMS", "Notify patient that results were reviewed", "action", 430, 330, {"message": "Your lab results were reviewed. No urgent action is required."}),
            _n("t7", "log_completion", "Log Completion", "End workflow", "endpoint", 430, 470),
        ],
        "edges": [
            _e("e1", "t1", "t2"),
            _e("e2", "t2", "t3", "true"),
            _e("e3", "t3", "t4"),
            _e("e4", "t4", "t5"),
            _e("e5", "t2", "t6", "false"),
            _e("e6", "t6", "t7"),
        ],
    },
    {
        "id": "missed-appointment-recovery",
        "name": "Missed Appointment Recovery",
        "description": "Recover no-show appointments through call retry and rescheduling outreach.",
        "category": "Operations",
        "use_case": "No-show reduction",
        "nodes": [
            _n("m1", "appointment_missed", "Appointment Missed", "Trigger when patient misses visit", "trigger", 260, 40),
            _n("m2", "check_appointment_history", "Check Appointment History", "Has this patient missed recently?", "conditional", 260, 180, {"days_since_last": "60"}),
            _n("m3", "call_patient", "Call Patient", "Call to recover missed visit", "action", 80, 330, {"lab_result_summary": "We noticed a missed appointment. Let us help you rebook quickly."}),
            _n("m4", "schedule_appointment", "Schedule Appointment", "Attempt auto scheduling", "action", 80, 470),
            _n("m5", "send_summary_to_doctor", "Send Summary to Doctor", "Inform doctor about recovered patient", "endpoint", 80, 610),
            _n("m6", "send_sms", "Send SMS", "Reminder for self-booking", "action", 430, 330, {"message": "You missed your appointment. Tap here to reschedule at your convenience."}),
            _n("m7", "log_completion", "Log Completion", "End workflow", "endpoint", 430, 470),
        ],
        "edges": [
            _e("e1", "m1", "m2"),
            _e("e2", "m2", "m3", "true"),
            _e("e3", "m3", "m4"),
            _e("e4", "m4", "m5"),
            _e("e5", "m2", "m6", "false"),
            _e("e6", "m6", "m7"),
        ],
    },
    {
        "id": "prescription-renewal-reminder",
        "name": "Prescription Renewal Reminder",
        "description": "Automatically nudge expiring prescriptions and route high-risk patients to staff.",
        "category": "Pharmacy",
        "use_case": "Medication adherence",
        "nodes": [
            _n("p1", "prescription_expiring", "Prescription Expiring", "Trigger near medication expiry", "trigger", 260, 40),
            _n("p2", "check_patient_age", "Check Patient Age", "Is patient elderly/high risk?", "conditional", 260, 180, {"operator": "greater_than", "threshold": "60", "threshold_max": ""}),
            _n("p3", "assign_to_staff", "Assign to Staff", "Assign refill assistance", "action", 80, 330, {"staff_id": "nurse_desk", "task_type": "prescription_follow_up", "due_date": ""}),
            _n("p4", "send_notification", "Send Notification", "Internal urgent flag", "action", 80, 470, {"message": "Senior patient prescription expiring. Please contact today.", "recipient": "care_team", "priority": "urgent"}),
            _n("p5", "log_completion", "Log Completion", "End workflow", "endpoint", 80, 610),
            _n("p6", "send_sms", "Send SMS", "Renewal reminder", "action", 430, 330, {"message": "Your prescription is expiring soon. Please request renewal to avoid interruption."}),
            _n("p7", "create_report", "Create Report", "Save outreach report", "endpoint", 430, 470),
        ],
        "edges": [
            _e("e1", "p1", "p2"),
            _e("e2", "p2", "p3", "true"),
            _e("e3", "p3", "p4"),
            _e("e4", "p4", "p5"),
            _e("e5", "p2", "p6", "false"),
            _e("e6", "p6", "p7"),
        ],
    },
    {
        "id": "new-patient-onboarding",
        "name": "New Patient Onboarding",
        "description": "Welcome new patients with onboarding messages and first-visit preparation tasks.",
        "category": "Growth",
        "use_case": "Onboarding automation",
        "nodes": [
            _n("o1", "new_patient_registered", "New Patient Registered", "Trigger on patient creation", "trigger", 260, 40),
            _n("o2", "send_sms", "Send SMS", "Welcome SMS", "action", 260, 180, {"message": "Welcome to CareSync. We will guide your first consultation journey."}),
            _n("o3", "assign_to_staff", "Assign to Staff", "Assign onboarding task", "action", 260, 320, {"staff_id": "front_desk", "task_type": "onboarding_call", "due_date": ""}),
            _n("o4", "schedule_appointment", "Schedule Appointment", "Create first consultation slot", "action", 260, 460),
            _n("o5", "send_summary_to_doctor", "Send Summary to Doctor", "Inform doctor about new onboarding", "endpoint", 260, 600),
        ],
        "edges": [
            _e("e1", "o1", "o2"),
            _e("e2", "o2", "o3"),
            _e("e3", "o3", "o4"),
            _e("e4", "o4", "o5"),
        ],
    },
    {
        "id": "blood-campaign-launch",
        "name": "Blood Campaign Launch",
        "description": "Launch donor outreach workflow when urgent blood requirement is triggered.",
        "category": "Emergency",
        "use_case": "Blood donor mobilization",
        "nodes": [
            _n("b1", "blood_gathering_trigger", "Blood Gathering Trigger", "Trigger for donor outreach", "trigger", 260, 40),
            _n("b2", "start_blood_campaign", "Start Blood Campaign", "Run donor matching and outreach", "action", 260, 180, {"blood_type": "O+", "recipient_name": "Critical Patient", "patient_location": "Hubli", "reason": "Emergency transfusion", "batch_size": "5"}),
            _n("b3", "send_notification", "Send Notification", "Alert emergency desk", "action", 260, 320, {"message": "Blood campaign launched. Track donor responses live.", "recipient": "emergency_team", "priority": "urgent"}),
            _n("b4", "create_report", "Create Report", "Create campaign execution report", "endpoint", 260, 460),
            _n("b5", "send_summary_to_doctor", "Send Summary to Doctor", "Send recipient status summary", "endpoint", 260, 600),
        ],
        "edges": [
            _e("e1", "b1", "b2"),
            _e("e2", "b2", "b3"),
            _e("e3", "b3", "b4"),
            _e("e4", "b4", "b5"),
        ],
    },
]


def list_workflow_templates() -> list[dict[str, Any]]:
    return TEMPLATES


def get_workflow_template(template_id: str) -> dict[str, Any] | None:
    for template in TEMPLATES:
        if template["id"] == template_id:
            return template
    return None
