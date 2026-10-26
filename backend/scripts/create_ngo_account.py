"""
Operator tool: create an NGO organization and/or an NGO staff login.

NGO accounts are never self-registered; run this from the backend folder
with access to DATABASE_URL:

    python scripts/create_ngo_account.py --ngo-name "Asha Foundation" --city Hubli \
        --email staff@asha.org --username "Asha Staff" --role admin

The password is read from the NGO_PASSWORD environment variable or prompted
for interactively, so it never appears in shell history or process lists.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import ngo_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ngo-name", required=True, help="Organization name (reused if it already exists)")
    parser.add_argument("--registration-number")
    parser.add_argument("--contact-email")
    parser.add_argument("--contact-phone")
    parser.add_argument("--city")
    parser.add_argument("--email", help="Staff login email; omit to only create the organization")
    parser.add_argument("--username", help="Staff display name")
    parser.add_argument("--mobile", default="")
    parser.add_argument("--role", choices=("admin", "staff"), default="staff")
    args = parser.parse_args()

    org = ngo_service.create_ngo_organization(
        args.ngo_name,
        registration_number=args.registration_number,
        contact_email=args.contact_email,
        contact_phone=args.contact_phone,
        city=args.city,
    )
    print(f"NGO organization: {org['name']} ({org['id']})")

    if not args.email:
        return 0

    password = os.environ.get("NGO_PASSWORD") or getpass.getpass("Password for the NGO account: ")
    try:
        user = ngo_service.create_ngo_user(
            str(org["id"]),
            email=args.email,
            password=password,
            username=args.username or args.email.split("@")[0],
            mobile=args.mobile,
            member_role=args.role,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"NGO {user['member_role']} account created for {user['email']} ({user['account_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
