"""AI workflow builder: provider fallback, the offline drafter, custom steps."""

import asyncio
import json

from app.services import workflow_ai_builder_service as wb
from app.services import workflow_engine


def _labels(workflow):
    return [n["data"]["label"] for n in workflow["nodes"]]


def _edges(workflow):
    label = {n["id"]: n["data"]["label"] for n in workflow["nodes"]}
    return {(label[e["source"]], e.get("sourceHandle"), label[e["target"]]) for e in workflow["edges"]}


def test_offline_draft_follows_the_text_with_branches():
    w = wb._heuristic_workflow(
        "When a dengue patient is discharged, call them on day 2 and day 7, "
        "if they report bleeding alert the doctor, else send an SMS with diet tips"
    )
    types = {n["data"]["label"]: n["data"]["nodeType"] for n in w["nodes"]}
    assert types["When a dengue patient is discharged"] == "custom_trigger"
    assert types["Call them on day 2 and day 7"] == "call_patient"
    assert types["They report bleeding"] == "custom_condition"
    assert types["Send an SMS with diet tips"] == "send_sms"
    edges = _edges(w)
    assert ("They report bleeding", "true", "Alert the doctor") in edges
    assert ("They report bleeding", "false", "Send an SMS with diet tips") in edges


def test_offline_draft_splits_steps_but_not_lists_inside_a_step():
    w = wb._heuristic_workflow("After a missed appointment text the patient, wait two days, call them again")
    assert _labels(w)[:4] == ["After a missed appointment", "Text the patient", "Wait two days", "Call them again"]
    w = wb._heuristic_workflow("When lab results arrive send an SMS about fever, cough and rest")
    assert "Send an SMS about fever, cough and rest" in _labels(w)


def test_offline_draft_maps_conditions_to_real_checks():
    w = wb._heuristic_workflow("When lab results arrive, if HbA1c is above 9 then book an appointment otherwise send SMS")
    types = {n["data"]["label"]: n["data"]["nodeType"] for n in w["nodes"]}
    assert types["HbA1c is above 9"] == "check_result_values"
    assert types["Book an appointment"] == "schedule_appointment"


def test_ai_branches_are_kept_and_custom_steps_survive():
    content = json.dumps(
        {
            "workflow_name": "Dengue follow-up",
            "nodes": [
                {"id": "t", "nodeType": "custom_trigger", "label": "Dengue patient discharged"},
                {"id": "c", "nodeType": "custom_condition", "label": "Reports bleeding?"},
                {"id": "a", "nodeType": "send_notification", "label": "Alert doctor"},
                {"id": "b", "nodeType": "send_sms", "label": "Diet tips SMS"},
                {"id": "o", "nodeType": "log_completion", "label": "Done"},
                {"id": "x", "nodeType": "made_up_type", "label": "Dropped"},
            ],
            "edges": [
                {"source": "t", "target": "c"},
                {"source": "c", "target": "a", "sourceHandle": "true"},
                {"source": "c", "target": "b", "sourceHandle": "false"},
                {"source": "a", "target": "o"},
            ],
        }
    )
    w = wb._workflow_from_ai_content(content, "dengue discharge")
    assert "Dropped" not in _labels(w)
    edges = _edges(w)
    assert ("Reports bleeding?", "true", "Alert doctor") in edges
    assert ("Reports bleeding?", "false", "Diet tips SMS") in edges
    assert ("Diet tips SMS", None, "Done") in edges  # loose end joined to the output
    assert not any("Rebuilt edges" in warning for warning in w["warnings"])


def test_falls_back_to_gemini_then_to_the_offline_draft(monkeypatch):
    async def fail(*_):
        raise RuntimeError("OpenRouter returned 401")

    async def gemini(*_):
        return json.dumps({"nodes": [{"id": "t", "nodeType": "lab_results_received", "label": "Labs in"}], "edges": []})

    monkeypatch.setattr(wb, "_ask_openrouter", fail)
    monkeypatch.setattr(wb, "_ask_gemini", gemini)
    result = asyncio.run(wb.generate_workflow_from_natural_language(prompt="when labs arrive call the patient"))
    assert result["warnings"][0] == "Built with Gemini (OpenRouter returned 401)"

    async def gemini_down(*_):
        raise RuntimeError("Gemini returned 503")

    monkeypatch.setattr(wb, "_ask_gemini", gemini_down)
    result = asyncio.run(wb.generate_workflow_from_natural_language(prompt="when labs arrive call the patient"))
    assert "drafted directly from your text" in result["warnings"][0]
    assert "Call the patient" in _labels(result)


def test_engine_skips_custom_steps_and_runs_neither_branch_of_a_custom_condition():
    w = wb._heuristic_workflow(
        "When a dengue patient is discharged, if they report bleeding alert the doctor, else send an SMS"
    )
    log = asyncio.run(workflow_engine.execute_workflow(w, {"id": "p1", "name": "Test", "phone": "9000000000"}))
    ran = [step.get("label") for step in log]
    assert ran[0] == "When a dengue patient is discharged"
    assert "They report bleeding" in ran
    assert "Alert the doctor" not in ran and "Send an SMS" not in ran
    assert all(step["status"] != "error" for step in log)
