"""
AI workflow builder service.

Turns natural language into a workflow graph (nodes + edges) that matches
existing workflow engine node types.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# nodeType -> (react_flow_type, default_label, default_description, default_params)
_ALLOWED_NODE_TYPES: dict[str, tuple[str, str, str, dict[str, str]]] = {
    # Triggers
    "lab_results_received": (
        "trigger",
        "Lab Results Received",
        "Triggered when lab results arrive for a patient",
        {},
    ),
    "abnormal_result_detected": (
        "trigger",
        "Abnormal Result",
        "Triggered when an abnormal lab value is detected",
        {},
    ),
    "follow_up_due": (
        "trigger",
        "Follow-Up Due",
        "Triggered when a patient is due for follow-up",
        {},
    ),
    "appointment_missed": (
        "trigger",
        "Appointment Missed",
        "Triggered when a patient misses an appointment",
        {},
    ),
    "new_patient_registered": (
        "trigger",
        "New Patient Registered",
        "Triggered when a new patient registers",
        {},
    ),
    "prescription_expiring": (
        "trigger",
        "Prescription Expiring",
        "Triggered when prescription is nearing expiry",
        {},
    ),
    "blood_gathering_trigger": (
        "trigger",
        "Blood Gathering Trigger",
        "Triggered when donor outreach should begin",
        {},
    ),
    # Conditions
    "check_result_values": (
        "conditional",
        "Check Result Values",
        "Branch based on lab thresholds",
        {"test_name": "", "operator": "greater_than", "threshold": ""},
    ),
    "check_insurance": (
        "conditional",
        "Check Insurance",
        "Branch based on insurance status",
        {"insurance_type": "any"},
    ),
    "check_patient_age": (
        "conditional",
        "Check Patient Age",
        "Branch based on patient age",
        {"operator": "greater_than", "threshold": ""},
    ),
    "check_appointment_history": (
        "conditional",
        "Check Appointment History",
        "Branch based on last appointment",
        {"days_since_last": "90"},
    ),
    "check_medication_list": (
        "conditional",
        "Check Medication List",
        "Branch based on current medication",
        {"medication": ""},
    ),
    # Actions
    "call_patient": (
        "action",
        "Call Patient",
        "Place AI outbound call",
        {"lab_result_summary": ""},
    ),
    "send_sms": (
        "action",
        "Send SMS",
        "Send SMS to patient",
        {"message": ""},
    ),
    "schedule_appointment": (
        "action",
        "Schedule Appointment",
        "Schedule appointment",
        {},
    ),
    "send_notification": (
        "action",
        "Send Notification",
        "Notify internal staff",
        {"message": "", "recipient": "staff", "priority": "normal"},
    ),
    "create_lab_order": (
        "action",
        "Create Lab Order",
        "Create lab order in system",
        {"test_type": "", "priority": "routine", "notes": ""},
    ),
    "create_referral": (
        "action",
        "Create Referral",
        "Create specialist referral",
        {"specialty": "", "reason": "", "urgency": "routine"},
    ),
    "update_patient_record": (
        "action",
        "Update Patient Record",
        "Update patient record fields",
        {"risk_level": "", "notes": ""},
    ),
    "assign_to_staff": (
        "action",
        "Assign to Staff",
        "Assign patient follow-up task",
        {"staff_id": "", "task_type": "follow_up", "due_date": ""},
    ),
    "start_blood_campaign": (
        "action",
        "Start Blood Campaign",
        "Initiate blood donor outreach",
        {
            "blood_type": "O+",
            "recipient_name": "",
            "patient_location": "",
            "reason": "",
            "batch_size": "3",
        },
    ),
    # Output
    "log_completion": (
        "endpoint",
        "Log Completion",
        "Log workflow completion",
        {},
    ),
    "generate_transcript": (
        "endpoint",
        "Generate Transcript",
        "Fetch call transcript",
        {},
    ),
    "create_report": (
        "endpoint",
        "Create Report",
        "Create execution report",
        {},
    ),
    "send_summary_to_doctor": (
        "endpoint",
        "Send Summary to Doctor",
        "Send workflow summary to doctor",
        {},
    ),
}

_TRIGGER_TYPES = {k for k, v in _ALLOWED_NODE_TYPES.items() if v[0] == "trigger"}
_OUTPUT_TYPES = {k for k, v in _ALLOWED_NODE_TYPES.items() if v[0] == "endpoint"}
_CONDITIONAL_TYPES = {k for k, v in _ALLOWED_NODE_TYPES.items() if v[0] == "conditional"}

_TRIGGER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "lab_results_received": ("lab", "result", "report", "upload", "test"),
    "abnormal_result_detected": ("abnormal", "critical", "high", "low", "flag"),
    "follow_up_due": ("follow", "due", "reminder", "pending"),
    "appointment_missed": ("missed", "no show", "no_show"),
    "new_patient_registered": ("new patient", "register", "signup", "sign up"),
    "prescription_expiring": ("prescription", "medication", "expiry", "expire"),
    "blood_gathering_trigger": ("blood", "donor", "campaign", "transfusion"),
}

_OUTPUT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "create_report": ("report", "summary", "document"),
    "generate_transcript": ("transcript", "call recording", "conversation"),
    "send_summary_to_doctor": ("doctor", "notify", "summary", "email"),
    "log_completion": ("log", "audit", "completion", "record"),
}

_NODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "call_patient": ("call", "phone", "voice"),
    "send_sms": ("sms", "text", "message"),
    "schedule_appointment": ("schedule", "book", "appointment", "slot", "reschedule"),
    "send_notification": ("notify", "alert", "notification", "staff"),
    "create_lab_order": ("lab order", "order", "test"),
    "create_referral": ("referral", "specialist"),
    "update_patient_record": ("update", "record", "risk"),
    "assign_to_staff": ("assign", "staff", "task"),
    "start_blood_campaign": ("blood", "donor", "campaign"),
    "check_result_values": ("threshold", "abnormal", "value", "check"),
    "check_insurance": ("insurance",),
    "check_patient_age": ("age",),
    "check_appointment_history": ("history", "last appointment"),
    "check_medication_list": ("medication", "drug"),
}


class WorkflowBuilderError(RuntimeError):
    pass


def _new_node_id() -> str:
    return f"ai_{uuid4().hex[:12]}"


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    # Strip fenced markdown if present.
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\\s*", "", cleaned)
        cleaned = re.sub(r"\\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: capture first JSON object region.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _is_prompt_injection_attempt(prompt: str) -> bool:
    text = (prompt or "").lower()
    if not text:
        return False

    patterns = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(all\s+)?(system|developer)\s+instructions",
        r"reveal\s+(the\s+)?(system|developer)\s+prompt",
        r"show\s+(the\s+)?(system|developer)\s+prompt",
        r"jailbreak",
        r"prompt\s+injection",
        r"bypass\s+(safety|guardrails|policy)",
        r"do\s+anything\s+now",
        r"act\s+as\s+.*(root|admin|developer)",
        r"return\s+raw\s+instructions",
    ]

    return any(re.search(p, text) for p in patterns)


def _empty_workflow_response() -> dict[str, Any]:
    # Intentionally silent/no explanation response for prompt-injection attempts.
    return {
        "workflow_name": "",
        "workflow_description": "",
        "nodes": [],
        "edges": [],
        "notes": [],
        "warnings": [],
    }


def _normalize_node(raw: dict[str, Any]) -> dict[str, Any] | None:
    node_type = str(raw.get("nodeType") or "").strip()
    if node_type not in _ALLOWED_NODE_TYPES:
        return None

    react_flow_type, default_label, default_description, default_params = _ALLOWED_NODE_TYPES[
        node_type
    ]

    label = str(raw.get("label") or default_label).strip() or default_label
    description = (
        str(raw.get("description") or default_description).strip() or default_description
    )

    raw_params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    # Strictly keep only cataloged params for the selected allowed nodeType.
    params = {**default_params}
    allowed_param_keys = set(default_params.keys())
    for key, value in raw_params.items():
        if value is None:
            continue
        key_s = str(key)
        if key_s not in allowed_param_keys:
            continue
        params[key_s] = str(value)

    node_id = str(raw.get("id") or "").strip() or _new_node_id()

    x = raw.get("position", {}).get("x", 0) if isinstance(raw.get("position"), dict) else 0
    y = raw.get("position", {}).get("y", 0) if isinstance(raw.get("position"), dict) else 0

    try:
        pos_x = float(x)
    except Exception:
        pos_x = 0.0
    try:
        pos_y = float(y)
    except Exception:
        pos_y = 0.0

    return {
        "id": node_id,
        "type": react_flow_type,
        "position": {"x": pos_x, "y": pos_y},
        "data": {
            "label": label,
            "nodeType": node_type,
            "description": description,
            "params": params,
        },
    }


def _normalize_edges(raw_edges: list[dict[str, Any]], valid_node_ids: set[str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()

    for idx, edge in enumerate(raw_edges):
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source not in valid_node_ids or target not in valid_node_ids:
            continue
        source_handle = edge.get("sourceHandle")
        if source_handle is not None:
            source_handle = str(source_handle)

        dedupe_key = (source, target, source_handle)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        normalized.append(
            {
                "id": str(edge.get("id") or f"ai_edge_{idx}_{uuid4().hex[:6]}"),
                "source": source,
                "target": target,
                **({"sourceHandle": source_handle} if source_handle else {}),
                "animated": True,
                "style": {
                    "stroke": "#10b981" if source_handle == "true" else "#ef4444" if source_handle == "false" else "#C43B3B",
                    "strokeWidth": 2,
                },
            }
        )

    return normalized


def _auto_layout(nodes: list[dict[str, Any]]) -> None:
    lane_x = {
        "trigger": 120,
        "conditional": 340,
        "action": 560,
        "endpoint": 780,
    }
    lane_count = {"trigger": 0, "conditional": 0, "action": 0, "endpoint": 0}

    for node in nodes:
        node_type = node.get("type", "action")
        lane_count.setdefault(node_type, 0)
        index = lane_count[node_type]
        lane_count[node_type] += 1
        node["position"] = {"x": lane_x.get(node_type, 560), "y": 80 + index * 170}


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(k in text for k in keywords)


def _pick_best_type_from_prompt(
    user_prompt: str,
    available_types: set[str],
    keyword_map: dict[str, tuple[str, ...]],
    default_type: str,
) -> str:
    prompt_l = (user_prompt or "").lower()
    best_type = default_type
    best_score = -1
    for node_type in available_types:
        words = keyword_map.get(node_type, ())
        score = sum(1 for w in words if w in prompt_l)
        if score > best_score:
            best_score = score
            best_type = node_type
    return best_type


def _node_prompt_score(node: dict[str, Any], user_prompt: str) -> int:
    prompt_l = (user_prompt or "").lower()
    data = node.get("data", {})
    node_type = str(data.get("nodeType") or "")
    score = 0

    for w in _NODE_KEYWORDS.get(node_type, ()):
        if w in prompt_l:
            score += 2

    label = str(data.get("label") or "").lower()
    description = str(data.get("description") or "").lower()
    for token in re.findall(r"[a-z0-9_]+", prompt_l):
        if len(token) < 4:
            continue
        if token in label:
            score += 1
        if token in description:
            score += 1

    return score


def _make_edge(
    source: str,
    target: str,
    source_handle: str | None = None,
) -> dict[str, Any]:
    color = "#10b981" if source_handle == "true" else "#ef4444" if source_handle == "false" else "#C43B3B"
    edge: dict[str, Any] = {
        "id": f"ai_edge_{uuid4().hex[:6]}",
        "source": source,
        "target": target,
        "animated": True,
        "style": {"stroke": color, "strokeWidth": 2},
    }
    if source_handle:
        edge["sourceHandle"] = source_handle
    return edge


def _ensure_valid_flow(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    user_prompt: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []

    if not nodes:
        raise WorkflowBuilderError("AI did not generate any valid nodes")

    if len(nodes) > 30:
        nodes = nodes[:30]
        warnings.append("Workflow truncated to first 30 nodes for safety")

    trigger_nodes = [n for n in nodes if n.get("data", {}).get("nodeType") in _TRIGGER_TYPES]
    if not trigger_nodes:
        trigger_type = _pick_best_type_from_prompt(
            user_prompt,
            _TRIGGER_TYPES,
            _TRIGGER_KEYWORDS,
            "lab_results_received",
        )
        _, default_label, default_description, default_params = _ALLOWED_NODE_TYPES[trigger_type]
        trigger_id = _new_node_id()
        nodes.insert(
            0,
            {
                "id": trigger_id,
                "type": "trigger",
                "position": {"x": 120, "y": 80},
                "data": {
                    "label": default_label,
                    "nodeType": trigger_type,
                    "description": default_description,
                    "params": default_params,
                },
            },
        )
        warnings.append("No trigger was produced, inserted a default trigger")
        trigger_nodes = [nodes[0]]

    if len(trigger_nodes) > 1:
        preferred_trigger_type = _pick_best_type_from_prompt(
            user_prompt,
            {str(n.get("data", {}).get("nodeType") or "") for n in trigger_nodes},
            _TRIGGER_KEYWORDS,
            str(trigger_nodes[0].get("data", {}).get("nodeType") or "lab_results_received"),
        )
        primary_trigger = next(
            (n for n in trigger_nodes if n.get("data", {}).get("nodeType") == preferred_trigger_type),
            trigger_nodes[0],
        )
        removed_ids = {n["id"] for n in trigger_nodes if n["id"] != primary_trigger["id"]}
        nodes = [n for n in nodes if n["id"] not in removed_ids]
        edges = [e for e in edges if e.get("source") not in removed_ids and e.get("target") not in removed_ids]
        warnings.append("Multiple triggers detected; kept one trigger aligned to the prompt")
        trigger_nodes = [primary_trigger]

    output_nodes = [n for n in nodes if n.get("data", {}).get("nodeType") in _OUTPUT_TYPES]
    if not output_nodes:
        output_type = _pick_best_type_from_prompt(
            user_prompt,
            _OUTPUT_TYPES,
            _OUTPUT_KEYWORDS,
            "log_completion",
        )
        _, default_label, default_description, default_params = _ALLOWED_NODE_TYPES[output_type]
        out_id = _new_node_id()
        nodes.append(
            {
                "id": out_id,
                "type": "endpoint",
                "position": {"x": 780, "y": 80},
                "data": {
                    "label": default_label,
                    "nodeType": output_type,
                    "description": default_description,
                    "params": default_params,
                },
            }
        )
        warnings.append("No output was produced, appended log completion node")
        output_nodes = [nodes[-1]]

    if len(output_nodes) > 1:
        preferred_output_type = _pick_best_type_from_prompt(
            user_prompt,
            {str(n.get("data", {}).get("nodeType") or "") for n in output_nodes},
            _OUTPUT_KEYWORDS,
            str(output_nodes[0].get("data", {}).get("nodeType") or "log_completion"),
        )
        primary_output = next(
            (n for n in output_nodes if n.get("data", {}).get("nodeType") == preferred_output_type),
            output_nodes[0],
        )
        removed_ids = {n["id"] for n in output_nodes if n["id"] != primary_output["id"]}
        nodes = [n for n in nodes if n["id"] not in removed_ids]
        edges = [e for e in edges if e.get("source") not in removed_ids and e.get("target") not in removed_ids]
        warnings.append("Multiple outputs detected; kept one output aligned to the prompt")
        output_nodes = [primary_output]

    valid_ids = {n["id"] for n in nodes}
    _ = _normalize_edges(edges, valid_ids)

    trigger_node = trigger_nodes[0]
    output_node = output_nodes[0]

    non_terminal_nodes = [
        n for n in nodes if n["id"] not in {trigger_node["id"], output_node["id"]}
    ]

    original_index = {n["id"]: i for i, n in enumerate(nodes)}
    pipeline_nodes = sorted(
        non_terminal_nodes,
        key=lambda n: (
            {"conditional": 0, "action": 1}.get(n.get("type", "action"), 2),
            -_node_prompt_score(n, user_prompt),
            original_index.get(n["id"], 0),
        ),
    )

    rebuilt_edges: list[dict[str, Any]] = []
    if not pipeline_nodes:
        rebuilt_edges.append(_make_edge(trigger_node["id"], output_node["id"]))
    else:
        rebuilt_edges.append(_make_edge(trigger_node["id"], pipeline_nodes[0]["id"]))
        for idx, node in enumerate(pipeline_nodes):
            next_target = (
                pipeline_nodes[idx + 1]["id"] if idx + 1 < len(pipeline_nodes) else output_node["id"]
            )
            node_type = str(node.get("data", {}).get("nodeType") or "")
            if node_type in _CONDITIONAL_TYPES:
                rebuilt_edges.append(_make_edge(node["id"], next_target, "true"))
                rebuilt_edges.append(_make_edge(node["id"], output_node["id"], "false"))
            else:
                rebuilt_edges.append(_make_edge(node["id"], next_target))

    edges = _normalize_edges(rebuilt_edges, valid_ids)
    warnings.append("Rebuilt edges into one connected workflow path aligned to prompt intent")

    _auto_layout(nodes)
    return nodes, edges, warnings


def _fallback_workflow(user_prompt: str) -> dict[str, Any]:
    trigger = {
        "id": _new_node_id(),
        "type": "trigger",
        "position": {"x": 120, "y": 80},
        "data": {
            "label": "Lab Results Received",
            "nodeType": "lab_results_received",
            "description": "Triggered when lab results arrive for a patient",
            "params": {},
        },
    }
    action = {
        "id": _new_node_id(),
        "type": "action",
        "position": {"x": 560, "y": 80},
        "data": {
            "label": "Send Notification",
            "nodeType": "send_notification",
            "description": "Notify staff for manual review",
            "params": {
                "message": f"AI fallback generated from request: {user_prompt[:120]}",
                "recipient": "staff",
                "priority": "normal",
            },
        },
    }
    output = {
        "id": _new_node_id(),
        "type": "endpoint",
        "position": {"x": 780, "y": 80},
        "data": {
            "label": "Log Completion",
            "nodeType": "log_completion",
            "description": "Log workflow completion",
            "params": {},
        },
    }

    nodes = [trigger, action, output]
    edges = [
        {
            "id": f"ai_edge_{uuid4().hex[:6]}",
            "source": trigger["id"],
            "target": action["id"],
            "animated": True,
            "style": {"stroke": "#C43B3B", "strokeWidth": 2},
        },
        {
            "id": f"ai_edge_{uuid4().hex[:6]}",
            "source": action["id"],
            "target": output["id"],
            "animated": True,
            "style": {"stroke": "#C43B3B", "strokeWidth": 2},
        },
    ]

    return {
        "workflow_name": "AI Generated Workflow",
        "workflow_description": "Fallback workflow generated when AI response was unavailable.",
        "nodes": nodes,
        "edges": edges,
        "warnings": ["Used fallback generator because AI model response failed"],
    }


async def generate_workflow_from_natural_language(
    *,
    prompt: str,
    doctor_id: str | None = None,
) -> dict[str, Any]:
    user_prompt = (prompt or "").strip()
    if not user_prompt:
        raise WorkflowBuilderError("Prompt cannot be empty")

    if _is_prompt_injection_attempt(user_prompt):
        return _empty_workflow_response()

    api_key = settings.openrouter_api_key.strip()
    model = settings.openrouter_model.strip() or "deepseek/deepseek-v3.2"
    base_url = settings.openrouter_base_url.rstrip("/")

    if not api_key:
        raise WorkflowBuilderError("OpenRouter API key is not configured")

    # system_prompt = (
    #     "You are an expert medical workflow graph planner. "
    #     "Convert doctor requests into an executable workflow graph for React Flow. "
    #     "Understand intent from full natural-language details, not just exact keywords. "
    #     "If user provides step-by-step workflow details, preserve that sequence in the generated nodes. "
    #     "Map synonyms and paraphrases to the closest allowed node types while keeping medical logic coherent. "
    #     "Never invent custom triggers, conditionals, actions, outputs, or nodeType values. "
    #     "If a requested step is not available, map it to the closest allowed node type. "
    #     "Generate exactly one coherent workflow graph where every node is connected to the same flow. "
    #     "Use exactly one trigger node and one output node. "
    #     "Output JSON only with these keys: "
    #     "workflow_name (string), workflow_description (string), nodes (array), edges (array), notes (array of strings). "
    #     "Each node must include: id, nodeType, label, description, params. "
    #     "Allowed nodeType values are exactly: "
    #     + ", ".join(sorted(_ALLOWED_NODE_TYPES.keys()))
    #     + ". "
    #     "Each edge must include source and target; for conditional branches, set sourceHandle to true or false. "
    #     "Do not include any markdown, explanation, or text outside JSON."
    # )

    system_prompt = (
    "You are an expert medical workflow graph planner. "
    "Your task is to convert doctor requests into a valid, executable workflow graph for React Flow. "

    "STRICT OUTPUT RULES: "
    "Return ONLY valid JSON. Do NOT include markdown, explanations, comments, or any text outside the JSON. "
    "The response must be directly parseable using JSON.parse(). "

    "FLOW CONSTRAINTS: "
    "Generate ONLY workflows that can be fully constructed using the provided allowed node types. "
    "DO NOT include any step, logic, or concept that cannot be implemented using the available nodes. "
    "If a requested step is not supported, you MUST map it to the closest valid nodeType from the allowed list. "
    "DO NOT invent or assume any new triggers, actions, conditionals, outputs, or nodeType values. "

    "STRUCTURE RULES: "
    "Generate exactly ONE coherent workflow graph. "
    "All nodes must be connected in a single valid flow (no isolated nodes). "
    "Use exactly ONE trigger node and exactly ONE output node. "
    "Preserve user-provided step order when explicitly given. "
    "Infer intent from natural language and map synonyms to valid node types while maintaining medical correctness. "

    "OUTPUT FORMAT (STRICT): "
    "Return JSON with EXACTLY these keys: "
    "workflow_name (string), workflow_description (string), nodes (array), edges (array), notes (array of strings). "

    "NODE RULES: "
    "Each node must include: id, nodeType, label, description, params. "
    "nodeType must be one of the allowed values only. "

    "EDGE RULES: "
    "Each edge must include: source and target. "
    "For conditional branching, include sourceHandle with value 'true' or 'false'. "

    "ALLOWED NODE TYPES: "
    + ", ".join(sorted(_ALLOWED_NODE_TYPES.keys())) + "."
    )

    user_context = {
        "doctor_id": doctor_id,
        "request": user_prompt,
        "constraints": {
            "max_nodes": 12,
            "must_include_trigger": True,
            "must_include_output": True,
        },
    }

    payload = {
        "model": model,
        "temperature": 0.15,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_context)},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except Exception as exc:
        logger.exception("OpenRouter request failed")
        return _fallback_workflow(user_prompt) | {
            "warnings": [f"OpenRouter request failed: {exc}"]
        }

    if response.status_code >= 400:
        detail = response.text[:500]
        logger.error(
            "OpenRouter generation failed status=%s detail=%s",
            response.status_code,
            detail,
        )
        return _fallback_workflow(user_prompt) | {
            "warnings": [
                f"OpenRouter returned {response.status_code}, used fallback workflow"
            ]
        }

    try:
        body = response.json()
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = _extract_json(content)

        raw_nodes = parsed.get("nodes") if isinstance(parsed.get("nodes"), list) else []
        raw_edges = parsed.get("edges") if isinstance(parsed.get("edges"), list) else []

        nodes: list[dict[str, Any]] = []
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                continue
            normalized = _normalize_node(raw)
            if normalized is not None:
                nodes.append(normalized)

        # Deduplicate node ids
        seen_node_ids: set[str] = set()
        for node in nodes:
            node_id = node["id"]
            if node_id in seen_node_ids:
                node["id"] = _new_node_id()
            seen_node_ids.add(node["id"])

        edges = [e for e in raw_edges if isinstance(e, dict)]
        nodes, edges, validation_warnings = _ensure_valid_flow(
            nodes,
            edges,
            user_prompt,
        )

        ai_notes = parsed.get("notes") if isinstance(parsed.get("notes"), list) else []
        notes = [str(n) for n in ai_notes[:8]]

        workflow_name = str(parsed.get("workflow_name") or "AI Generated Workflow").strip()
        workflow_description = str(
            parsed.get("workflow_description")
            or f"Generated from doctor request: {user_prompt[:140]}"
        ).strip()

        return {
            "workflow_name": workflow_name,
            "workflow_description": workflow_description,
            "nodes": nodes,
            "edges": edges,
            "notes": notes,
            "warnings": validation_warnings,
        }
    except Exception as exc:
        logger.exception("Failed to parse OpenRouter response")
        return _fallback_workflow(user_prompt) | {
            "warnings": [f"AI response parsing failed: {exc}"]
        }
