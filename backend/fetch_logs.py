from app.services import postgres_service as db
import json

def fetch_logs():
    data = db.list_call_logs()[:5]
    if not data:
        print("No logs.")
        return
        
    for log in data:
        print(f"\n--- Call Log {log['id']} ---")
        exec_log = log.get("execution_log", [])
        webhook_node = next((node for node in exec_log if node.get("node_id") == "elevenlabs_webhook"), None)
        if webhook_node:
            print(json.dumps({
                "patient_confirmed": webhook_node.get("patient_confirmed"),
                "confirmed_date": webhook_node.get("confirmed_date"),
                "confirmed_time": webhook_node.get("confirmed_time"),
                "call_outcome": webhook_node.get("call_outcome"),
                "transcript_preview": webhook_node.get("transcript", "")[-200:],
            }, indent=2))
        else:
            print("No webhook node.")

if __name__ == "__main__":
    fetch_logs()
