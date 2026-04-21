"""Slack Events API handler for messages (whisper coaching)."""

from fastapi import APIRouter, Request

from app.core import json_storage
from app.services.nango_service import nango_client
from app.services.vapi_service import vapi_client

router = APIRouter()


@router.post("")
async def slack_events(request: Request):
    """Handle Slack events (URL verification and messages)."""
    body = await request.json()

    # Slack URL verification challenge
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    # Handle event callbacks
    event = body.get("event", {})
    event_type = event.get("type")

    if event_type == "message" and event.get("thread_ts"):
        # Message in a thread — check if it's a live call thread
        thread_ts = event["thread_ts"]
        message_text = event.get("text", "")
        bot_id = event.get("bot_id")

        # Ignore bot messages to prevent loops
        if bot_id:
            return {"status": "ignored_bot_message"}

        # Find call log by thread_ts
        all_logs = await json_storage.list_all_call_logs(limit=10000)
        call_log = None
        for log in all_logs:
            if log.get("slack_live_thread_ts") == thread_ts:
                call_log = log
                break

        if not call_log:
            return {"status": "not_a_call_thread"}

        # Get business to check whisper setting
        business = await json_storage.get_business(call_log["business_id"])

        if not business or not business.get("whisper_coaching_via_slack", True):
            return {"status": "whisper_disabled"}

        # Inject whisper into VAPI call
        whisper_payload = {
            "role": "system",
            "content": f"WHISPER FROM OWNER: {message_text}",
        }

        try:
            await vapi_client.send_message(call_log["vapi_call_id"], whisper_payload)

            # Confirm in Slack thread
            if business.get("nango_connection_id") and call_log.get("slack_live_thread_ts"):
                await nango_client.proxy_request(
                    connection_id=str(business.get("nango_connection_id")),
                    method="POST",
                    endpoint="chat.postMessage",
                    data={
                        "channel": business.get("slack_channel"),
                        "thread_ts": call_log.get("slack_live_thread_ts"),
                        "text": f"✅ Whisper delivered: _{message_text}_",
                    },
                )
        except Exception as e:
            print(f"Whisper injection failed: {e}")

    return {"status": "ok"}
