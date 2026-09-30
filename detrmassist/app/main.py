"""DetrmAssist — FastAPI entry point."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import routes_decisions, routes_disruptions, routes_trace_log, routes_webhooks
from app.auth import jira_oauth
from app.db import init_db

app = FastAPI(title="DetrmAssist", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_disruptions.router)
app.include_router(routes_decisions.router)
app.include_router(routes_trace_log.router)
app.include_router(routes_webhooks.router)
app.include_router(jira_oauth.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "product": "DetrmAssist"}


# Serves frontend/index.html at the root URL. Mounted last, on purpose —
# Starlette matches routes in registration order, so the API routes above
# are always checked first and this only catches what's left. Resolved
# from this file's own location, not the working directory, so it works
# no matter where `uvicorn` is launched from.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
