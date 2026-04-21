"""VAPI webhook handler for inbound calls and call events."""

import asyncio
import json
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Request

from app.core import json_storage
from app.core.config import settings
from app.services.call_orchestrator import _build_ananya_tools, _build_owner_pa_tools
from app.services.groq_service import groq_service
from app.services.nango_service import nango_client
from app.services.prompt_builder import prompt_builder
from app.services.slack_service import slack_service
from app.services.vapi_service import vapi_client

router = APIRouter()

# ── Dual-agent call tracking ──────────────────────────────────────────────
# Maps owner_call_id → customer_call_id (so /owner-decision can find the customer call)
owner_to_customer: dict[str, str] = {}
# Maps customer_call_id → {control_url, business, ...}
call_sessions: dict[str, dict] = {}


async def _get_shared_prompt() -> str:
    """Get shared system prompt template."""
    try:
        templates = await json_storage.list_prompt_templates()
        if templates:
            template = templates[0]
            return template.get("shared_system_prompt", "You are a helpful assistant.")
    except (TypeError, ValueError, KeyError) as exc:
        print(f"Failed to load shared prompt template: {exc}")
    return "You are a helpful assistant."


def extract_ani_from_diversion(diversion: str) -> Optional[str]:
    """Extract phone number from SIP Diversion header."""
    if not diversion:
        return None
    match = re.search(r"sip:(\+?\d+)", diversion)
    return match.group(1) if match else None


@router.post("")
async def vapi_webhook(request: Request):
    """Handle all VAPI call events."""
    payload = await request.json()
    print("VAPI EVENT:", json.dumps(payload, indent=2))
    message = payload.get("message", {})
    event_type = message.get("type")

    if event_type == "assistant-request":
        return await handle_assistant_request(payload)
    if event_type == "transcript":
        return await handle_transcript(payload)
    if event_type == "end-of-call-report":
        return await handle_end_of_call_report(payload)
    if event_type == "hang":
        return {"status": "ok"}

    return {"status": "ignored"}


async def handle_assistant_request(payload: dict) -> dict:
    """Handle VAPI assistant-request for inbound calls."""
    call_data = payload.get("message", {}).get("call", {})
    phone_data = call_data.get("phoneNumber", {})
    from_number = phone_data.get("number")
    diversion = phone_data.get("diversion")

    if from_number == settings.VAPI_OUTBOUND_PHONE:
        return {
            "assistantId": settings.VAPI_INBOUND_ASSISTANT_ID or settings.VAPI_OUTBOUND_ASSISTANT_ID,
            "assistantOverrides": {
                "firstMessage": "This line is currently busy. Please try again later.",
            },
        }

    ani = extract_ani_from_diversion(diversion) or from_number
    business = await json_storage.get_business_by_phone(ani)

    if not business:
        return {
            "assistantId": settings.VAPI_INBOUND_ASSISTANT_ID,
            "assistantOverrides": {
                "firstMessage": "This number is not configured for voice service. Please contact the business directly.",
            },
        }

    if not bool(business.get("enable_inbound_call_handling", False)):
        return {
            "assistantId": settings.VAPI_INBOUND_ASSISTANT_ID,
            "assistantOverrides": {
                "firstMessage": "Inbound calls are not enabled for this business.",
            }
        }

    shared_prompt = await _get_shared_prompt()
    business_dict = {
        "display_name": business.get("display_name", ""),
        "kb": business.get("kb", ""),
        "fallback_number": business.get("fallback_number", ""),
    }
    system_prompt = prompt_builder.build_system_prompt(
        shared_prompt, business_dict, is_outbound=False #Triggers inbound logic.
    )

    first_message = prompt_builder.render_welcome(
        business.get("inbound_welcome_template")
        or "Thank you for calling {{businessName}}! I'm Ananya, how can I help?",
        {"businessName": business.get("display_name", "")},
    )

    vapi_call_id = call_data.get("id")
    call_log = await json_storage.create_call_log(
        {
            "business_id": business.get("id"),
            "call_type": "inbound",
            "vapi_call_id": vapi_call_id,
            "customer_phone": from_number,
        }
    )

    if business.get("nango_connection_id") and business.get("slack_channel"):
        try:
            slack_result = await slack_service.send_live_call_notification(
                connection_id=str(business.get("nango_connection_id")),
                channel=str(business.get("slack_channel")),
                call_type="inbound",
                call_log_id=str(call_log.get("id")),
                vapi_call_id=vapi_call_id,
                business_name=business.get("display_name", ""),
                customer_phone=from_number,
            )
            thread_ts = slack_result.get("ts") if isinstance(slack_result, dict) else None
            if thread_ts:
                call_log["slack_live_thread_ts"] = thread_ts
                await json_storage.update_call_log(call_log["id"], call_log)
        except Exception as e:
            print(f"Slack live notification failed (non-fatal): {e}")

    assistant_overrides = {
        "firstMessage": first_message,
        "variableValues": business_dict,
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": system_prompt}],
            "tools": _build_ananya_tools(business.get("fallback_number", "")),
        },
    }

    # Track call session for dual-agent flow
    call_sessions[vapi_call_id] = {
        "business_id": business.get("id"),
        "business": business,
        "customer_phone": from_number,
        "owner_call_triggered": False,
        "owner_call_id": None,
        "control_url": None,
    }

    # Always return full inline assistant — never use assistantId for inbound
    # Using assistantId causes VAPI to merge/override our config with dashboard defaults
    return {
        "assistant": {
            "model": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "messages": [{"role": "system", "content": system_prompt}],
                "tools": _build_ananya_tools(business.get("fallback_number", "")),
            },
            "voice": {
                "provider": "11labs",
                "voiceId": business.get("voice_id", "pMsXgVXv3BLzUgSXRplE"),
            },
            "firstMessage": first_message,
            "variableValues": business_dict,
            "maxDurationSeconds": business.get("max_call_duration_minutes", 10) * 60,
            "serverMessages": ["transcript", "hang", "end-of-call-report"],
            "endCallFunctionEnabled": True,
            "backgroundDenoisingEnabled": True,
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-3",
                "language": "en-IN",
            },
        }
    }

async def handle_transcript(payload: dict) -> dict:
    """Handle transcript events for live streaming to Slack."""
    call_id = payload.get("message", {}).get("call", {}).get("id")
    message = payload.get("message", {})
    text = (
        message.get("transcript")
        or message.get("text")
        or message.get("content")
        or payload.get("transcript")
        or ""
    )
    role = message.get("role") or message.get("speaker") or "assistant"

    if not text:
        return {"status": "no_text"}

    call_log = await json_storage.get_call_log_by_vapi_id(call_id)
    if not call_log:
        return {"status": "call_log_not_found"}

    current = call_log.get("transcript", "") or ""
    call_log["transcript"] = f"{current}\n{role.capitalize()}: {text}".strip()
    await json_storage.update_call_log(call_log["id"], call_log)

    # Stream transcript to Slack thread in real-time
    if call_log.get("slack_live_thread_ts") and call_log.get("business_id"):
        try:
            business = await json_storage.get_business(call_log["business_id"])
            if business and business.get("nango_connection_id") and business.get("slack_channel"):
                transcript_line = f"{role.capitalize()}: {text}"
                await nango_client.proxy_request(
                    connection_id=str(business.get("nango_connection_id")),
                    method="POST",
                    endpoint="chat.postMessage",
                    data={
                        "channel": business.get("slack_channel"),
                        "thread_ts": call_log.get("slack_live_thread_ts"),
                        "text": transcript_line,
                    },
                )
        except Exception as e:
            print(f"Slack transcript streaming failed (non-fatal): {e}")

    return {"status": "processed"}


async def handle_end_of_call_report(payload: dict) -> dict:
    """Handle end-of-call-report: generate summary and post to Slack."""
    message = payload.get("message", {})
    call_data = message.get("call", {})
    vapi_call_id = call_data.get("id")
    duration = message.get("durationSeconds") or call_data.get("durationSeconds", 0)
    transcript = message.get("transcript") or message.get("artifact", {}).get("transcript", "")
    ended_reason = message.get("endedReason") or call_data.get("endedReason", "")

    call_log = await json_storage.get_call_log_by_vapi_id(vapi_call_id)
    if not call_log:
        return {"status": "call_log_not_found"}

    if "transferred" in ended_reason:
        outcome = "transferred"
    elif "customer-ended-call" in ended_reason:
        outcome = "resolved"
    else:
        outcome = "abandoned"

    # Use VAPI transcript if available, otherwise fall back to accumulated transcript
    final_transcript = transcript or call_log.get("transcript", "")
    
    # Clean up transcript: remove timestamp-only lines and normalize
    if final_transcript:
        lines = final_transcript.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            # Skip empty lines and timestamp-only lines (e.g., "13:22", "1:22:15 PM(+00:01.66)")
            if stripped and not (len(stripped) < 6 and stripped.replace(":", "").replace(".", "").isdigit()):
                # Also skip lines that are just "Customer ended the call" metadata
                if "ended the call" not in stripped.lower():
                    cleaned_lines.append(stripped)
        final_transcript = "\n".join(cleaned_lines).strip()
    
    summary = groq_service.summarize_transcript(
        final_transcript, call_log.get("call_type", "inbound")
    )
    credits_used = max(1, duration // 6)

    call_log["duration_seconds"] = duration
    call_log["outcome"] = outcome
    call_log["transcript"] = final_transcript
    call_log["summary"] = summary
    call_log["credits_used"] = credits_used
    await json_storage.update_call_log(call_log["id"], call_log)

    business = await json_storage.get_business(call_log["business_id"])
    if business and business.get("nango_connection_id") and business.get("slack_channel"):
        transcript_lines = final_transcript.split("\n")[:3]
        preview = "\n".join(transcript_lines)
        asyncio.create_task(
            slack_service.send_post_call_summary(
                connection_id=str(business.get("nango_connection_id")),
                channel=str(business.get("slack_channel")),
                call_type=call_log.get("call_type", "inbound"),
                customer_phone=call_log.get("customer_phone", ""),
                customer_name=call_log.get("customer_name"),
                duration_seconds=duration,
                outcome=outcome,
                summary=summary,
                transcript_preview=preview,
                credits_used=credits_used,
                vapi_call_id=vapi_call_id,
                call_log_id=str(call_log["id"]),
            )
        )

    return {"status": "summary_sent"}


# ── Helper: send background message to active VAPI call ─────────────────
async def _send_background_message(customer_call_id: str, message: str):
    """Inject a system message into an active customer call."""
    try:
        # Get call details to find controlUrl
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://api.vapi.ai/call/{customer_call_id}",
                headers={"Authorization": f"Bearer {settings.VAPI_API_KEY}"},
            )
            resp.raise_for_status()
            call_data = resp.json()

        control_url = call_data.get("monitor", {}).get("controlUrl")
        if not control_url:
            print(f"No controlUrl for call {customer_call_id}")
            return

        payload = {
            "type": "add-message",
            "message": {"role": "system", "content": message},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                control_url,
                headers={"Authorization": f"Bearer {settings.VAPI_API_KEY}"},
                json=payload,
            )
            print(f"Background message response: {resp.status_code}")
    except Exception as e:
        print(f"Failed to send background message: {e}")


# ── Helper: transfer customer call ───────────────────────────────────────
async def _transfer_customer_call(customer_call_id: str, sip_uri: str):
    """Transfer customer call to owner via SIP."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://api.vapi.ai/call/{customer_call_id}",
                headers={"Authorization": f"Bearer {settings.VAPI_API_KEY}"},
            )
            resp.raise_for_status()
            call_data = resp.json()

        control_url = call_data.get("monitor", {}).get("controlUrl")
        if not control_url:
            print(f"No controlUrl for call {customer_call_id}")
            return

        payload = {
            "type": "transfer",
            "destination": {"type": "sip", "sipUri": sip_uri},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                control_url,
                headers={"Authorization": f"Bearer {settings.VAPI_API_KEY}"},
                json=payload,
            )
            print(f"Transfer response: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Failed to transfer call: {e}")


# ── Helper: command customer call based on owner decision ───────────────
async def _command_customer_call(customer_call_id: str, decision: str, business: dict):
    """Tell Ananya what to do based on owner's yes/no decision."""
    sip_uri = f"sip:{business.get('fallback_number', '')}@{settings.VOBIZ_SIP_DOMAIN}"

    if decision == "yes":
        # Step 1: Tell Ananya to say the handoff line
        await _send_background_message(
            customer_call_id,
            "The owner is available. Say exactly: 'Great news! The owner is ready to speak with you. Connecting you now, please hold.' Then stop speaking.",
        )

        # Step 2: Small delay to let Ananya finish speaking
        await asyncio.sleep(4)

        # Step 3: Execute the transfer
        await _transfer_customer_call(customer_call_id, sip_uri)

    elif decision == "no":
        business_name = business.get("display_name", "the business")
        await _send_background_message(
            customer_call_id,
            f"The owner is currently unavailable. Say: 'I'm sorry, our team at {business_name} is a little occupied at the moment. They will call you back shortly. Thank you so much!' Then call end_call_tool.",
        )


@router.post("/notify-owner")
async def notify_owner(request: Request):
    """
    Called by Ananya's notify_owner tool when she detects escalation.
    
    DUAL-AGENT FLOW:
    1. Fires Owner PA VAPI call to owner's phone (PRIMARY)
    2. Also sends Slack notification with approve/decline buttons (SECONDARY)
    
    Owner PA assistant talks to owner → owner says yes/no → Owner PA calls
    report_decision → hits /owner-decision → commands Ananya to transfer/decline.
    """
    payload = await request.json()

    # Extract tool call data from VAPI payload
    tool_call_list = payload.get("message", {}).get("toolCallList", [])
    tool_call_id = tool_call_list[0].get("id") if tool_call_list else None
    arguments = (
        tool_call_list[0].get("function", {}).get("arguments", {})
        if tool_call_list
        else {}
    )

    customer_name = arguments.get("customer_name", "the customer")
    call_summary = arguments.get("call_summary", "")
    lead_reason = arguments.get("lead_reason", "")
    customer_call_id = payload.get("message", {}).get("call", {}).get("id")

    if not customer_call_id:
        return {
            "results": [
                {
                    "toolCallId": tool_call_id,
                    "result": "Error: Could not identify the call.",
                }
            ]
        }

    # Get call session and business context
    call_log = await json_storage.get_call_log_by_vapi_id(customer_call_id)
    if not call_log:
        return {
            "results": [
                {
                    "toolCallId": tool_call_id,
                    "result": "Owner has been notified. Please hold while we check availability.",
                }
            ]
        }

    business = await json_storage.get_business(call_log.get("business_id", ""))
    if not business:
        return {
            "results": [
                {
                    "toolCallId": tool_call_id,
                    "result": "Owner has been notified. Please hold while we check availability.",
                }
            ]
        }

    owner_phone = business.get("fallback_number", "")
    owner_name = business.get("display_name", "the owner")
    business_name = business.get("display_name", "")
    customer_phone = call_log.get("customer_phone", "")
    reason = (
        f"{customer_name} wants to {call_summary}"
        if call_summary
        else lead_reason or "Customer requested to speak with the owner."
    )

    # ── PRIMARY: Fire Owner PA VAPI call to owner's phone ──────────────
    pa_system_prompt = f"""[Identity]
You are a brief, efficient AI assistant for {business_name}.
Your only job: inform the owner of a lead and get a yes/no decision.

[Customer]
Name: {customer_name}
Request: {call_summary}
Reason: {lead_reason}

[Script - follow exactly]
1. Say: "Hello {owner_name}, I'm calling from {business_name}. I have {customer_name} on the line who wants to {call_summary}. Are you available to take this call?"
2. Wait for response.
3. If YES or any positive response:
   - Say: "Perfect, connecting now."
   - Call report_decision with decision="yes"
   - Immediately call endCall. Do not say anything else.
4. If NO or unavailable:
   - Say: "Understood, thank you."
   - Call report_decision with decision="no"
   - Immediately call endCall. Do not say anything else.
5. If unclear after one follow-up:
   - Call report_decision with decision="no"
   - Immediately call endCall.

[Rules]
- Call report_decision ONCE only.
- Call endCall immediately after report_decision. No more talking.
- Do not repeat yourself.
- Do not say "hold on" or "one moment" after calling report_decision."""

    pa_first_message = (
        f"Hello {owner_name}, am I speaking to the owner of {business_name}?"
    )

    owner_assistant_id = settings.VAPI_OWNER_ASSISTANT_ID
    if not owner_assistant_id:
        print("WARNING: VAPI_OWNER_ASSISTANT_ID not set — skipping Owner PA call")
    else:
        resp = None
        try:
            # Fire Owner PA call via VAPI API
            # VAPI requires systemPrompt to be inside model.messages, not as a top-level override
            owner_payload = {
                "assistantId": owner_assistant_id,
                "phoneNumberId": settings.VAPI_PHONE_NUMBER_ID,
                "customer": {
                    "number": owner_phone,
                    "name": f"{owner_name} (Owner)",
                },
                "assistantOverrides": {
                    "firstMessage": pa_first_message,
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "system", "content": pa_system_prompt}],
                        "tools": _build_owner_pa_tools(),
                    },
                },
            }
            print(f"📞 DEBUG: Attempting Owner Call with ID: {owner_assistant_id}")
            print(f"📞 DEBUG: Payload: {owner_payload}")

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.vapi.ai/call",
                    headers={
                        "Authorization": f"Bearer {settings.VAPI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=owner_payload,
                )
                resp.raise_for_status()
                owner_call_data = resp.json()
                owner_call_id = owner_call_data.get("id")

                if owner_call_id:
                    owner_to_customer[owner_call_id] = customer_call_id
                    if customer_call_id in call_sessions:
                        call_sessions[customer_call_id]["owner_call_triggered"] = True
                        call_sessions[customer_call_id]["owner_call_id"] = owner_call_id
                        # Store control_url for later transfer
                        call_sessions[customer_call_id]["control_url"] = owner_call_data.get("monitor", {}).get("controlUrl")

                    print(f"Owner PA call triggered: {owner_call_id} → customer: {customer_call_id}")
        except Exception as e:
            print(f"Owner PA call failed: {e}")
            print(f"📞 DEBUG: Response Text: {getattr(resp, 'text', '<no response>')}")

    # ── SECONDARY: Send Slack notification with approve/decline buttons ─
    if business.get("nango_connection_id") and business.get("slack_channel"):
        try:
            await slack_service.send_owner_approval_request(
                connection_id=str(business.get("nango_connection_id")),
                channel=str(business.get("slack_channel")),
                customer_name=customer_name,
                customer_phone=customer_phone,
                reason=reason,
                call_id=customer_call_id,
                business_name=business_name,
            )
        except Exception as e:
            print(f"Owner approval Slack notification failed: {e}")

    return {
        "results": [
            {
                "toolCallId": tool_call_id,
                "result": "WAITING_FOR_OWNER. Do not say anything to the customer. Do not say the owner is ready. Stay silent until you receive a system message with the owner's decision.",
            }
        ]
    }


@router.post("/owner-decision")
async def owner_decision(request: Request):
    """
    Called by Owner PA's report_decision tool.
    Receives owner's yes/no decision.
    Commands Ananya to transfer or decline via background message injection.
    """
    payload = await request.json()

    tool_call_list = payload.get("message", {}).get("toolCallList", [])
    tool_call_id = tool_call_list[0].get("id") if tool_call_list else None
    arguments = (
        tool_call_list[0].get("function", {}).get("arguments", {})
        if tool_call_list
        else {}
    )

    decision = arguments.get("decision", "").lower()
    owner_call_id = payload.get("message", {}).get("call", {}).get("id")

    print(f"Owner decision received: {decision} for owner_call: {owner_call_id}")

    customer_call_id = owner_to_customer.get(owner_call_id)
    if customer_call_id:
        # Get business context
        call_log = await json_storage.get_call_log_by_vapi_id(customer_call_id)
        if call_log:
            business = await json_storage.get_business(call_log.get("business_id", ""))
            if business:
                await _command_customer_call(customer_call_id, decision, business)
    else:
        print(f"No customer call found for owner call: {owner_call_id}")

    messages = {
        "yes": "Done.",
        "no": "Done.",
    }

    return {
        "results": [
            {
                "toolCallId": tool_call_id,
                "result": messages.get(decision, "Decision recorded."),
            }
        ]
    }
