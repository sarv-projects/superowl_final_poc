"""High-level call flow orchestration."""

from typing import Optional

from app.core.config import settings
from app.core import json_storage
from app.services.prompt_builder import prompt_builder
from app.services.vapi_service import vapi_client
import json


def _base_url() -> str:
    return settings.VAPI_WEBHOOK_URL.replace("/vapi-webhook", "")


def _build_ananya_tools(fallback_number: str) -> list:
    """Inline tool definitions for Ananya (inbound + outbound assistants)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "notify_owner",
                "description": "Call this when the customer wants to escalate, speak to the owner, or is a qualified lead.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_name": {"type": "string", "description": "Customer's name"},
                        "call_summary": {"type": "string", "description": "What the customer wants"},
                        "lead_reason": {"type": "string", "description": "Why this is a qualified lead"},
                    },
                    "required": ["customer_name", "call_summary", "lead_reason"],
                },
            },
            "server": {"url": f"{_base_url()}/vapi-webhook/notify-owner"},
        },
        {"type": "endCall"},
        {
            "type": "transferCall",
            "destinations": [
                {
                    "type": "sip",
                    "sipUri": f"sip:{fallback_number}@{settings.VOBIZ_SIP_DOMAIN}",
                }
            ],
        },
    ]


def _build_owner_pa_tools() -> list:
    """Inline tool definitions for Owner PA assistant."""
    return [
        {
            "type": "function",
            "function": {
                "name": "report_decision",
                "description": "Report the owner's yes/no decision on whether to take the customer call.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Owner's decision: yes to transfer, no to decline",
                        }
                    },
                    "required": ["decision"],
                },
            },
            "server": {"url": f"{_base_url()}/vapi-webhook/owner-decision"},
        },
        {"type": "endCall"},
    ]


async def trigger_outbound_callback(
    business: dict,
    customer_name: str,
    customer_phone: str,
    chat_summary: str,
    chat_history: Optional[list] = None,
) -> dict:
    """Initiate an outbound callback flow."""
    templates = await json_storage.list_prompt_templates()
    business_prompt = ""
    if templates:
        t = templates[0]
        business_prompt = t.get("shared_system_prompt", "") if isinstance(t, dict) else getattr(t, "shared_system_prompt", "")

    business_dict = {
        "display_name": business.get("display_name"),
        "kb": business.get("kb", ""),
        "fallback_number": business.get("fallback_number"),
    }

    extra_vars = {
        "customerName": customer_name,
        "customer_name": customer_name,
        "chatSummary": chat_summary,
        "chat_summary": chat_summary,
    }

    system_prompt = prompt_builder.build_system_prompt(
        business_prompt, business_dict, is_outbound=True, extra_vars=extra_vars
    )

    if business.get("inject_chat_context") and chat_history:
        # Strip the last assistant message if it's a callback/availability fallback
        # so Ananya doesn't start the call already thinking the owner is unreachable
        filtered = []
        skip_phrases = [
            "having trouble reaching",
            "can someone call you back",
            "please hold a moment",
            "check availability",
        ]
        for msg in chat_history:
            content = msg.get("content", "").lower()
            if msg.get("role") == "assistant" and any(p in content for p in skip_phrases):
                continue
            filtered.append(msg)
        if filtered:
            formatted = "\n".join([f"{m['role']}: {m['content']}" for m in filtered])
            system_prompt += f"\n\nCHAT HISTORY:\n{formatted}"

    first_message = prompt_builder.render_welcome(
        business.get("outbound_welcome_template")
        or "Hi {customer_name}, this is Ananya from {business_name}! How can I help?",
        {
            "customer_name": customer_name,
            "business_name": business.get("display_name"),
            "chat_summary": chat_summary,
        },
    )

    assistant_config = {
        "firstMessage": first_message,
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [{"role": "system", "content": system_prompt}],
            "tools": _build_ananya_tools(business.get("fallback_number", "")),
        },
        "variableValues": {
            "display_name": business.get("display_name"),
            "kb": business.get("kb", ""),
            "fallback_number": business.get("fallback_number"),
            "businessName": business.get("display_name"),
            "fallbackNumber": business.get("fallback_number"),
            "customer_name": customer_name,
            "customerName": customer_name,
            "chat_summary": chat_summary,
            "chatSummary": chat_summary,
        },
    }

    print("=" * 60)
    print("SYSTEM PROMPT BEING SENT TO VAPI:")
    print(system_prompt)
    print("=" * 60)

    if settings.VAPI_OUTBOUND_ASSISTANT_ID:
        vapi_result = await vapi_client.create_call_from_assistant_id(
            assistant_id=settings.VAPI_OUTBOUND_ASSISTANT_ID,
            customer_number=customer_phone,
            customer_name=customer_name,
            assistant_overrides=assistant_config,
        )
    else:
        assistant_config.update({
            "voice": {
                "provider": "11labs",
                "voiceId": business.get("voice_id", "pMsXgVXv3BLzUgSXRplE"),
            },
            "maxDurationSeconds": business.get("max_call_duration_minutes", 10) * 60,
            "serverMessages": ["transcript", "hang", "end-of-call-report"],
            "endCallFunctionEnabled": True,
        })
        vapi_result = await vapi_client.create_call(
            assistant_config=assistant_config,
            customer_number=customer_phone,
            customer_name=customer_name,
        )

    vapi_call_id = vapi_result.get("id")
    if vapi_call_id:
        from app.services.slack_service import slack_service

        call_log = await json_storage.create_call_log({
            "business_id": business.get("id"),
            "call_type": "outbound",
            "vapi_call_id": vapi_call_id,
            "customer_phone": customer_phone,
            "customer_name": customer_name,
        })

        if business.get("nango_connection_id") and business.get("slack_channel"):
            try:
                slack_result = await slack_service.send_live_call_notification(
                    connection_id=str(business.get("nango_connection_id")),
                    channel=str(business.get("slack_channel")),
                    call_type="outbound",
                    call_log_id=str(call_log.get("id")),
                    vapi_call_id=vapi_call_id,
                    business_name=str(business.get("display_name")),
                    customer_phone=customer_phone,
                    customer_name=customer_name,
                )
                thread_ts = slack_result.get("ts") if isinstance(slack_result, dict) else None
                if thread_ts:
                    call_log["slack_live_thread_ts"] = thread_ts
                    await json_storage.update_call_log(call_log["id"], call_log)
            except Exception as e:
                print(f"Outbound Slack notification failed (non-fatal): {e}")

    return vapi_result


async def handle_owner_check_result(
    customer_call_id: str,
    decision: str,
    business_fallback_number: str,
):
    """Handle owner's decision after verification."""
    if decision == "yes":
        destination = {
            "type": "sip",
            "sipUri": f"sip:{business_fallback_number}@{settings.VOBIZ_SIP_DOMAIN}",
        }
        await vapi_client.transfer_call(customer_call_id, destination)
    else:
        await vapi_client.send_message(
            customer_call_id,
            {
                "role": "system",
                "content": "The owner is currently unavailable. Say: 'I'm sorry, our team is busy right now. Can I help you with anything else, or would you like me to take a message?'",
            },
        )
