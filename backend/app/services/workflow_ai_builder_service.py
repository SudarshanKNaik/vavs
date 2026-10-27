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

# Steps with no matching node type are kept as custom boxes, so the drafted flow
# still matches what the doctor asked for. The engine skips them when it runs.
_CUSTOM_TYPES = {
    "custom_trigger": "trigger",
    "custom_condition": "conditional",
    "custom_action": "action",
    "custom_output": "endpoint",
}

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
    "send_sms": ("sms", "text", "message", "whatsapp"),
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


def _custom_node(node_type: str, label: str, description: str = "", node_id: str | None = None) -> dict[str, Any]:
    return {
        "id": node_id or _new_node_id(),
        "type": _CUSTOM_TYPES[node_type],
        "position": {"x": 0.0, "y": 0.0},
        "data": {
            "label": label,
            "nodeType": node_type,
            "description": description or "Custom step: not automated yet, skipped when the workflow runs",
            "params": {},
            "custom": True,
        },
    }


def _normalize_node(raw: dict[str, Any]) -> dict[str, Any] | None:
    node_type = str(raw.get("nodeType") or "").strip()
    if node_type in _CUSTOM_TYPES:
        label = str(raw.get("label") or "").strip()
        if not label:
            return None
        return _custom_node(
            node_type,
            label[:80],
            str(raw.get("description") or "").strip()[:200],
            str(raw.get("id") or "").strip() or None,
        )
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


def _default_node(node_type: str) -> dict[str, Any]:
    react_flow_type, label, description, params = _ALLOWED_NODE_TYPES[node_type]
    return {
        "id": _new_node_id(),
        "type": react_flow_type,
        "position": {"x": 0.0, "y": 0.0},
        "data": {"label": label, "nodeType": node_type, "description": description, "params": dict(params)},
    }


def _kind(node: dict[str, Any]) -> str:
    return str(node.get("type") or "action")


def _connect_ai_edges(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    trigger_id: str,
    output_id: str,
) -> list[dict[str, Any]] | None:
    """
    Keep the AI's own graph (branches included) when it hangs together: every
    node reachable from the trigger. Loose ends are joined to the output.
    Returns None when the edges are unusable, so the caller rebuilds them.
    """
    by_id = {n["id"]: n for n in nodes}
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        if edge["source"] == edge["target"] or edge["target"] == trigger_id or edge["source"] == output_id:
            continue
        outgoing.setdefault(edge["source"], []).append(edge)

    kept: list[dict[str, Any]] = []
    for source, out in outgoing.items():
        if _kind(by_id[source]) == "conditional":
            # Branch edges need a true/false handle; assign any that are missing.
            used = {e.get("sourceHandle") for e in out}
            for edge in out:
                handle = edge.get("sourceHandle")
                if handle not in ("true", "false"):
                    handle = "true" if "true" not in used else "false"
                    used.add(handle)
                kept.append(_make_edge(source, edge["target"], handle))
        else:
            kept.extend(_make_edge(source, e["target"]) for e in out)

    seen, stack = {trigger_id}, [trigger_id]
    while stack:
        current = stack.pop()
        for edge in kept:
            if edge["source"] == current and edge["target"] not in seen:
                seen.add(edge["target"])
                stack.append(edge["target"])
    if len(seen) < len(nodes) - (0 if output_id in seen else 1):
        return None

    for node in nodes:
        if node["id"] == output_id:
            continue
        handles = {e.get("sourceHandle") for e in kept if e["source"] == node["id"]}
        if _kind(node) == "conditional":
            for handle in ("true", "false"):
                if handle not in handles:
                    kept.append(_make_edge(node["id"], output_id, handle))
        elif not handles:
            kept.append(_make_edge(node["id"], output_id))
    return kept


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

    trigger_nodes = [n for n in nodes if _kind(n) == "trigger"]
    if not trigger_nodes:
        trigger_type = _pick_best_type_from_prompt(
            user_prompt, _TRIGGER_TYPES, _TRIGGER_KEYWORDS, "lab_results_received"
        )
        nodes.insert(0, _default_node(trigger_type))
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

    output_nodes = [n for n in nodes if _kind(n) == "endpoint"]
    if not output_nodes:
        output_type = _pick_best_type_from_prompt(
            user_prompt, _OUTPUT_TYPES, _OUTPUT_KEYWORDS, "log_completion"
        )
        nodes.append(_default_node(output_type))
        warnings.append("No output was produced, appended an output node")
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
        # Edges into a removed output now go to the one that's kept.
        edges = [
            {**e, "target": primary_output["id"]} if e.get("target") in removed_ids else e
            for e in edges
            if e.get("source") not in removed_ids
        ]
        warnings.append("Multiple outputs detected; kept one output aligned to the prompt")
        output_nodes = [primary_output]

    valid_ids = {n["id"] for n in nodes}
    trigger_node = trigger_nodes[0]
    output_node = output_nodes[0]

    connected = _connect_ai_edges(nodes, _normalize_edges(edges, valid_ids), trigger_node["id"], output_node["id"])
    if connected is not None:
        _auto_layout(nodes)
        return nodes, _normalize_edges(connected, valid_ids), warnings

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
            if _kind(node) == "conditional":
                rebuilt_edges.append(_make_edge(node["id"], next_target, "true"))
                rebuilt_edges.append(_make_edge(node["id"], output_node["id"], "false"))
            else:
                rebuilt_edges.append(_make_edge(node["id"], next_target))

    edges = _normalize_edges(rebuilt_edges, valid_ids)
    warnings.append("Rebuilt edges into one connected workflow path aligned to prompt intent")

    _auto_layout(nodes)
    return nodes, edges, warnings


# ---------------------------------------------------------------------------
# Offline builder: turns the doctor's own sentence into boxes when no AI
# service answers, so the canvas always reflects what was typed.
# ---------------------------------------------------------------------------

_TRIGGER_OPENERS = re.compile(r"^(when|whenever|once|after|as soon as|on|every|each|daily|weekly)\b", re.I)
# Hard step boundaries: new lines, semicolons, sentence ends, "then", arrows.
_STEP_SPLIT = re.compile(
    r"\s*(?:\n+|;|(?<!\bDr)(?<!\bMr)(?<!\bMs)(?<!\bMrs)(?<!\d)\.(?:\s+|$)"
    r"|,?\s*\b(?:and then|then|after that|afterwards|next|finally)\b\s*,?|->|→"
    # "... otherwise send an SMS": keep the word, it marks the else branch.
    r"|\s+(?=(?:otherwise|else)\b))\s*",
    re.I,
)
_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")
_ACTION_VERBS = (
    "call", "phone", "ring", "send", "sms", "text", "whatsapp", "message", "email", "mail", "alert",
    "notify", "inform", "escalate", "book", "schedule", "reschedule", "create", "order", "refer",
    "update", "mark", "flag", "assign", "start", "remind", "ask", "log", "record", "generate", "share",
    "follow up", "wait", "check", "review", "monitor", "repeat", "collect",
)
_ACTION_VERB_RE = re.compile(r"\b(" + "|".join(sorted({re.escape(v) for v in _ACTION_VERBS}, key=len, reverse=True)) + r")\b", re.I)
_CONDITION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "check_result_values": ("value", "level", "result", "count", "above", "below", "greater", "less", "high", "low",
                            "abnormal", "hba1c", "sugar", "glucose", "platelet", "hemoglobin", "haemoglobin", "bp", "pressure"),
    "check_patient_age": ("age", "years old", "elderly", "senior", "child", "older than", "younger than"),
    "check_insurance": ("insurance", "insured", "ayushman", "pmjay", "cghs"),
    "check_appointment_history": ("last visit", "last appointment", "not seen", "hasn't visited", "history"),
    "check_medication_list": ("medication", "medicine", "drug", "taking", "prescribed", "insulin", "metformin"),
}


def _tidy_label(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    text = re.sub(r"\s+(?:and|or)$", "", text, flags=re.I)
    text = re.sub(r"^(?:and|also|please|we should|we need to|i want to|i want|it should|should)\s+", "", text, flags=re.I)
    if len(text) > 60:
        text = text[:57].rsplit(" ", 1)[0] + "…"
    return text[:1].upper() + text[1:] if text else text


def _best_match(text: str, keyword_map: dict[str, tuple[str, ...]], candidates: set[str]) -> str | None:
    lowered = f" {text.lower()} "
    best, best_score = None, 0
    for node_type in sorted(candidates):
        score = sum(len(k) for k in keyword_map.get(node_type, ()) if re.search(rf"\b{re.escape(k)}\b", lowered))
        if score > best_score:
            best, best_score = node_type, score
    return best


def _step_node(kind: str, text: str) -> dict[str, Any]:
    """A box for one step: the closest built-in type, labelled in the doctor's words."""
    label = _tidy_label(text) or "Step"
    if kind == "trigger":
        node_type = _best_match(text, _TRIGGER_KEYWORDS, _TRIGGER_TYPES)
    elif kind == "conditional":
        node_type = _best_match(text, _CONDITION_KEYWORDS, _CONDITIONAL_TYPES)
    elif kind == "endpoint":
        node_type = _best_match(text, _OUTPUT_KEYWORDS, _OUTPUT_TYPES)
    else:
        node_type = _best_match(text, _NODE_KEYWORDS, {k for k, v in _ALLOWED_NODE_TYPES.items() if v[0] == "action"})
    if not node_type:
        custom_type = {"trigger": "custom_trigger", "conditional": "custom_condition", "endpoint": "custom_output"}
        return _custom_node(custom_type.get(kind, "custom_action"), label)
    node = _default_node(node_type)
    node["data"]["label"] = label
    if node_type in ("send_sms", "send_notification"):
        node["data"]["params"]["message"] = label
    return node


def _split_condition(clause: str) -> tuple[str, str]:
    """'if they report bleeding alert the doctor' -> ('they report bleeding', 'alert the doctor')."""
    body = re.sub(r"^\s*(?:if|in case|when)\s+", "", clause, flags=re.I)
    match = _ACTION_VERB_RE.search(body, 3)
    if match:
        return body[: match.start()], body[match.start():]
    return body, ""


_NEW_STEP_AFTER_COMMA = re.compile(rf"^\s*(?:and\s+)?(?:if|in case|else|otherwise|{_ACTION_VERB_RE.pattern[3:-3]})\b", re.I)


_AND_NEW_STEP = re.compile(rf"\s+and\s+(?=(?:{_ACTION_VERB_RE.pattern[3:-3]})\b)", re.I)


def _split_steps(text: str) -> list[str]:
    """Split a request into steps. A comma only splits when a new step starts after it."""
    steps: list[str] = []
    for part in _STEP_SPLIT.split(text):
        part = _LIST_MARKER.sub("", part or "").strip()
        if not part:
            continue
        pieces = part.split(",")
        current = pieces[0]
        for piece in pieces[1:]:
            if _NEW_STEP_AFTER_COMMA.match(piece):
                steps.append(current.strip())
                current = piece
            else:
                current += "," + piece
        steps.append(current.strip())
    # "call the patient and book a slot" is two steps; "day 2 and day 7" is not.
    steps = [piece for step in steps for piece in _AND_NEW_STEP.split(step)]
    return [re.sub(r"^(?:and|&)\s+", "", s, flags=re.I) for s in steps if s]


def _heuristic_workflow(user_prompt: str) -> dict[str, Any]:
    text = user_prompt.strip()
    clauses = _split_steps(text)

    trigger_text = None
    # The first step is the trigger when it reads like an event ("When...",
    # "New patient registers") rather than an instruction ("Call the patient").
    if clauses and (
        _TRIGGER_OPENERS.match(clauses[0])
        or not re.match(rf"^\s*(?:if|in case|{_ACTION_VERB_RE.pattern[3:-3]})\b", clauses[0], re.I)
    ):
        trigger_text = clauses.pop(0)
        # "When X happens call the patient" -> trigger "When X happens", step "call the patient".
        verb = _ACTION_VERB_RE.search(trigger_text, 5)
        if verb:
            clauses.insert(0, trigger_text[verb.start():])
            trigger_text = trigger_text[: verb.start()]
    trigger = _step_node("trigger", trigger_text) if trigger_text else _default_node(
        _pick_best_type_from_prompt(text, _TRIGGER_TYPES, _TRIGGER_KEYWORDS, "lab_results_received")
    )

    output = None
    if clauses and _best_match(clauses[-1], _OUTPUT_KEYWORDS, _OUTPUT_TYPES) and re.match(
        r"^(log|record|generate|create a report|create report|send (?:a )?summary|summari[sz]e)", clauses[-1], re.I
    ):
        output = _step_node("endpoint", clauses.pop())
    output = output or _default_node(_pick_best_type_from_prompt(text, _OUTPUT_TYPES, _OUTPUT_KEYWORDS, "log_completion"))

    nodes = [trigger]
    edges: list[dict[str, Any]] = []
    # Open ends that the next step attaches to: (node id, source handle).
    tails: list[tuple[str, str | None]] = [(trigger["id"], None)]

    def attach(node: dict[str, Any]) -> None:
        nodes.append(node)
        for source, handle in tails:
            edges.append(_make_edge(source, node["id"], handle))

    i = 0
    while i < len(clauses):
        clause = clauses[i]
        if re.match(r"^\s*(?:if|in case)\b", clause, re.I):
            cond_text, yes_text = _split_condition(clause)
            # "if X, alert the doctor": the action came after a comma or "then".
            if not yes_text.strip() and i + 1 < len(clauses) and not re.match(
                r"^\s*(?:else|otherwise|if)\b", clauses[i + 1], re.I
            ):
                i += 1
                yes_text = clauses[i]
            condition = _step_node("conditional", cond_text)
            attach(condition)
            tails = []
            if yes_text.strip():
                yes = _step_node("action", yes_text)
                nodes.append(yes)
                edges.append(_make_edge(condition["id"], yes["id"], "true"))
                tails.append((yes["id"], None))
            else:
                tails.append((condition["id"], "true"))
            if i + 1 < len(clauses) and re.match(r"^\s*(?:else|otherwise|if not)\b", clauses[i + 1], re.I):
                no_text = re.sub(r"^\s*(?:else|otherwise|if not)\b[\s,]*", "", clauses[i + 1], flags=re.I)
                no = _step_node("action", no_text)
                nodes.append(no)
                edges.append(_make_edge(condition["id"], no["id"], "false"))
                tails.append((no["id"], None))
                i += 1
            else:
                tails.append((condition["id"], "false"))
        else:
            step = _step_node("action", clause)
            attach(step)
            tails = [(step["id"], None)]
        i += 1

    attach(output)
    _auto_layout(nodes)
    words = re.findall(r"[A-Za-z0-9]+", trigger_text or text)
    return {
        "workflow_name": (" ".join(words[:6]).title() or "Drafted Workflow")[:60],
        "workflow_description": f"Drafted from: {text[:140]}",
        "nodes": nodes,
        "edges": edges,
        "notes": [],
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# AI providers
# ---------------------------------------------------------------------------


class _ProviderNotConfigured(Exception):
    pass


async def _ask_openrouter(system_prompt: str, user_content: str) -> str:
    api_key = settings.openrouter_api_key.strip()
    if not api_key:
        raise _ProviderNotConfigured
    model = settings.openrouter_model.strip() or "deepseek/deepseek-v3.2"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.15,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            },
        )
    if response.status_code >= 400:
        logger.error("OpenRouter generation failed status=%s detail=%s", response.status_code, response.text[:500])
        raise RuntimeError(f"OpenRouter returned {response.status_code}")
    return response.json().get("choices", [{}])[0].get("message", {}).get("content", "")


async def _ask_gemini(system_prompt: str, user_content: str) -> str:
    api_key = settings.google_gemini_api_key.strip()
    if not api_key:
        raise _ProviderNotConfigured
    model = settings.google_gemini_model.strip() or "gemini-2.5-flash"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            # Key in a header so it never appears in logged URLs.
            headers={"x-goog-api-key": api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_content}]}],
                "generationConfig": {"temperature": 0.15, "responseMimeType": "application/json"},
            },
        )
    if response.status_code >= 400:
        logger.error("Gemini generation failed status=%s detail=%s", response.status_code, response.text[:500])
        raise RuntimeError(f"Gemini returned {response.status_code}")
    parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(str(p.get("text", "")) for p in parts)


def _workflow_from_ai_content(content: str, user_prompt: str) -> dict[str, Any]:
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
        if node["id"] in seen_node_ids:
            node["id"] = _new_node_id()
        seen_node_ids.add(node["id"])

    edges = [e for e in raw_edges if isinstance(e, dict)]
    nodes, edges, validation_warnings = _ensure_valid_flow(nodes, edges, user_prompt)

    ai_notes = parsed.get("notes") if isinstance(parsed.get("notes"), list) else []
    return {
        "workflow_name": str(parsed.get("workflow_name") or "AI Generated Workflow").strip(),
        "workflow_description": str(
            parsed.get("workflow_description") or f"Generated from doctor request: {user_prompt[:140]}"
        ).strip(),
        "nodes": nodes,
        "edges": edges,
        "notes": [str(n) for n in ai_notes[:8]],
        "warnings": validation_warnings,
    }


_SYSTEM_PROMPT = (
    "You are an expert medical workflow graph planner. "
    "Your task is to convert doctor requests into a workflow graph for React Flow. "

    "STRICT OUTPUT RULES: "
    "Return ONLY valid JSON. Do NOT include markdown, explanations, comments, or any text outside the JSON. "
    "The response must be directly parseable using JSON.parse(). "

    "NODE CHOICE: "
    "Represent EVERY step the doctor describes, in the order given. "
    "Use the allowed nodeType that matches a step whenever one fits, mapping synonyms to it. "
    "Only when no allowed type fits a step, use a custom nodeType: custom_trigger, custom_condition, "
    "custom_action or custom_output, with a short label in the doctor's own words (max 6 words). "
    "Never drop a step and never invent other nodeType values. "
    "Give every node a short, specific label taken from the request (e.g. 'Call on day 2', not 'Call Patient'). "

    "STRUCTURE RULES: "
    "Generate exactly ONE coherent workflow graph. "
    "All nodes must be connected in a single flow starting at the trigger (no isolated nodes). "
    "Use exactly ONE trigger node and exactly ONE output node. "
    "For every if/else in the request, use a condition node with a 'true' edge and a 'false' edge "
    "leading to the matching steps; both branches may rejoin later steps. "

    "OUTPUT FORMAT (STRICT): "
    "Return JSON with EXACTLY these keys: "
    "workflow_name (string), workflow_description (string), nodes (array), edges (array), notes (array of strings). "
    "Each node must include: id, nodeType, label, description, params. "
    "Each edge must include: source and target; for condition nodes also sourceHandle 'true' or 'false'. "

    "ALLOWED NODE TYPES: "
    + ", ".join(sorted(_ALLOWED_NODE_TYPES.keys()))
    + ". CUSTOM NODE TYPES (only when nothing above fits): "
    + ", ".join(sorted(_CUSTOM_TYPES))
    + "."
)


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

    user_content = json.dumps(
        {
            "doctor_id": doctor_id,
            "request": user_prompt,
            "constraints": {"max_nodes": 12, "must_include_trigger": True, "must_include_output": True},
        }
    )

    # OpenRouter first, then Gemini; if neither answers, draft it from the text.
    problems: list[str] = []
    for name, ask in (("OpenRouter", _ask_openrouter), ("Gemini", _ask_gemini)):
        try:
            content = await ask(_SYSTEM_PROMPT, user_content)
        except _ProviderNotConfigured:
            continue
        except Exception as exc:
            logger.warning("%s workflow generation failed: %s", name, exc)
            problems.append(str(exc) if str(exc).startswith(name) else f"{name} request failed")
            continue
        try:
            result = _workflow_from_ai_content(content, user_prompt)
        except Exception as exc:
            logger.exception("Failed to parse %s workflow response", name)
            problems.append(f"{name} response couldn't be read")
            continue
        if problems:
            result["warnings"] = [f"Built with {name} ({'; '.join(problems)})"] + result["warnings"]
        return result

    result = _heuristic_workflow(user_prompt)
    reason = "; ".join(problems) if problems else "no AI service is configured"
    result["warnings"] = [
        f"AI unavailable ({reason}), so the boxes were drafted directly from your text. Review them before running."
    ]
    return result
