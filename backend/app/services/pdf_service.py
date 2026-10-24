"""
PDF Extraction Service
-----------------------
Parses uploaded medical PDF documents (lab reports, patient records, etc.)
and extracts structured data that can be used by the workflow engine.

Uses pdfplumber for text extraction and regex-based parsing for common
medical document patterns.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from datetime import datetime
from typing import Any

import httpx
import pdfplumber

from app.core.config import settings

logger = logging.getLogger(__name__)


def _extract_json_block(text: str) -> dict[str, Any] | None:
    content = (text or "").strip()
    if not content:
        return None

    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None


def _normalize_gemini_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    patient_info = data.get("patient_info") if isinstance(data.get("patient_info"), dict) else {}
    tables = data.get("tables") if isinstance(data.get("tables"), list) else []
    medications = data.get("medications") if isinstance(data.get("medications"), list) else []
    raw_text = str(data.get("raw_text") or "")

    lab_rows = data.get("lab_results") if isinstance(data.get("lab_results"), list) else []
    normalized_lab_results: list[dict[str, Any]] = []
    for row in lab_rows:
        if not isinstance(row, dict):
            continue
        value_raw = row.get("value")
        try:
            numeric_value: float | str = float(value_raw)
        except (TypeError, ValueError):
            numeric_value = str(value_raw or "")

        normalized_lab_results.append(
            {
                "test_name": str(row.get("test_name") or "").strip(),
                "value": numeric_value,
                "unit": str(row.get("unit") or "").strip(),
                "reference_range": str(row.get("reference_range") or "").strip(),
                "flag": str(row.get("flag") or "normal").strip().lower() or "normal",
            }
        )

    return {
        "raw_text": raw_text,
        "patient_info": patient_info,
        "lab_results": normalized_lab_results,
        "medications": medications,
        "tables": tables,
    }


async def _call_gemini_structured_extraction(
    *,
    prompt: str,
    inline_mime_type: str | None = None,
    inline_data: bytes | None = None,
) -> dict[str, Any] | None:
    api_key = settings.google_gemini_api_key.strip()
    if not api_key:
        return None

    preferred_model = settings.google_gemini_model.strip() or "gemini-1.5-flash-latest"
    fallback_models = [
        preferred_model,
        "gemini-1.5-flash-latest",
        "gemini-1.5-pro-latest",
        "gemini-2.0-flash",
    ]
    models_to_try: list[str] = []
    seen_models: set[str] = set()
    for model in fallback_models:
        m = model.strip()
        if m and m not in seen_models:
            models_to_try.append(m)
            seen_models.add(m)

    parts: list[dict[str, Any]] = [{"text": prompt}]
    if inline_mime_type and inline_data:
        parts.append(
            {
                "inlineData": {
                    "mimeType": inline_mime_type,
                    "data": base64.b64encode(inline_data).decode("ascii"),
                }
            }
        )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": parts,
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    body: dict[str, Any] | None = None
    for model_name in models_to_try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={api_key}"
        )
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
            break
        except Exception as exc:
            detail = ""
            status_code = None
            if isinstance(exc, httpx.HTTPStatusError):
                status_code = exc.response.status_code
                try:
                    detail = exc.response.text[:600]
                except Exception:
                    detail = ""
            logger.warning(
                "Gemini extraction request failed (model=%s): %s %s",
                model_name,
                exc,
                detail,
            )
            if status_code in (400, 404):
                continue
            return None

    if body is None:
        return None

    try:
        candidates = body.get("candidates") or []
        first = candidates[0] if candidates else {}
        parts = first.get("content", {}).get("parts", [])
        text = "\n".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
        parsed = _extract_json_block(text)
        if parsed is None:
            logger.warning("Gemini response did not contain parseable JSON")
            return None
        return _normalize_gemini_payload(parsed)
    except Exception as exc:
        logger.warning("Failed to parse Gemini extraction response: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Common lab-test patterns   name: value  unit  reference-range
# ---------------------------------------------------------------------------
_LAB_LINE_RE = re.compile(
    r"(?P<test_name>[A-Za-z\s\-/()]+?)\s+"
    r"(?P<value>[\d]+\.?\d*)\s*"
    r"(?P<unit>[a-zA-Z/%]+)?\s*"
    r"(?P<ref_range>[\d.\-–]+\s*[-–]\s*[\d.]+)?",
)

_PATIENT_NAME_RE = re.compile(
    r"(?:Patient\s*(?:Name)?|Name)\s*[:\-]?\s*(?P<name>[A-Z][a-zA-Z\s\-'.]+)",
    re.IGNORECASE,
)
_DOB_RE = re.compile(
    r"(?:D\.?O\.?B\.?|Date\s*of\s*Birth|Birth\s*Date)\s*[:\-]?\s*"
    r"(?P<dob>\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
    re.IGNORECASE,
)
_MRN_RE = re.compile(
    r"(?:MRN|Medical\s*Record\s*(?:Number|No\.?|#))\s*[:\-]?\s*(?P<mrn>[A-Z0-9\-]+)",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r"(?:Phone|Tel|Telephone|Contact)\s*[:\-]?\s*"
    r"(?P<phone>\+?[\d\s\-().]{7,20})",
    re.IGNORECASE,
)
_INSURANCE_RE = re.compile(
    r"(?:Insurance|Insurer|Carrier|Plan)\s*[:\-]?\s*(?P<insurance>[A-Za-z\s\-&.]+?)(?:\n|$)",
    re.IGNORECASE,
)

_MEDICATION_SECTION_RE = re.compile(
    r"(?:Medications?|Current\s+Medications?|Active\s+Medications?|Rx|Prescriptions?)"
    r"\s*[:\-]?\s*\n(?P<block>(?:.*\n?){1,30})",
    re.IGNORECASE,
)
_MEDICATION_LINE_RE = re.compile(
    r"(?P<name>[A-Za-z][\w\-]+(?:\s+[\w\-]+)?)"
    r"(?:\s+(?P<dosage>\d+\s*(?:mg|mcg|ml|g|IU|units?)(?:/\w+)?))?",
    re.IGNORECASE,
)
_MEDICATION_KEYWORDS = {
    "metformin", "lisinopril", "atorvastatin", "amlodipine", "omeprazole",
    "losartan", "gabapentin", "hydrochlorothiazide", "sertraline", "simvastatin",
    "levothyroxine", "acetaminophen", "ibuprofen", "aspirin", "warfarin",
    "clopidogrel", "insulin", "glipizide", "prednisone", "albuterol",
    "amoxicillin", "azithromycin", "ciprofloxacin", "furosemide", "pantoprazole",
    "rosuvastatin", "carvedilol", "metoprolol", "montelukast", "tamsulosin",
    "duloxetine", "escitalopram", "fluoxetine", "bupropion", "trazodone",
    "tramadol", "oxycodone", "hydrocodone", "morphine", "cephalexin",
    "doxycycline", "clindamycin", "meloxicam", "naproxen", "diclofenac",
    "cyclobenzaprine", "alprazolam", "lorazepam", "clonazepam", "zolpidem",
}


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF file."""
    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def extract_tables_from_pdf(file_bytes: bytes) -> list[list[list[str | None]]]:
    """Extract all tables from a PDF as lists of rows."""
    tables: list[list[list[str | None]]] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_tables = page.extract_tables()
            if page_tables:
                tables.extend(page_tables)
    return tables


def parse_patient_info(text: str) -> dict[str, str | None]:
    """Extract patient demographic info from PDF text."""
    info: dict[str, str | None] = {}

    m = _PATIENT_NAME_RE.search(text)
    if m:
        info["name"] = m.group("name").strip()

    m = _DOB_RE.search(text)
    if m:
        info["dob"] = m.group("dob").strip()

    m = _MRN_RE.search(text)
    if m:
        info["mrn"] = m.group("mrn").strip()

    m = _PHONE_RE.search(text)
    if m:
        info["phone"] = m.group("phone").strip()

    m = _INSURANCE_RE.search(text)
    if m:
        info["insurance"] = m.group("insurance").strip()

    return info


def parse_lab_results(text: str) -> list[dict[str, Any]]:
    """
    Extract lab result rows from PDF text.

    Returns a list of dicts with keys:
      test_name, value (float), unit, reference_range, flag
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for m in _LAB_LINE_RE.finditer(text):
        test_name = m.group("test_name").strip()
        if not test_name or test_name.lower() in seen:
            continue

        try:
            value = float(m.group("value"))
        except (TypeError, ValueError):
            continue

        unit = (m.group("unit") or "").strip()
        ref_range = (m.group("ref_range") or "").strip().replace("–", "-")

        flag = "normal"
        if ref_range and "-" in ref_range:
            try:
                parts = ref_range.split("-")
                low, high = float(parts[0].strip()), float(parts[1].strip())
                if value < low:
                    flag = "low"
                elif value > high:
                    flag = "high"
            except (ValueError, IndexError):
                pass

        results.append({
            "test_name": test_name,
            "value": value,
            "unit": unit,
            "reference_range": ref_range,
            "flag": flag,
        })
        seen.add(test_name.lower())

    return results


def parse_medications(text: str) -> list[dict[str, str]]:
    """
    Extract medications from PDF text.
    Looks for a medications section first, then falls back to keyword matching.
    """
    medications: list[dict[str, str]] = []
    seen: set[str] = set()

    section_match = _MEDICATION_SECTION_RE.search(text)
    if section_match:
        block = section_match.group("block")
        for line in block.strip().split("\n"):
            line = line.strip().lstrip("•-–*123456789. ")
            if not line or len(line) < 3:
                continue
            if any(kw in line.lower() for kw in ("diagnosis", "condition", "allerg", "history", "lab ", "result")):
                break
            m = _MEDICATION_LINE_RE.match(line)
            if m:
                name = m.group("name").strip()
                dosage = (m.group("dosage") or "").strip()
                if name.lower() not in seen and len(name) > 2:
                    medications.append({"name": name, "dosage": dosage, "status": "active"})
                    seen.add(name.lower())

    for keyword in _MEDICATION_KEYWORDS:
        if keyword in seen:
            continue
        pattern = re.compile(
            rf"\b({re.escape(keyword)})\s*(\d+\s*(?:mg|mcg|ml|g|IU|units?)?(?:/\w+)?)?",
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if m:
            name = m.group(1).strip()
            dosage = (m.group(2) or "").strip()
            if name.lower() not in seen:
                medications.append({"name": name.capitalize(), "dosage": dosage, "status": "active"})
                seen.add(name.lower())

    return medications


async def parse_image_document_with_gemini(
    file_bytes: bytes,
    mime_type: str,
) -> dict[str, Any]:
    prompt = (
        "You are extracting structured data from a medical report image. "
        "Return strict JSON with keys: raw_text (string), patient_info (object with name,dob,mrn,phone,insurance), "
        "lab_results (array of objects with test_name,value,unit,reference_range,flag), medications (array), tables (array). "
        "Do not include markdown."
    )

    gemini_data = await _call_gemini_structured_extraction(
        prompt=prompt,
        inline_mime_type=mime_type,
        inline_data=file_bytes,
    )

    if gemini_data:
        return {
            **gemini_data,
            "page_count": 1,
            "extracted_at": datetime.utcnow().isoformat() + "Z",
            "extraction_source": "gemini_vision",
        }

    return {
        "raw_text": "",
        "patient_info": {},
        "lab_results": [],
        "medications": [],
        "tables": [],
        "page_count": 1,
        "extracted_at": datetime.utcnow().isoformat() + "Z",
        "extraction_source": "none",
    }


async def parse_pdf_document_with_gemini(file_bytes: bytes) -> dict[str, Any] | None:
    prompt = (
        "You are extracting structured data from a medical report PDF. "
        "Return strict JSON with keys: raw_text (string), patient_info (object with name,dob,mrn,phone,insurance), "
        "lab_results (array of objects with test_name,value,unit,reference_range,flag), medications (array), tables (array). "
        "Do not include markdown."
    )

    gemini_data = await _call_gemini_structured_extraction(
        prompt=prompt,
        inline_mime_type="application/pdf",
        inline_data=file_bytes,
    )
    if not gemini_data:
        return None

    return {
        **gemini_data,
        "extracted_at": datetime.utcnow().isoformat() + "Z",
        "extraction_source": "gemini_pdf",
    }


async def enrich_report_text_with_gemini(raw_text: str) -> dict[str, Any] | None:
    content = (raw_text or "").strip()
    if len(content) < 40:
        return None

    prompt = (
        "You are extracting structured data from medical report text. "
        "Return strict JSON with keys: raw_text, patient_info, lab_results, medications, tables. "
        "Use only facts from the input text below.\n\n"
        f"REPORT_TEXT:\n{content[:18000]}"
    )
    return await _call_gemini_structured_extraction(prompt=prompt)


def parse_pdf_document(file_bytes: bytes) -> dict[str, Any]:
    """
    Full PDF parsing pipeline — returns structured data extracted from
    a medical PDF document.

    Returns:
        {
            "raw_text": str,
            "patient_info": { name, dob, mrn, phone, insurance },
            "lab_results": [ { test_name, value, unit, reference_range, flag } ],
            "tables": [ ... ],
            "page_count": int,
            "extracted_at": str (ISO timestamp),
        }
    """
    text = extract_text_from_pdf(file_bytes)
    tables = extract_tables_from_pdf(file_bytes)
    patient_info = parse_patient_info(text)
    lab_results = parse_lab_results(text)
    medications = parse_medications(text)

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        page_count = len(pdf.pages)

    return {
        "raw_text": text,
        "patient_info": patient_info,
        "lab_results": lab_results,
        "medications": medications,
        "tables": tables,
        "page_count": page_count,
        "extracted_at": datetime.utcnow().isoformat() + "Z",
    }
