"""
MedTrigger — FastAPI application entry point.
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from app.api.endpoints import router, start_follow_up_scheduler
from app.services import postgres_service as db

app = FastAPI(
    title="MedTrigger API",
    description="Drag & Drop Medical Workflow Automation Backend",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS — allow local Next.js dev server and any deployed frontend
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "https://care-sync-ai-delta.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(router, prefix="/api")


@app.on_event("startup")
async def startup_follow_up_scheduler() -> None:
    await start_follow_up_scheduler()


@app.get("/health")
async def health():
    db_ok = await run_in_threadpool(db.ping_db)
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "unreachable",
    }