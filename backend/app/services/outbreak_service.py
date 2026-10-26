from __future__ import annotations

"""
Outbreak Watch: early warning of local disease clusters from AI call data.

Every completed AI call is scanned for symptoms the *patient* mentions
(English, Hindi and Kannada, negation-aware), the symptoms are grouped into a
syndrome, and the report is tagged with the patient's locality.

Detection compares each area's last 7 days with that same area's previous 28
days. Under a Poisson model of the baseline rate, an area is flagged when the
week's count would happen by chance less than 5% (watch) or 1% (alert) of the
time. A rise in dengue-like illness also feeds a platelet demand estimate for
the blood side of CareSync.
"""

import logging
import math
import random
import re
import threading
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic, sleep
from typing import Any

import httpx

import app.services.postgres_service as db

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
BASELINE_DAYS = 28
HISTORY_DAYS = WINDOW_DAYS + BASELINE_DAYS

# A brand-new cluster has a zero baseline; assume at least one case a week so
# two or three scattered reports don't look like an outbreak.
MIN_EXPECTED_PER_WEEK = 1.0
WATCH = {"min_cases": 3, "p": 0.05}
ALERT = {"min_cases": 5, "p": 0.01}

# Planning assumptions for the platelet estimate (shown on the page).
PLATELET_NEED_SHARE = 0.15  # share of dengue-like cases needing a platelet transfusion
UNITS_PER_EPISODE = 1  # single-donor (apheresis) platelet units per transfusion
MAX_GROWTH = 2.0  # cap on week-over-week growth used to project next week

SYNDROMES = {
    "dengue_like": "Dengue-like fever",
    "respiratory": "Respiratory illness",
    "gastro": "Diarrhoea & vomiting",
    "fever": "Fever, unspecified",
}
# Syndromes that are watched for clusters. Fever on its own is too unspecific.
WATCHED_SYNDROMES = ("dengue_like", "respiratory", "gastro")

SYMPTOM_LABELS = {
    "fever": "Fever",
    "chills": "Chills",
    "body_pain": "Body / joint pain",
    "headache": "Headache",
    "eye_pain": "Pain behind the eyes",
    "rash": "Rash",
    "bleeding": "Bleeding",
    "low_platelets": "Low platelets",
    "vomiting": "Vomiting",
    "diarrhoea": "Diarrhoea",
    "abdominal_pain": "Stomach pain",
    "cough": "Cough",
    "breathlessness": "Breathlessness",
    "sore_throat": "Sore throat",
}

# Romanised terms are matched on word boundaries; Devanagari and Kannada terms
# as plain substrings (\b doesn't work with Indic combining marks).
SYMPTOM_TERMS: dict[str, list[str]] = {
    "fever": ["fever", "feverish", "temperature", "bukhar", "bukhaar", "jwara", "jvara", "jwar",
              "बुखार", "ज्वर", "ಜ್ವರ"],
    "chills": ["chills", "shivering", "rigors", "kapkapi", "कंपकंपी", "ಚಳಿ ಜ್ವರ", "ನಡುಕ"],
    "body_pain": ["body pain", "body ache", "bodyache", "body aches", "joint pain", "joints pain",
                  "joint pains", "muscle pain", "badan dard", "jodon mein dard", "mai kai novu",
                  "kai kalu novu", "बदन दर्द", "जोड़ों में दर्द", "जोड़ों का दर्द",
                  "ಮೈ ಕೈ ನೋವು", "ಮೈಕೈ ನೋವು", "ಕೀಲು ನೋವು"],
    "headache": ["headache", "head ache", "head pain", "sir dard", "sar dard", "tale novu",
                 "सिरदर्द", "सिर दर्द", "ತಲೆನೋವು", "ತಲೆ ನೋವು"],
    "eye_pain": ["pain behind the eyes", "pain behind my eyes", "pain behind eyes", "eye pain",
                 "eyes pain", "aankh mein dard", "kannu novu", "आंखों में दर्द", "ಕಣ್ಣು ನೋವು"],
    "rash": ["rash", "rashes", "red spots", "daane", "dadde", "दाने", "चकत्ते", "ದದ್ದು"],
    "bleeding": ["bleeding gums", "gum bleeding", "gums bleeding", "nose bleed", "nosebleed",
                 "nose bleeding", "blood in vomit", "black stool", "मसूड़ों से खून", "नाक से खून",
                 "ಒಸಡಿನಲ್ಲಿ ರಕ್ತ", "ಮೂಗಿನಲ್ಲಿ ರಕ್ತ"],
    "low_platelets": ["platelet", "platelets", "प्लेटलेट", "ಪ್ಲೇಟ್ಲೆಟ್"],
    "vomiting": ["vomit", "vomits", "vomiting", "vomited", "throwing up", "nausea", "ulti",
                 "vaanti", "vanti", "उल्टी", "ವಾಂತಿ"],
    "diarrhoea": ["diarrhoea", "diarrhea", "loose motion", "loose motions", "loose stool",
                  "loose stools", "watery stool", "dast", "bhedi", "दस्त", "ಭೇದಿ"],
    "abdominal_pain": ["stomach pain", "stomach ache", "stomachache", "abdominal pain",
                       "tummy pain", "pet dard", "pet mein dard", "hotte novu",
                       "पेट दर्द", "पेट में दर्द", "ಹೊಟ್ಟೆ ನೋವು"],
    "cough": ["cough", "coughing", "khansi", "khaansi", "kemmu", "खांसी", "खाँसी", "ಕೆಮ್ಮು"],
    "breathlessness": ["breathless", "breathlessness", "shortness of breath", "short of breath",
                       "difficulty breathing", "trouble breathing", "saans phoolna",
                       "saans lene mein", "सांस फूलना", "सांस लेने में", "ಉಸಿರಾಟದ ತೊಂದರೆ"],
    "sore_throat": ["sore throat", "throat pain", "gala kharab", "gale mein dard",
                    "गला खराब", "गले में दर्द", "ಗಂಟಲು ನೋವು"],
}

_NEGATION_BEFORE = re.compile(r"\b(no|not|never|without|denies|deny|nor|any)\b")
_NEGATION_AFTER = re.compile(r"\b(nahi|nahin|nai|illa|gone)\b|नहीं|नही|ಇಲ್ಲ")
_CLAUSE_BREAK = re.compile(r"[.?!,;:\n]")
_NO_SYMPTOMS = {"", "none", "no", "nil", "na", "n/a", "no symptoms", "nothing"}

_PATTERNS: list[tuple[str, re.Pattern[str]]] = []
for _code, _terms in SYMPTOM_TERMS.items():
    for _term in _terms:
        escaped = re.escape(_term).replace(r"\ ", r"\s+")
        _PATTERNS.append(
            (_code, re.compile(rf"\b{escaped}\b" if _term.isascii() else escaped))
        )


def _is_negated(text: str, start: int, end: int) -> bool:
    before = _CLAUSE_BREAK.split(text[max(0, start - 30):start])[-1]
    after = _CLAUSE_BREAK.split(text[end:end + 20])[0]
    # Only the last three words before the symptom ("no fever", "not any cough").
    if _NEGATION_BEFORE.search(" ".join(before.split()[-3:])):
        return True
    return bool(_NEGATION_AFTER.search(after))


def extract_symptoms(text: str | None) -> list[str]:
    """Symptom codes mentioned (and not denied) in free text."""
    lowered = (text or "").lower()
    if lowered.strip() in _NO_SYMPTOMS:
        return []
    found: set[str] = set()
    for code, pattern in _PATTERNS:
        for match in pattern.finditer(lowered):
            if not _is_negated(lowered, match.start(), match.end()):
                found.add(code)
                break
    return sorted(found)


def patient_speech(transcript: Any) -> str:
    """
    Only what the patient said. The agent's own questions ("any fever?") must
    never count as a symptom, so text with no speaker roles is ignored.
    """
    if isinstance(transcript, list):
        return "\n".join(
            str(turn.get("message") or "")
            for turn in transcript
            if isinstance(turn, dict) and str(turn.get("role", "")).lower() == "user"
        )
    lines = []
    for line in str(transcript or "").splitlines():
        role, sep, message = line.partition(":")
        if sep and role.strip().lower() in ("user", "patient", "caller"):
            lines.append(message)
    return "\n".join(lines)


def classify_syndrome(symptoms: list[str] | set[str]) -> str | None:
    s = set(symptoms)
    if "low_platelets" in s or ("fever" in s and s & {"body_pain", "headache", "eye_pain", "rash", "bleeding"}):
        return "dengue_like"
    if "diarrhoea" in s or "vomiting" in s:
        return "gastro"
    if s & {"cough", "breathlessness", "sore_throat"}:
        return "respiratory"
    if s & {"fever", "chills"}:
        return "fever"
    return None


# Approximate centroids of Hubli-Dharwad localities, so a patient's area can be
# placed on the map without a geocoding call.
LOCALITIES: dict[str, tuple[str, float, float]] = {
    "old hubli": ("Old Hubli", 15.3647, 75.1520),
    "keshwapur": ("Keshwapur", 15.3440, 75.1420),
    "vidyanagar": ("Vidyanagar", 15.3640, 75.1210),
    "gokul road": ("Gokul Road", 15.3600, 75.1000),
    "deshpande nagar": ("Deshpande Nagar", 15.3530, 75.1390),
    "unkal": ("Unkal", 15.3800, 75.1130),
    "navanagar": ("Navanagar", 15.4040, 75.0790),
    "gopankoppa": ("Gopankoppa", 15.3360, 75.1130),
    "bengeri": ("Bengeri", 15.3330, 75.0950),
    "tarihal": ("Tarihal", 15.3270, 75.1320),
    "anand nagar": ("Anand Nagar", 15.3780, 75.1570),
    "lingaraj nagar": ("Lingaraj Nagar", 15.3690, 75.1060),
    "gadag road": ("Gadag Road", 15.3420, 75.1680),
    "saptapur": ("Saptapur", 15.4620, 75.0160),
    "vidyagiri": ("Vidyagiri", 15.4470, 75.0230),
    "malmaddi": ("Malmaddi", 15.4520, 75.0030),
    "kelgeri": ("Kelgeri", 15.4600, 74.9850),
}


def locate(locality: str | None) -> tuple[str, float | None, float | None] | None:
    """Canonical area name and coordinates; unknown areas keep their name, unmapped."""
    raw = " ".join((locality or "").split())
    if not raw:
        return None
    key = raw.lower()
    matches = [k for k in LOCALITIES if k in key]
    if not matches:
        return raw.title(), None, None
    return LOCALITIES[max(matches, key=len)]


# ---------------------------------------------------------------------------
# Places outside Hubli-Dharwad (OpenStreetMap, cached in place_geocodes)
# ---------------------------------------------------------------------------

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Overpass servers, tried in order (the main one is often overloaded).
_OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
# Both services require an identifying user agent.
_OSM_HEADERS = {"User-Agent": "CareSync-AI/1.0 (outbreak-watch)", "Accept-Language": "en"}
HUBLI_DHARWAD = "Hubli–Dharwad"
_HUBLI_KEYS = {"hubli", "hubballi", "dharwad", "hubli-dharwad", "hubli dharwad", "hubballi-dharwad", "hubli–dharwad"}
# Search for neighbourhoods within this distance (degrees, ~13 km) of the city centre.
_CITY_RADIUS_DEG = 0.12
DEMO_AREA_COUNT = 12

# Well-known neighbourhoods of major cities, so sample data doesn't depend on
# Overpass. Coordinates still come from Nominatim (and are cached).
CITY_NEIGHBOURHOODS: dict[str, list[str]] = {
    "Bengaluru": ["Koramangala", "Indiranagar", "Jayanagar", "Whitefield", "Malleshwaram", "Rajajinagar",
                  "Hebbal", "BTM Layout", "Yelahanka", "Marathahalli", "Banashankari", "HSR Layout"],
    "Mumbai": ["Dharavi", "Kurla", "Andheri", "Bandra", "Dadar", "Colaba", "Malad", "Borivali",
               "Ghatkopar", "Chembur", "Goregaon", "Worli"],
    "Delhi": ["Karol Bagh", "Lajpat Nagar", "Rohini", "Dwarka", "Saket", "Mayur Vihar", "Chandni Chowk",
              "Janakpuri", "Shahdara", "Vasant Kunj", "Pitampura", "Okhla"],
    "Pune": ["Kothrud", "Hadapsar", "Aundh", "Katraj", "Shivajinagar", "Viman Nagar", "Kharadi", "Wakad",
             "Baner", "Swargate", "Yerawada", "Kondhwa"],
    "Hyderabad": ["Secunderabad", "Banjara Hills", "Gachibowli", "Kukatpally", "Charminar", "Ameerpet",
                  "Dilsukhnagar", "Begumpet", "Madhapur", "Mehdipatnam", "LB Nagar", "Uppal"],
    "Chennai": ["T. Nagar", "Adyar", "Mylapore", "Anna Nagar", "Velachery", "Tambaram", "Royapuram",
                "Egmore", "Guindy", "Perambur", "Porur", "Tondiarpet"],
    "Kolkata": ["Salt Lake", "Park Street", "Ballygunge", "Behala", "Dum Dum", "Garia", "Tollygunge",
                "Shyambazar", "Jadavpur", "New Town", "Sealdah", "Howrah"],
    "Mysuru": ["Gokulam", "Kuvempunagar", "Vijayanagar", "Saraswathipuram", "Jayalakshmipuram",
               "Bannimantap", "Nazarbad", "Lashkar Mohalla", "Siddhartha Layout", "Ramakrishnanagar",
               "Hinkal", "Hebbal"],
    "Belagavi": ["Tilakwadi", "Shahapur", "Camp", "Sadashiv Nagar", "Hindwadi", "Vadgaon", "Angol",
                 "Mahantesh Nagar", "Shivaji Nagar", "Bhagya Nagar", "Azam Nagar", "Khasbag"],
}
_CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "mumbai": "Mumbai", "bombay": "Mumbai",
    "delhi": "Delhi", "new delhi": "Delhi", "pune": "Pune", "poona": "Pune", "hyderabad": "Hyderabad",
    "chennai": "Chennai", "madras": "Chennai", "kolkata": "Kolkata", "calcutta": "Kolkata",
    "mysuru": "Mysuru", "mysore": "Mysuru", "belagavi": "Belagavi", "belgaum": "Belagavi",
}

_osm_lock = threading.Lock()
_osm_last_request = 0.0


def _osm_get(url: str, params: dict[str, Any], timeout: float) -> Any:
    """GET with Nominatim's usage policy applied: at most one request a second."""
    global _osm_last_request
    with _osm_lock:
        wait = 1.1 - (monotonic() - _osm_last_request)
        if wait > 0:
            sleep(wait)
        try:
            response = httpx.get(url, params=params, headers=_OSM_HEADERS, timeout=timeout)
        finally:
            _osm_last_request = monotonic()
    response.raise_for_status()
    return response.json()


def _place_key(text: str) -> str:
    return " ".join(text.lower().split())


def geocode_place(query: str) -> dict[str, Any] | None:
    """Coordinates and bounding box of a place, from the cache or Nominatim. None if not found."""
    key = _place_key(query)
    if not key:
        return None
    cached = db.get_place_geocode(key)
    if cached:
        return cached if cached.get("latitude") is not None else None

    try:
        rows = []
        for extra in ({"countrycodes": "in"}, {}):  # prefer India, then anywhere
            rows = _osm_get(_NOMINATIM_URL, {"q": query, "format": "jsonv2", "limit": 1, **extra}, timeout=8)
            if rows:
                break
    except Exception as exc:
        # Network trouble: don't cache, so the next call tries again.
        logger.warning("Geocoding %r failed: %s", query, exc)
        return None

    place: dict[str, Any] = {"query": key}
    if rows:
        top = rows[0]
        south, north, west, east = (float(v) for v in top.get("boundingbox") or [0, 0, 0, 0])
        place.update(
            name=top.get("name") or query.strip().title(),
            latitude=float(top["lat"]),
            longitude=float(top["lon"]),
            south=south, north=north, west=west, east=east,
        )
    db.save_place_geocode(place)
    return place if rows else None


def resolve_place(locality: str | None) -> tuple[str, float | None, float | None] | None:
    """Built-in Hubli-Dharwad areas first, then any other place via OpenStreetMap."""
    place = locate(locality)
    if not place or place[1] is not None:
        return place
    hit = geocode_place(locality or "")
    name = (locality or "").split(",")[0].strip().title()
    return (name, float(hit["latitude"]), float(hit["longitude"])) if hit else (name, None, None)


def _spread(points: list[tuple[str, float, float]], centre: tuple[float, float], count: int):
    """Pick `count` points spread across the city, starting nearest the centre."""
    def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - b[0]) ** 2 + ((a[1] - b[1]) * math.cos(math.radians(a[0]))) ** 2

    remaining = sorted(points, key=lambda p: dist((p[1], p[2]), centre))
    chosen = [remaining.pop(0)]
    while remaining and len(chosen) < count:
        best = max(remaining, key=lambda p: min(dist((p[1], p[2]), (c[1], c[2])) for c in chosen))
        remaining.remove(best)
        chosen.append(best)
    return chosen


def _compass_areas(city: str, lat: float, lon: float) -> list[tuple[str, float, float]]:
    """Fallback when OpenStreetMap lists no neighbourhoods: named zones around the centre."""
    d = 0.035
    zones = [("Central", 0, 0), ("North", d, 0), ("South", -d, 0), ("East", 0, d), ("West", 0, -d),
             ("North-East", d, d), ("North-West", d, -d), ("South-East", -d, d), ("South-West", -d, -d)]
    return [(f"{label} {city}", lat + dlat, lon + dlon) for label, dlat, dlon in zones]


def city_areas(city: str) -> tuple[str, list[tuple[str, float, float]]]:
    """A city's display name and up to DEMO_AREA_COUNT real neighbourhoods with coordinates."""
    if _place_key(city) in _HUBLI_KEYS:
        return HUBLI_DHARWAD, [locate(name) for name, *_ in _DEMO_PATTERN]

    place = geocode_place(city)
    if not place:
        raise ValueError(f"Couldn't find “{city.strip()}” on the map. Try the city's full name.")
    name, lat, lon = place["name"], float(place["latitude"]), float(place["longitude"])
    if place.get("areas"):
        return name, [(a["name"], a["latitude"], a["longitude"]) for a in place["areas"]]

    preset = _CITY_ALIASES.get(_place_key(city))
    if preset:
        name = preset
        hits = []
        for area in CITY_NEIGHBOURHOODS[preset]:
            hit = geocode_place(f"{area}, {preset}")
            if hit:
                hits.append((area, float(hit["latitude"]), float(hit["longitude"])))
        # Drop a match that landed in some other town. Measured from the middle
        # of the neighbourhoods, since a city name can resolve to its district.
        if hits:
            mid_lat = sorted(h[1] for h in hits)[len(hits) // 2]
            mid_lon = sorted(h[2] for h in hits)[len(hits) // 2]
            hits = [h for h in hits if abs(h[1] - mid_lat) < 0.25 and abs(h[2] - mid_lon) < 0.25]
        areas = hits
        if len(areas) >= 6:
            db.save_place_geocode(
                {**place, "name": name, "areas": [{"name": a[0], "latitude": a[1], "longitude": a[2]} for a in areas]}
            )
            return name, areas

    south, north = max(float(place["south"]), lat - _CITY_RADIUS_DEG), min(float(place["north"]), lat + _CITY_RADIUS_DEG)
    west, east = max(float(place["west"]), lon - _CITY_RADIUS_DEG), min(float(place["east"]), lon + _CITY_RADIUS_DEG)
    query = (
        f'[out:json][timeout:25];node["place"~"^(suburb|neighbourhood|quarter)$"]["name"]'
        f"({south},{west},{north},{east});out 200;"
    )
    found: dict[str, tuple[str, float, float]] = {}
    for url in _OVERPASS_URLS:
        try:
            elements = _osm_get(url, {"data": query}, timeout=10).get("elements", [])
        except Exception as exc:
            logger.warning("Neighbourhood lookup for %r on %s failed: %s", city, url, exc)
            continue
        for el in elements:
            tags = el.get("tags", {})
            area_name = (tags.get("name:en") or tags.get("name") or "").strip()
            if area_name and area_name.lower() not in found:
                found[area_name.lower()] = (area_name, float(el["lat"]), float(el["lon"]))
        break
    else:
        return name, _compass_areas(name, lat, lon)  # not cached, so a later try can do better

    areas = _spread(list(found.values()), (lat, lon), DEMO_AREA_COUNT) if len(found) >= 6 else _compass_areas(name, lat, lon)
    db.save_place_geocode(
        {**place, "areas": [{"name": a[0], "latitude": a[1], "longitude": a[2]} for a in areas]}
    )
    return name, areas


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def record_call_symptoms(call_log: dict[str, Any] | None, reported: str, transcript: Any) -> dict[str, Any] | None:
    """Store the symptoms from one finished call. Returns the report, or None if there were none."""
    patient_id = (call_log or {}).get("patient_id")
    if not patient_id:
        return None
    symptoms = sorted(set(extract_symptoms(reported)) | set(extract_symptoms(patient_speech(transcript))))
    syndrome = classify_syndrome(symptoms)
    if not syndrome:
        return None

    patient = db.get_patient(str(patient_id)) or {}
    doctor_id = patient.get("doctor_id") or call_log.get("doctor_id")
    if not doctor_id:
        return None
    place = resolve_place(patient.get("locality"))
    return db.upsert_call_symptom_report(
        {
            "doctor_id": str(doctor_id),
            "patient_id": str(patient_id),
            "call_log_id": str(call_log["id"]),
            "source": "ai_call",
            "locality": place[0] if place else None,
            "latitude": place[1] if place else None,
            "longitude": place[2] if place else None,
            "symptoms": symptoms,
            "syndrome": syndrome,
            "reported_at": call_log.get("created_at") or datetime.now(timezone.utc),
        }
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def poisson_sf(observed: int, expected: float) -> float:
    """P(X >= observed) for X ~ Poisson(expected)."""
    if observed <= 0:
        return 1.0
    term = math.exp(-expected)
    cdf = term
    for k in range(1, observed):
        term *= expected / k
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


def _chance_phrase(p: float) -> str:
    if p < 0.001:
        return "less than 1 in 1,000"
    return f"about 1 in {max(2, round(1 / p)):,}"


def _signal(locality: str, syndrome: str, daily: list[int]) -> dict[str, Any]:
    observed = sum(daily[-WINDOW_DAYS:])
    previous_week = sum(daily[-2 * WINDOW_DAYS:-WINDOW_DAYS])
    baseline_rate = sum(daily[:BASELINE_DAYS]) / BASELINE_DAYS * WINDOW_DAYS
    expected = max(baseline_rate, MIN_EXPECTED_PER_WEEK)
    p = poisson_sf(observed, expected)
    if observed >= ALERT["min_cases"] and p < ALERT["p"]:
        level = "alert"
    elif observed >= WATCH["min_cases"] and p < WATCH["p"]:
        level = "watch"
    else:
        level = "normal"
    return {
        "locality": locality,
        "syndrome": syndrome,
        "syndrome_label": SYNDROMES[syndrome],
        "level": level,
        "observed": observed,
        "previous_week": previous_week,
        "expected": round(baseline_rate, 1),
        "ratio": round(observed / expected, 1),
        "p_value": p,
        "chance": _chance_phrase(p),
        "daily": daily[-2 * WINDOW_DAYS:],
    }


_LEVEL_RANK = {"alert": 2, "watch": 1, "normal": 0}


def summarise(reports: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Pure aggregation over symptom reports; `today` is the clinic's local date."""
    first_day = today - timedelta(days=HISTORY_DAYS - 1)
    days = [first_day + timedelta(days=i) for i in range(HISTORY_DAYS)]
    index = {d: i for i, d in enumerate(days)}

    per_area: dict[tuple[str, str], list[int]] = {}
    trend = {s: [0] * HISTORY_DAYS for s in SYNDROMES}
    coords: dict[str, tuple[float, float]] = {}
    symptom_counts: dict[str, int] = {}
    window_start = HISTORY_DAYS - WINDOW_DAYS

    for r in reports:
        reported = r["reported_at"]
        if isinstance(reported, str):
            reported = datetime.fromisoformat(reported.replace("Z", "+00:00"))
        i = index.get(reported.astimezone(db.CLINIC_TZ).date())
        syndrome = r.get("syndrome")
        if i is None or syndrome not in SYNDROMES:
            continue
        trend[syndrome][i] += 1
        if i >= window_start:
            for code in r.get("symptoms") or []:
                symptom_counts[code] = symptom_counts.get(code, 0) + 1
        area = r.get("locality") or "Area not recorded"
        per_area.setdefault((area, syndrome), [0] * HISTORY_DAYS)[i] += 1
        if r.get("latitude") is not None and r.get("longitude") is not None:
            coords[area] = (float(r["latitude"]), float(r["longitude"]))

    signals = [
        _signal(area, syndrome, daily)
        for (area, syndrome), daily in per_area.items()
        if syndrome in WATCHED_SYNDROMES
    ]
    signals.sort(key=lambda s: (-_LEVEL_RANK[s["level"]], s["p_value"], -s["observed"]))

    areas: dict[str, dict[str, Any]] = {}
    for (area, syndrome), daily in per_area.items():
        entry = areas.setdefault(
            area,
            {
                "locality": area,
                "latitude": coords.get(area, (None, None))[0],
                "longitude": coords.get(area, (None, None))[1],
                "cases": 0,
                "by_syndrome": {},
                "level": "normal",
            },
        )
        week = sum(daily[window_start:])
        entry["cases"] += week
        if week:
            entry["by_syndrome"][syndrome] = week
    for s in signals:
        entry = areas[s["locality"]]
        if _LEVEL_RANK[s["level"]] > _LEVEL_RANK[entry["level"]]:
            entry["level"] = s["level"]

    dengue = trend["dengue_like"]
    this_week, last_week = sum(dengue[window_start:]), sum(dengue[window_start - WINDOW_DAYS:window_start])
    growth = min(MAX_GROWTH, max(0.5, this_week / last_week)) if last_week else (MAX_GROWTH if this_week >= 3 else 1.0)
    projected = round(this_week * growth)

    return {
        "today": today.isoformat(),
        "window_days": WINDOW_DAYS,
        "baseline_days": BASELINE_DAYS,
        "days": [d.isoformat() for d in days],
        "syndromes": [{"key": k, "label": v, "watched": k in WATCHED_SYNDROMES} for k, v in SYNDROMES.items()],
        "trend": trend,
        "signals": signals,
        "areas": sorted(areas.values(), key=lambda a: (-_LEVEL_RANK[a["level"]], -a["cases"])),
        "reports_in_window": sum(sum(series[window_start:]) for series in trend.values()),
        "top_symptoms": [
            {"code": code, "label": SYMPTOM_LABELS.get(code, code), "count": n}
            for code, n in sorted(symptom_counts.items(), key=lambda kv: -kv[1])[:6]
        ],
        "platelets": {
            "dengue_cases_this_week": this_week,
            "dengue_cases_last_week": last_week,
            "growth": round(growth, 2),
            "projected_cases_next_week": projected,
            "projected_units": math.ceil(projected * PLATELET_NEED_SHARE * UNITS_PER_EPISODE),
            "need_share": PLATELET_NEED_SHARE,
            "units_per_episode": UNITS_PER_EPISODE,
        },
    }


def get_outbreak_summary(doctor_id: str, donor_doctor_ids: list[str]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.astimezone(db.CLINIC_TZ).date()
    since = datetime.combine(today - timedelta(days=HISTORY_DAYS - 1), time.min, tzinfo=db.CLINIC_TZ)
    reports = db.list_symptom_reports(doctor_id, since)
    summary = summarise(reports, today)
    month_ago = now - timedelta(days=30)
    summary["calls_analysed_30d"] = db.count_completed_calls(doctor_id, month_ago)
    summary["demo_reports"] = sum(1 for r in reports if r.get("source") == "demo")
    summary["call_reports"] = len(reports) - summary["demo_reports"]
    regions = [r["region"] for r in reports if r.get("source") == "demo" and r.get("region")]
    summary["demo_region"] = max(set(regions), key=regions.count) if regions else None
    summary["platelets"]["eligible_donors"] = db.count_eligible_donors(donor_doctor_ids)
    summary["brief"] = build_brief(summary)
    return summary


def build_brief(summary: dict[str, Any]) -> str:
    """Plain-text situation report for a district health officer. Aggregates only, no patient details."""
    flagged = [s for s in summary["signals"] if s["level"] != "normal"]
    lines = [
        f"CareSync Outbreak Watch: situation report for the {summary['window_days']} days to {summary['today']}",
        "",
        f"Symptom reports from AI follow-up calls this week: {summary['reports_in_window']}",
    ]
    if not flagged:
        lines.append("No area shows an unusual rise against its own 4-week baseline.")
    for s in flagged:
        lines.append(
            f"- {s['level'].upper()}: {s['syndrome_label']} in {s['locality']}: "
            f"{s['observed']} cases vs {s['expected']} expected "
            f"(a rise this large happens by chance {s['chance']})"
        )
    p = summary["platelets"]
    if p["projected_cases_next_week"]:
        lines += [
            "",
            f"Dengue-like cases: {p['dengue_cases_this_week']} this week, {p['dengue_cases_last_week']} last week. "
            f"Projected next week: about {p['projected_cases_next_week']}, "
            f"needing roughly {p['projected_units']} platelet unit(s).",
        ]
    lines += [
        "",
        "Method: each area's last 7 days compared with its previous 28 days (Poisson test). "
        "Counts come from one clinic's patients and are an early signal, not a diagnosis.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

# (locality, syndrome, background cases per day, fixed daily cases over the last
# 7 days, oldest first). Clusters are fixed so every demo shows the same
# picture: two dengue alerts, a diarrhoea alert and one area on watch.
_DEMO_PATTERN = [
    ("Old Hubli", "dengue_like", 0.10, [0, 1, 1, 2, 2, 3, 3]),
    ("Keshwapur", "dengue_like", 0.10, [0, 0, 1, 1, 1, 2, 2]),
    ("Navanagar", "gastro", 0.10, [0, 0, 1, 1, 2, 3, 2]),
    ("Anand Nagar", "dengue_like", 0.04, [0, 0, 1, 0, 1, 1, 1]),
    ("Vidyanagar", "respiratory", 0.35, None),
    ("Gokul Road", "respiratory", 0.20, None),
    ("Deshpande Nagar", "dengue_like", 0.08, None),
    ("Unkal", "gastro", 0.10, None),
    ("Saptapur", "respiratory", 0.20, None),
    ("Vidyagiri", "fever", 0.15, None),
    ("Gopankoppa", "fever", 0.12, None),
    ("Tarihal", "gastro", 0.08, None),
]
_DEMO_SYMPTOMS = {
    "dengue_like": [["fever", "body_pain", "headache"], ["fever", "eye_pain", "body_pain"],
                    ["fever", "rash", "headache"], ["fever", "body_pain", "low_platelets"]],
    "respiratory": [["cough", "fever"], ["cough", "sore_throat"], ["cough", "breathlessness"]],
    "gastro": [["diarrhoea", "vomiting"], ["diarrhoea", "abdominal_pain"], ["vomiting", "abdominal_pain", "fever"]],
    "fever": [["fever"], ["fever", "chills"]],
}


def _poisson_draw(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _assign_demo_roles(areas: list[tuple[str, float, float]]) -> list[tuple[str, float, float]]:
    """
    Order a city's areas to match _DEMO_PATTERN: the main dengue cluster near the
    centre, its two dengue neighbours next to it, the diarrhoea cluster far away.
    """
    def dist(a, b):
        return (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2

    hub, rest = areas[0], list(areas[1:])
    rest.sort(key=lambda a: dist(a, hub))
    near, far = rest[:2], rest[-1:]
    others = [a for a in rest if a not in near and a not in far]
    # Pattern order: main dengue, dengue neighbour, gastro, dengue watch, background...
    return [hub, near[0], far[0], near[1], *others]


def load_demo_data(doctor_id: str, city: str | None = None) -> dict[str, Any]:
    """Replace this doctor's demo reports with five weeks of sample data for a city."""
    region, areas = city_areas(city or HUBLI_DHARWAD)
    if region != HUBLI_DHARWAD:
        areas = _assign_demo_roles(areas)
    db.delete_demo_symptom_reports(doctor_id)
    rng = random.Random(f"outbreak-demo:{doctor_id}:{region}")
    today = datetime.now(timezone.utc).astimezone(db.CLINIC_TZ).date()
    rows = []
    for days_ago in range(HISTORY_DAYS - 1, -1, -1):
        day = today - timedelta(days=days_ago)
        in_window = days_ago < WINDOW_DAYS
        for (_, syndrome, background, cluster), (name, lat, lon) in zip(_DEMO_PATTERN, areas):
            if cluster and in_window:
                count = cluster[WINDOW_DAYS - 1 - days_ago]
            else:
                count = _poisson_draw(rng, background)
            for _ in range(count):
                reported = datetime.combine(day, time(rng.randint(9, 18), rng.randint(0, 59)), tzinfo=db.CLINIC_TZ)
                if reported > datetime.now(timezone.utc):
                    reported = datetime.now(timezone.utc) - timedelta(minutes=rng.randint(5, 120))
                rows.append(
                    {
                        "doctor_id": doctor_id,
                        "source": "demo",
                        "region": region,
                        "locality": name,
                        "latitude": lat,
                        "longitude": lon,
                        "symptoms": rng.choice(_DEMO_SYMPTOMS[syndrome]),
                        "syndrome": syndrome,
                        "reported_at": reported,
                    }
                )
    return {"inserted": db.insert_symptom_reports(rows), "region": region}


def clear_demo_data(doctor_id: str) -> int:
    return db.delete_demo_symptom_reports(doctor_id)
