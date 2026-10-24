from app.services import postgres_service as db

data = db.list_patients()
for p in data:
    print(f"Patient ID: {p['id']}, Phone: {p['phone']}")

logs = db.list_call_logs()[:2]
import json
print("Latest Call Logs:", json.dumps(logs, indent=2))
