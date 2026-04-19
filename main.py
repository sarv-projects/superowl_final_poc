"""SuperOwl Voice AI POC — Main Application Entry Point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pathlib

from app.routers import (
    businesses,
    onboarding,
    playground,
    prompts,
    slack_actions,
    slack_events,
    trigger,
    vapi_webhook,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # No database setup needed — using JSON file storage
    yield


app = FastAPI(
    title="SuperOwl Voice AI",
    description="Multi‑tenant voice AI platform for inbound/outbound calls",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(businesses.router, prefix="/businesses", tags=["Businesses"])
app.include_router(prompts.router, prefix="/prompts", tags=["Prompts"])
app.include_router(trigger.router, prefix="/trigger", tags=["Call Triggers"])
app.include_router(vapi_webhook.router, prefix="/vapi-webhook", tags=["VAPI Webhooks"])
# Note: /vapi-webhook/notify-owner and /vapi-webhook/owner-decision are handled by the same router

# Dual-agent endpoints (must be at root level for VAPI tool calls)
from app.routers.vapi_webhook import notify_owner, owner_decision
app.add_api_route("/notify-owner", notify_owner, methods=["POST"], tags=["Dual Agent"])
app.add_api_route("/owner-decision", owner_decision, methods=["POST"], tags=["Dual Agent"])

app.include_router(slack_events.router, prefix="/slack/events", tags=["Slack Events"])
app.include_router(
    slack_actions.router, prefix="/slack/actions", tags=["Slack Actions"]
)
app.include_router(onboarding.router, prefix="/onboarding", tags=["Onboarding"])
app.include_router(playground.router, prefix="/playground", tags=["Playground"])


# Frontend static files
FRONTEND_DIR = pathlib.Path(__file__).resolve().parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_frontend():
    """Serve the Voice Configuration dashboard."""
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
