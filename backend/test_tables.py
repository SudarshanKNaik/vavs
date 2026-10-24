from app.services import postgres_service as db

def check_tables():
    tables = [
        "patients", "workflows", "call_logs", "patient_conditions", "patient_medications",
        "notifications", "lab_orders", "referrals", "staff_assignments", "reports", "pdf_documents"
    ]
    with db._cursor() as cur:
        for t in tables:
            try:
                cur.execute(f"SELECT 1 FROM {t} LIMIT 1")
                print(f"✅ {t} exists")
            except Exception as e:
                print(f"❌ {t} does not exist: {e}")

if __name__ == "__main__":
    check_tables()
