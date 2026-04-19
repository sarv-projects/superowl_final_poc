"""Slack Interactive Components handler (buttons)."""

import json

from fastapi import APIRouter, Request

from app.core.config import settings
from app.core import json_storage
from app.services.call_orchestrator import trigger_outbound_callback
from app.services.vapi_service import vapi_client

router = APIRouter()


@router.post("")
async def slack_actions(request: Request):
    """Handle interactive button clicks from Slack."""
    body = await request.form()
    payload = json.loads(body.get("payload", "{}"))

    actions = payload.get("actions", [])
    if not actions:
        return {"status": "no_actions"}

    action = actions[0]
    action_id = action.get("action_id")
    value = action.get("value")  # vapi_call_id or call_log_id or phone

    if action_id in ("takeover", "transfer"):
        # Find call log by vapi_call_id
        call_log = await json_storage.get_call_log_by_vapi_id(value)

        if not call_log:
            return {"response_type": "ephemeral", "text": "⚠️ Call not found."}

        # Check if call still live
        status = await vapi_client.get_call_status(value)
        if status != "in-progress":
            return {"response_type": "ephemeral", "text": "⚠️ Call has already ended."}

        # Get business for fallback number
        business = await json_storage.get_business(call_log["business_id"])

        if not business:
            return {"response_type": "ephemeral", "text": "⚠️ Business not found."}

        # Transfer call
        destination = {
            "type": "sip",
            "sipUri": f"sip:{business.get('fallback_number')}@{settings.VOBIZ_SIP_DOMAIN}",
        }
        await vapi_client.transfer_call(value, destination)

        return {
            "response_type": "in_channel",
            "text": "📞 Transferring call to owner...",
        }

    elif action_id == "end_call":
        # End the call
        try:
            await vapi_client.end_call(value)
            return {"response_type": "in_channel", "text": "🔇 Call ended."}
        except Exception as e:
            return {"response_type": "ephemeral", "text": f"Error: {e}"}

    elif action_id == "view_transcript":
        # Fetch full transcript from JSON storage
        call_log = await json_storage.get_call_log_by_vapi_id(value)
        if call_log:
            transcript = call_log.get("transcript") or "No transcript available."
            return {
                "response_type": "ephemeral",
                "text": f"*Full Transcript*\n```{transcript[:3000]}```",
            }
        return {"response_type": "ephemeral", "text": "Transcript not found."}

    elif action_id == "callback":
        # value is customer phone number
        phone = str(value or "").strip()
        if not phone:
            return {"response_type": "ephemeral", "text": "⚠️ Invalid phone number."}

        # Use latest call for this phone to identify business context.
        all_logs = await json_storage.list_all_call_logs(limit=10000)
        matching_logs = [log for log in all_logs if log.get("customer_phone") == phone]
        if not matching_logs:
            return {
                "response_type": "ephemeral",
                "text": f"⚠️ Could not find call context for {phone}.",
            }
        # Take the most recent
        call_log = matching_logs[0]

        business = await json_storage.get_business(call_log["business_id"])
        if not business:
            return {"response_type": "ephemeral", "text": "⚠️ Business not found."}

        try:
            call = await trigger_outbound_callback(
                business=business,
                customer_name=call_log.get("customer_name") or "Customer",
                customer_phone=phone,
                chat_summary=(call_log.get("summary") or "Callback requested from Slack summary button."),
                chat_history=None,
            )
            return {
                "response_type": "in_channel",
                "text": f"📞 Callback initiated for {phone} (call id: {call.get('id', 'unknown')}).",
            }
        except Exception as e:
            return {
                "response_type": "ephemeral",
                "text": f"❌ Callback failed: {e}",
            }

    elif action_id == "mark_resolved":
        # value is call_log_id
        call_log = await json_storage.get_call_log(value)
        if call_log:
            call_log["outcome"] = "resolved"
            await json_storage.update_call_log(call_log["id"], call_log)
            return {"response_type": "in_channel", "text": "✅ Marked as resolved."}
        return {"response_type": "ephemeral", "text": "Call log not found."}

    elif action_id == "whisper":
        # Fallback whisper action for button clicks
        if not value:
            return {"response_type": "ephemeral", "text": "⚠️ Missing call id."}

        whisper_payload = {
            "role": "system",
            "content": "WHISPER FROM OWNER: Please reassure the caller and continue collecting details.",
        }
        try:
            await vapi_client.send_message(str(value), whisper_payload)
            return {
                "response_type": "ephemeral",
                "text": "✅ Whisper sent. For custom whisper text, reply in the call thread.",
            }
        except Exception as e:
            return {
                "response_type": "ephemeral",
                "text": f"❌ Whisper failed: {e}",
            }

    elif action_id == "approve_transfer":
        # Owner approved transfer — transfer call to owner
        call_log = await json_storage.get_call_log_by_vapi_id(value)
        if not call_log:
            return {"response_type": "ephemeral", "text": "⚠️ Call not found."}

        status = await vapi_client.get_call_status(value)
        if status != "in-progress":
            return {"response_type": "ephemeral", "text": "⚠️ Call has already ended."}

        business = await json_storage.get_business(call_log["business_id"])
        if not business:
            return {"response_type": "ephemeral", "text": "⚠️ Business not found."}

        destination = {
            "type": "sip",
            "sipUri": f"sip:{business.get('fallback_number')}@{settings.VOBIZ_SIP_DOMAIN}",
        }
        await vapi_client.transfer_call(value, destination)

        return {
            "response_type": "in_channel",
            "text": "✅ Transferring call to owner now...",
        }

    elif action_id == "decline_transfer":
        # Owner declined — send message to AI to inform caller
        try:
            await vapi_client.send_message(
                str(value),
                {
                    "role": "system",
                    "content": "The owner is currently unavailable. Say: 'I'm sorry, our team is busy right now. Can I help you with anything else, or would you like me to take a message?'",
                },
            )
            return {
                "response_type": "in_channel",
                "text": "❌ Owner declined. AI has been notified.",
            }
        except Exception as e:
            return {"response_type": "ephemeral", "text": f"❌ Failed to notify AI: {e}"}

    return {"status": "unknown_action"}
