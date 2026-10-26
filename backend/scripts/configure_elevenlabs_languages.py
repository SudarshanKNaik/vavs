"""
Configure an ElevenLabs agent to ask the caller's preferred language first and
then talk in it (Assamese, Gujarati, Kannada, Hindi, English, Malayalam,
Marathi, Odia, Punjabi, Sindhi, Tamil, Telugu).

What it changes on the agent (everything else is left as is):
  * agent.language        -> "en" (the opening question is in English + Hindi)
  * agent.first_message   -> the language question
  * language_presets      -> adds the missing switchable languages (hi, kn);
                             existing presets are kept
  * built_in_tools.language_detection -> enabled, so choosing a language
                             switches the agent's voice and speech recognition
  * prompt                -> tells the agent to call that tool when a language
                             is chosen, and adds fluency rules

Safe to re-run. Dry run by default; pass --apply to update the agent.

    python scripts/configure_elevenlabs_languages.py            # preview
    python scripts/configure_elevenlabs_languages.py --apply    # update
    python scripts/configure_elevenlabs_languages.py --agent-id agent_xxx --apply
"""

import argparse
import copy
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402

API = "https://api.elevenlabs.io/v1/convai/agents"

LANGUAGE_CODES = {
    "English": "en", "Hindi": "hi", "Kannada": "kn", "Gujarati": "gu",
    "Tamil": "ta", "Telugu": "te", "Malayalam": "ml", "Marathi": "mr",
    "Punjabi": "pa", "Odia": "or", "Assamese": "as", "Sindhi": "sd",
}
DEFAULT_LANGUAGE = "en"

FIRST_MESSAGE = (
    "Hi {{patient_name}}, this is CareSync calling about your appointment with "
    "Dr. {{doctor_name}}. Which language would you like to continue in: English, "
    "Hindi, Kannada, Gujarati, Tamil, Telugu, Malayalam, Marathi, Punjabi, Odia, "
    "Assamese, or Sindhi? आप किस भाषा में बात करना चाहेंगे?"
)

# Greeting used only when a call *starts* in that language; mirrors the
# existing presets (greeting + date question).
NEW_PRESET_FIRST_MESSAGES = {
    "hi": (
        "नमस्ते {{patient_name}}, यह CareSync की ओर से डॉ. {{doctor_name}} के साथ "
        "आपकी अपॉइंटमेंट के बारे में कॉल है। आप अपनी अपॉइंटमेंट किस तारीख को लेना चाहेंगे?"
    ),
    "kn": (
        "ನಮಸ್ಕಾರ {{patient_name}}, ಡಾ. {{doctor_name}} ಅವರೊಂದಿಗಿನ ನಿಮ್ಮ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ "
        "ಬಗ್ಗೆ CareSync ಇಂದ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇವೆ. ನಿಮ್ಮ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ಯಾವ ದಿನಾಂಕದಂದು ಬೇಕು?"
    ),
}

LANGUAGE_TOOL_DESCRIPTION = (
    "Switch the conversation language (your voice and speech recognition). Call it "
    "immediately when the patient chooses a language at the start of the call, when "
    "they ask to switch language, or when they clearly speak whole sentences in a "
    "different supported language. Do NOT switch just because the patient mixes "
    "English words into Hindi, Kannada, Gujarati or another language (for example "
    "'appointment', 'date', 'doctor', 'OK'); stay in the current language then."
)

CODE_LIST = ", ".join(f"{name}={code}" for name, code in LANGUAGE_CODES.items())
PROMPT_MARKER = "call the language_detection tool"

PROMPT_EDITS = [
    # (old, new) — applied once; skipped when PROMPT_MARKER is already present.
    (
        "3. Once chosen, acknowledge briefly IN THAT LANGUAGE and move straight to the date question, using these lines:",
        "3. As soon as a language is chosen, call the language_detection tool with its code "
        f"({CODE_LIST}) so your voice and listening switch to that language. Then acknowledge "
        "briefly IN THAT LANGUAGE and move straight to the date question, using these lines:",
    ),
    (
        "6. If the patient later asks to switch language, switch immediately,",
        "6. If the patient later asks to switch language, call the language_detection tool "
        "again and switch immediately,",
    ),
    (
        "Scheduling Flow (FOLLOW EXACTLY, IN THE CHOSEN LANGUAGE):",
        "10. Write every reply in the chosen language's own script: Hindi and Marathi in "
        "Devanagari, Kannada in Kannada script, Gujarati in Gujarati script, Tamil, Telugu, "
        "Malayalam, Punjabi, Odia, Assamese and Sindhi in their own scripts. Never write "
        "Indian languages in Latin letters.\n"
        "11. Speak the way people talk on the phone, not formal or bookish language. Common "
        "English words patients use every day (appointment, doctor, report, OK) are fine "
        "inside Hindi, Kannada, Gujarati and the other languages.\n"
        "12. Say dates and times the way they are said aloud in the chosen language, e.g. "
        "Hindi \"दस मई, दोपहर दो बजे\", Kannada \"ಮೇ ಹತ್ತು, ಮಧ್ಯಾಹ್ನ ಎರಡು ಗಂಟೆ\", Gujarati "
        "\"દસ મે, બપોરે બે વાગ્યે\".\n"
        "Scheduling Flow (FOLLOW EXACTLY, IN THE CHOSEN LANGUAGE):",
    ),
]


def build_update(agent: dict) -> tuple[dict, list[str]]:
    cc = copy.deepcopy(agent["conversation_config"])
    changes: list[str] = []
    agent_cfg = cc["agent"]

    if agent_cfg.get("language") != DEFAULT_LANGUAGE:
        changes.append(f"language: {agent_cfg.get('language')} -> {DEFAULT_LANGUAGE}")
        agent_cfg["language"] = DEFAULT_LANGUAGE
    if agent_cfg.get("first_message") != FIRST_MESSAGE:
        changes.append("first_message -> language question")
        agent_cfg["first_message"] = FIRST_MESSAGE

    presets = cc.get("language_presets") or {}
    for name, code in LANGUAGE_CODES.items():
        if code == DEFAULT_LANGUAGE:
            continue
        if code not in presets:
            message = NEW_PRESET_FIRST_MESSAGES.get(code)
            if not message:
                raise SystemExit(f"No preset greeting defined for {name} ({code})")
            presets[code] = {"overrides": {"agent": {"first_message": message}}}
            changes.append(f"language_presets: add {code} ({name})")
    # The default language must not also be a switch target.
    if DEFAULT_LANGUAGE in presets:
        presets.pop(DEFAULT_LANGUAGE)
        changes.append(f"language_presets: remove {DEFAULT_LANGUAGE} (now the default)")
    cc["language_presets"] = presets

    prompt_cfg = agent_cfg["prompt"]
    tools = prompt_cfg.get("built_in_tools") or {}
    wanted_tool = {
        "type": "system",
        "name": "language_detection",
        "description": LANGUAGE_TOOL_DESCRIPTION,
        "params": {"system_tool_type": "language_detection", "only_at_conversation_start": False},
    }
    current_tool = tools.get("language_detection") or {}
    if (
        current_tool.get("description") != wanted_tool["description"]
        or (current_tool.get("params") or {}).get("system_tool_type") != "language_detection"
    ):
        tools["language_detection"] = wanted_tool
        changes.append("built_in_tools.language_detection: enabled")
    prompt_cfg["built_in_tools"] = tools

    text = prompt_cfg.get("prompt") or ""
    old_first = text[text.find('"Hi {{patient_name}}'):] if '"Hi {{patient_name}}' in text else ""
    if old_first:
        old_first = old_first[: old_first.find('"', 1) + 1]
        new_first = f'"{FIRST_MESSAGE}"'
        if old_first != new_first and "First Message (ALWAYS START WITH THIS)" in text:
            text = text.replace(old_first, new_first, 1)
            changes.append("prompt: first message text synced")
    if PROMPT_MARKER not in text:
        for old, new in PROMPT_EDITS:
            if old not in text:
                raise SystemExit(f"Prompt no longer contains expected text, not editing:\n  {old}")
            text = text.replace(old, new, 1)
        changes.append("prompt: language tool + fluency rules added")
    prompt_cfg["prompt"] = text

    return {"conversation_config": {"agent": agent_cfg, "language_presets": presets}}, changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent-id", default=settings.elevenlabs_agent_id)
    parser.add_argument("--apply", action="store_true", help="Update the agent (default: dry run)")
    parser.add_argument("--backup", help="Write the agent's current config to this JSON file first")
    args = parser.parse_args()
    if not settings.elevenlabs_api_key or not args.agent_id:
        print("ELEVENLABS_API_KEY and an agent id are required", file=sys.stderr)
        return 1

    headers = {"xi-api-key": settings.elevenlabs_api_key}
    resp = httpx.get(f"{API}/{args.agent_id}", headers=headers, timeout=30)
    resp.raise_for_status()
    agent = resp.json()
    if args.backup:
        Path(args.backup).write_text(json.dumps(agent, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Backup written to {args.backup}")

    payload, changes = build_update(agent)
    print(f"Agent: {agent.get('name')} ({args.agent_id})")
    if not changes:
        print("Already configured; nothing to change.")
        return 0
    for change in changes:
        print(f"  - {change}")
    if not args.apply:
        print("Dry run. Re-run with --apply to update the agent.")
        return 0

    resp = httpx.patch(f"{API}/{args.agent_id}", headers=headers, json=payload, timeout=60)
    if resp.status_code >= 400:
        print(f"ElevenLabs rejected the update ({resp.status_code}): {resp.text[:1000]}", file=sys.stderr)
        return 1
    print("Agent updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
