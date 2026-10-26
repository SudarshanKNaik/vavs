"""
Operator tool: load blood-storing organizations (blood_donor_org) from a CSV.

    python scripts/seed_blood_orgs.py scripts/data/blood_orgs.local.csv
    python scripts/seed_blood_orgs.py my_orgs.csv --doctor-id <uuid>

CSV columns: org_name, phone_number, location, latitude, longitude
(latitude/longitude optional: if blank, "location" is geocoded). Rows are
upserted on (doctor, phone, name), so re-running is safe. Without --doctor-id
the orgs go to the first active doctor.

Real phone numbers belong in a *.local.csv file, which is git-ignored.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.postgres_service as db  # noqa: E402
from app.services.blood_campaign_service import (  # noqa: E402
    _geocode_plain_location,
    _normalize_phone,
    _parse_location_coordinates,
)


def _coords(row: dict) -> tuple[float | None, float | None]:
    lat, lng = (row.get("latitude") or "").strip(), (row.get("longitude") or "").strip()
    if lat and lng:
        return float(lat), float(lng)
    location = row["location"].strip()
    parsed = _parse_location_coordinates(location)
    if parsed[0] is not None:
        return parsed
    return _geocode_plain_location(location)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_file")
    parser.add_argument("--doctor-id")
    args = parser.parse_args()

    doctor_id = args.doctor_id
    if not doctor_id:
        doctors = db.list_doctors() if hasattr(db, "list_doctors") else []
        if not doctors:
            print("No doctor found; pass --doctor-id", file=sys.stderr)
            return 1
        doctor_id = str(doctors[0]["id"])

    orgs = []
    with open(args.csv_file, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            lat, lng = _coords(row)
            if lat is None:
                print(f"! no coordinates for {row['org_name']!r}; it will be ranked last", file=sys.stderr)
            orgs.append(
                {
                    "ngo_name": row["org_name"].strip(),
                    "phone_number": _normalize_phone(row["phone_number"]),
                    "location": row["location"].strip(),
                    "latitude": lat,
                    "longitude": lng,
                }
            )

    result = db.upsert_blood_orgs(doctor_id, orgs)
    print(f"doctor {doctor_id}: {result['created']} created, {result['updated']} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
