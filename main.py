"""SuperOwl Voice AI POC — Main Application Entry Point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pathlib
import httpx

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


async def _auto_detect_ngrok() -> str | None:
    """Ask ngrok's local API for the current public URL."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:4040/api/tunnels")
            tunnels = resp.json().get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    return t["public_url"]
    except Exception:
        pass
    return None


async def _configure_vapi_phone_number(ngrok_base: str) -> None:
    """Remove hardcoded assistant from ALL VAPI phone numbers, set server URL so assistant-request fires."""
    from app.core.config import settings
    webhook_url = f"{ngrok_base}/vapi-webhook"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get all phone numbers
            list_resp = await client.get(
                "https://api.vapi.ai/phone-number",
                headers={"Authorization": f"Bearer {settings.VAPI_API_KEY}"},
            )
            list_resp.raise_for_status()
            phone_numbers = list_resp.json()

            # Patch each one
            for phone in phone_numbers:
                phone_id = phone.get("id")
                if not phone_id:
                    continue
                resp = await client.patch(
                    f"https://api.vapi.ai/phone-number/{phone_id}",
                    headers={
                        "Authorization": f"Bearer {settings.VAPI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "assistantId": None,
                        "squadId": None,
                        "server": {"url": webhook_url},
                    },
                )
                if resp.is_success:
                    print(f"✅ Phone {phone.get('name')} ({phone_id[:8]}...) → server URL: {webhook_url}")
                else:
                    print(f"⚠️  Phone {phone_id[:8]}... update failed ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        print(f"⚠️  VAPI phone number update error: {e}")


async def _configure_vapi_assistants(ngrok_base: str) -> None:
    """Update server URL on all three assistants so tool calls always hit the current ngrok."""
    from app.core.config import settings
    webhook_url = f"{ngrok_base}/vapi-webhook"
    assistant_ids = [
        settings.VAPI_INBOUND_ASSISTANT_ID,
        settings.VAPI_OUTBOUND_ASSISTANT_ID,
        settings.VAPI_OWNER_ASSISTANT_ID,
    ]
    async with httpx.AsyncClient(timeout=10.0) as client:
        for aid in assistant_ids:
            if not aid:
                continue
            try:
                resp = await client.patch(
                    f"https://api.vapi.ai/assistant/{aid}",
                    headers={
                        "Authorization": f"Bearer {settings.VAPI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={"server": {"url": webhook_url}},
                )
                if resp.is_success:
                    print(f"✅ Assistant {aid[:8]}... → server URL updated")
                else:
                    print(f"⚠️  Assistant {aid[:8]}... update failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                print(f"⚠️  Assistant {aid[:8]}... update error: {e}")


def _print_nango_webhook_url(ngrok_base: str) -> None:
    """Print the Nango webhook URL that must be set manually in the Nango dashboard."""
    webhook_url = f"{ngrok_base}/onboarding/webhook/nango"
    print(f"ℹ️  Nango webhook URL (set manually in Nango dashboard): {webhook_url}")


async def _patch_env_ngrok(ngrok_base: str) -> None:
    """Rewrite VAPI_WEBHOOK_URL in .env with the new ngrok base URL."""
    env_path = pathlib.Path(".env")
    if not env_path.exists():
        return
    lines = env_path.read_text().splitlines()
    new_lines = []
    for line in lines:
        if line.startswith("VAPI_WEBHOOK_URL="):
            new_lines.append(f"VAPI_WEBHOOK_URL={ngrok_base}/vapi-webhook")
        else:
            new_lines.append(line)
    env_path.write_text("\n".join(new_lines) + "\n")
    print(f"✅ .env VAPI_WEBHOOK_URL updated: {ngrok_base}/vapi-webhook")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: auto-detect ngrok, patch .env, configure VAPI phone number."""
    from app.core.config import settings

    ngrok_url = await _auto_detect_ngrok()
    if ngrok_url:
        current = settings.VAPI_WEBHOOK_URL.replace("/vapi-webhook", "")
        if ngrok_url != current:
            await _patch_env_ngrok(ngrok_url)
            settings.VAPI_WEBHOOK_URL = f"{ngrok_url}/vapi-webhook"
            print(f"🔄 ngrok URL changed: {current} → {ngrok_url}")
        await _configure_vapi_phone_number(ngrok_url)
        await _configure_vapi_assistants(ngrok_url)
        _print_nango_webhook_url(ngrok_url)
    else:
        print("ℹ️  ngrok not detected — using VAPI_WEBHOOK_URL from .env")
        base = settings.VAPI_WEBHOOK_URL.replace("/vapi-webhook", "")
        await _configure_vapi_phone_number(base)
        await _configure_vapi_assistants(base)
        _print_nango_webhook_url(base)

    yield


app = FastAPI(
    title="SuperOwl Voice AI",
    description="Multi‑tenant voice AI platform for inbound/outbound calls",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(businesses.router, prefix="/businesses", tags=["Businesses"])
app.include_router(prompts.router, prefix="/prompts", tags=["Prompts"])
app.include_router(trigger.router, prefix="/trigger", tags=["Call Triggers"])
app.include_router(vapi_webhook.router, prefix="/vapi-webhook", tags=["VAPI Webhooks"])

from app.routers.vapi_webhook import notify_owner, owner_decision
app.add_api_route("/notify-owner", notify_owner, methods=["POST"], tags=["Dual Agent"])
app.add_api_route("/owner-decision", owner_decision, methods=["POST"], tags=["Dual Agent"])

app.include_router(slack_events.router, prefix="/slack/events", tags=["Slack Events"])
app.include_router(slack_actions.router, prefix="/slack/actions", tags=["Slack Actions"])
app.include_router(onboarding.router, prefix="/onboarding", tags=["Onboarding"])
app.include_router(playground.router, prefix="/playground", tags=["Playground"])

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
