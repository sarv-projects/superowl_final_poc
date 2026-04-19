"""High-level call flow orchestration."""

from typing import Optional

from app.core.config import settings
from app.core import json_storage
from app.services.prompt_builder import prompt_builder
from app.services.vapi_service import vapi_client


async def trigger_outbound_callback(
    business: dict,
    customer_name: str,
    customer_phone: str,
    chat_summary: str,
    chat_history: Optional[list] = None,
) -> dict:
    """Initiate an outbound callback flow (O-1 or O-2)."""
    # Get shared prompt template
    templates = await json_storage.list_prompt_templates()
    shared_prompt = "You are a helpful assistant."
    if templates and len(templates) > 0:
        template = templates[0]
        if isinstance(template, dict):
            shared_prompt = template.get("shared_system_prompt", shared_prompt)
        elif hasattr(template, "shared_system_prompt"):
            shared_prompt = template.shared_system_prompt

    # Build system prompt
    business_dict = {
        "display_name": business.get("display_name"),
        "city": business.get("city"),
        "hours": business.get("hours"),
        "services": business.get("services"),
        "fallback_number": business.get("fallback_number"),
    }

    # Provide runtime variables (customer name / chat summary) to server-side rendering
    extra_vars = {
        "customerName": customer_name,
        "customer_name": customer_name,
        "chatSummary": chat_summary,
        "chat_summary": chat_summary,
    }

    system_prompt = prompt_builder.build_system_prompt(
        shared_prompt, business_dict, is_outbound=True, extra_vars=extra_vars
    )

    # Append chat history if enabled
    if business.get("inject_chat_context") and chat_history:
        formatted = "\n".join([f"{m['role']}: {m['content']}" for m in chat_history])
        system_prompt += f"\n\nCHAT HISTORY:\n{formatted}"

    # Build welcome message
    welcome_vars = {
        "customer_name": customer_name,
        "business_name": business.get("display_name"),
        "chat_summary": chat_summary,
    }
    first_message = prompt_builder.render(
        business.get("outbound_welcome_template")
        or "Hi {customer_name}, this is Ananya from {business_name}! How can I help?",
        welcome_vars,
    )

    # Build assistant config
    # Provide variableValues in multiple common key formats so dashboard assistants
    # (which may expect camelCase) and server-side renderers (which expect
    # snake_case or specific keys) both receive the data. This prevents gaps
    # where the assistant doesn't know the customer's name or business fields
    # and asks the caller to repeat information.
    assistant_config = {
        "firstMessage": first_message,
        "variableValues": {
            # snake_case (used by some templates / server-side builders)
            "display_name": business.get("display_name"),
            "city": business.get("city"),
            "hours": business.get("hours"),
            "services": business.get("services"),
            "fallback_number": business.get("fallback_number"),

            # camelCase / human-friendly names (commonly used in VAPI dashboard)
            "businessName": business.get("display_name"),
            "cityName": business.get("city"),
            "fallbackNumber": business.get("fallback_number"),

            # customer identifiers (provide both variants)
            "customer_name": customer_name,
            "customerName": customer_name,

            # chat summary / context
            "chat_summary": chat_summary,
            "chatSummary": chat_summary,
        },
    }

    # Use VAPI dashboard assistant for model/voice; backend supplies prompt + variables.
    if settings.VAPI_OUTBOUND_ASSISTANT_ID:
        vapi_result = await vapi_client.create_call_from_assistant_id(
            assistant_id=settings.VAPI_OUTBOUND_ASSISTANT_ID,
            customer_number=customer_phone,
            customer_name=customer_name,
            assistant_overrides=assistant_config,
        )
    else:
        # Fallback only if dashboard assistant ID is not configured.
        assistant_config.update(
            {
                "model": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "system", "content": system_prompt}],
                },
                "voice": {
                    "provider": "11labs",
                    "voiceId": business.get("voice_id", "pMsXgVXv3BLzUgSXRplE"),
                },
                "maxDurationSeconds": business.get("max_call_duration_minutes", 10) * 60,
                "serverMessages": ["transcript", "hang", "end-of-call-report"],
                "endCallFunctionEnabled": True,
            }
        )
        vapi_result = await vapi_client.create_call(
            assistant_config=assistant_config,
            customer_number=customer_phone,
            customer_name=customer_name,
        )

    # Create call log for analytics, whisper, transcript, post-call summary
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

        # Fire Slack live-call notification for outbound (enables owner whisper/takeover)
        if business.get("nango_connection_id") and business.get("slack_live_channel"):
            try:
                slack_result = await slack_service.send_live_call_notification(
                    connection_id=str(business.get("nango_connection_id")),
                    channel=str(business.get("slack_live_channel")),
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
        # Transfer to owner
        destination = {
            "type": "sip",
            "sipUri": f"sip:{business_fallback_number}@{settings.VOBIZ_SIP_DOMAIN}",
        }
        await vapi_client.transfer_call(customer_call_id, destination)
    else:
        # Owner declined — send message to continue
        await vapi_client.send_message(
            customer_call_id,
            {
                "role": "system",
                "content": "The owner is currently unavailable. Say: 'I'm sorry, our team is busy right now. Can I help you with anything else, or would you like me to take a message?'",
            },
        )
