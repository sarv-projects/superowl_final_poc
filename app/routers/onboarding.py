"""Slack OAuth onboarding flow using Nango."""

import hmac
import json
from hashlib import sha256
from datetime import datetime
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.core import json_storage
from app.services.nango_service import nango_client

router = APIRouter()


def _normalize_phone(phone: str) -> str:
    return "".join(filter(str.isdigit, phone))[-10:]


async def _find_business_by_phone(phone: str):
    candidates = [phone, f"+91{_normalize_phone(phone)}", _normalize_phone(phone)]
    for candidate in candidates:
        business = await json_storage.get_business_by_phone(candidate)
        if business:
            return business
    return None


def _verify_nango_signature(raw_body: bytes, signature: str | None) -> bool:
    if not settings.NANGO_WEBHOOK_SECRET:
        return True
    if not signature:
        return False
    expected = hmac.new(
        settings.NANGO_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.get("/connect/session")
async def create_nango_session(phone: str):
    """Start Slack OAuth flow — PRODUCTION VERSION (uses real business UUID)."""
    business = await _find_business_by_phone(phone)
    if not business:
        all_biz = await json_storage.list_businesses()
        biz_phones = [b.get("phone_number") for b in all_biz]
        raise HTTPException(
            status_code=404,
            detail=f"Business not found for phone '{phone}'. Available phones: {biz_phones}"
        )

    # === PRODUCTION CHANGE ===
    # Use the real business UUID as connection_id (stable, unique, no phone dependency)
    connection_id = str(business["id"])

    try:
        # Nango client's create_session expects `end_user_id` (single param).
        session_data = await nango_client.create_session(end_user_id=connection_id)

        # Store the exact ID we sent to Nango
        business["nango_connection_id"] = connection_id
        await json_storage.update_business(business["id"], business)

        return {"connect_link": session_data.get("data", {}).get("connect_link")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Nango session creation failed: {e}")


@router.get("/callback/slack")
async def slack_oauth_callback(request: Request):
    """OAuth callback after Slack connection."""
    return HTMLResponse("<h1>✅ Slack Connected! You can close this window.</h1>")


@router.post("/webhook/slack")
async def nango_webhook(request: Request):
    """Handle Nango auth webhooks and finalize workspace metadata."""
    raw_body = await request.body()
    signature = request.headers.get("x-nango-signature")
    if not _verify_nango_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    print("🔍 FULL NANGO WEBHOOK PAYLOAD:", json.dumps(payload, indent=2))

    # Nango now sends our business UUID
    connection_id = (
        payload.get("endUser", {}).get("endUserId")
        or payload.get("connectionId")
        or payload.get("connection_id")
    )

    if not connection_id:
        print("❌ No connection_id found in webhook")
        return {"status": "ignored", "reason": "no_connection_id"}

    print(f"🔑 Extracted connection_id: {connection_id}")

    # Lookup by the exact business UUID we stored
    businesses = await json_storage.list_businesses()
    business = None
    for b in businesses:
        stored = b.get("nango_connection_id")
        if stored and str(stored) == str(connection_id):
            business = b
            break

    if not business:
        print("❌ Still no business found for this webhook")
        return {"status": "ignored", "reason": "business_not_found"}

    # === FORCE UPDATE ===
    business["nango_connection_id"] = str(connection_id)
    business["slack_workspace"] = "Connected"
    business["slack_workspace_name"] = "Connected"
    business["updated_at"] = datetime.utcnow().isoformat()

    await json_storage.update_business(business["id"], business)

    print(f"✅ SUCCESS: Updated business {business.get('id')} with Slack connection {connection_id}")

    return {"status": "ok", "business_id": business["id"]}

@router.get("/slack/channels")
async def get_slack_channels(phone: str):
    """Return current Slack channels saved for this business."""
    business = await _find_business_by_phone(phone)
    if not business:
        return {"live_channel": "", "summary_channel": ""}

    return {
        "live_channel": business.get("slack_live_channel", ""),
        "summary_channel": business.get("slack_summary_channel", "")
    }