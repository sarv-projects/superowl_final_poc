"""Slack OAuth onboarding flow using Nango."""

import hmac
import json
from hashlib import sha256
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
import asyncio
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


@router.post("/webhook/nango")
async def nango_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-nango-signature")
    if not _verify_nango_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    print("🔍 FULL NANGO WEBHOOK PAYLOAD:", json.dumps(payload, indent=2))

    nango_internal_id = payload.get("connectionId")
    business_uuid = payload.get("endUser", {}).get("endUserId")

    if not nango_internal_id or not business_uuid:
        print("❌ Missing connectionId or endUserId")
        return {"status": "ignored", "reason": "missing_ids"}

    business = await json_storage.get_business(business_uuid)
    if not business:
        print(f"❌ Business not found for UUID: {business_uuid}")
        return {"status": "ignored", "reason": "business_not_found"}

    business["nango_connection_id"] = nango_internal_id
    business["slack_workspace"] = "Connected"
    business["slack_workspace_name"] = "Connected"
    business["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Auto-fetch channel only if not already set
    if not business.get("slack_channel"):
        try:
            await asyncio.sleep(3)
            channels = await nango_client.list_channels(connection_id=nango_internal_id)
            if channels:
                selected = channels[0]["name"]
                business["slack_channel"] = selected
                print(f"✅ Auto-set Slack channel: {selected}")
            else:
                print("⚠️ No channels returned — user must set slack_channel manually via dashboard")
        except Exception as e:
            print(f"⚠️ Could not auto-fetch Slack channel: {e}")

    await json_storage.update_business(business["id"], business)
    print(f"✅ SUCCESS: Business {business_uuid} → Nango ID {nango_internal_id}")

    return {"status": "ok", "business_id": business_uuid}


# Alias for backwards compatibility with old Nango dashboard config
@router.post("/webhook/slack")
async def nango_webhook_slack_alias(request: Request):
    return await nango_webhook(request)

@router.get("/slack/channels")
async def get_slack_channels(phone: str):
    """Return current Slack channels saved for this business."""
    business = await _find_business_by_phone(phone)
    if not business:
        return {"live_channel": "", "summary_channel": "", "nango_connection_id": "", "status": "not_found"}
    return {
        "live_channel": business.get("slack_channel", ""),
        "summary_channel": business.get("slack_channel", ""),
        "nango_connection_id": business.get("nango_connection_id", ""),
        "slack_workspace": business.get("slack_workspace", ""),
        "status": "connected" if business.get("nango_connection_id") and business.get("slack_channel") else "incomplete",
    }


@router.post("/slack/set-channel")
async def set_slack_channel(phone: str, channel: str):
    """Manually set the Slack channel for a business (no # prefix needed)."""
    business = await _find_business_by_phone(phone)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    business["slack_channel"] = channel.lstrip("#")
    business["updated_at"] = datetime.now(timezone.utc).isoformat()
    await json_storage.update_business(business["id"], business)
    return {"status": "ok", "slack_channel": business["slack_channel"]}


@router.get("/slack/list-channels")
async def list_slack_channels(phone: str):
    """Fetch live channel list from Slack via Nango for a business."""
    business = await _find_business_by_phone(phone)
    if not business or not business.get("nango_connection_id"):
        raise HTTPException(status_code=404, detail="Business not connected to Slack")
    try:
        channels = await nango_client.list_channels(connection_id=str(business["nango_connection_id"]))
        return {"channels": [c["name"] for c in channels]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))