"""Playground endpoints for testing calls and seeding demo data."""

from typing import Optional, Any, cast
import re

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.config import settings
from app.core import json_storage
from app.services.call_orchestrator import trigger_outbound_callback
from app.services.groq_service import groq_service
from app.services.prompt_builder import prompt_builder

router = APIRouter()

VOICE_PREVIEW_TEXT = "Hi, I am Ananya from SuperOwl. This is a quick voice preview for your business assistant."

DEFAULT_SHARED_PROMPT = """You are {{agentName}}, a warm, friendly, and professional voice assistant for {{businessName}} in {{city}}.

Speak naturally and calmly. Keep responses short, clear, and human. This is a live voice call, so avoid long explanations.

Your goals:
- Understand the caller's request from the conversation or chat context
- Answer product, service, pricing, and booking questions clearly
- If the caller needs the owner or the issue is urgent, offer a transfer
- Confirm the caller's name and callback number before ending the call

If transferring, say: "Let me connect you with our team directly."
Then transfer to {{fallbackNumber}}."""

DEMO_BUSINESS_NAME = "Sweet Root – Toys & Memories"


def _seed_fallback_number() -> str:
    return settings.BUSINESS_FALLBACK_NUMBER or settings.BUSINESS_PHONE_NUMBER


_TOOL_CALL_PATTERNS = [
    re.compile(r"\bnotify_owner\s*\([^)]*\)", re.IGNORECASE),
    re.compile(r"\bend_call_tool\s*\([^)]*\)", re.IGNORECASE),
    re.compile(r"\btransfer_call_tool\s*\([^)]*\)", re.IGNORECASE),
    re.compile(r"\bsearch_knowledge_base\s*\([^)]*\)", re.IGNORECASE),
]


def _sanitize_playground_reply(reply: str) -> str:
    cleaned = reply or ""
    for pattern in _TOOL_CALL_PATTERNS:
        cleaned = pattern.sub("", cleaned)

    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


@router.post("/seed")
async def seed_demo_data():
    """
    Seed a demo business and shared prompt for fresh installs.
    Idempotent — safe to call multiple times.
    Returns the business_id to construct the dashboard URL:
      http://localhost:8000/?business_id=<id>
    """
    # Fetch all businesses and look for demo business
    businesses = await json_storage.list_businesses()
    existing = None
    for biz in businesses:
        if biz.get("display_name") == DEMO_BUSINESS_NAME:
            existing = biz
            break
    
    if existing:
        # Update phone/fallback in case env changed
        existing["phone_number"] = settings.BUSINESS_PHONE_NUMBER
        existing["fallback_number"] = _seed_fallback_number()
        await json_storage.update_business(existing["id"], existing)
        return {
            "status": "already_seeded",
            "business_id": str(existing["id"]),
            "dashboard_url": f"http://localhost:8000/?business_id={existing['id']}",
        }

    biz_data = {
        "phone_number": settings.BUSINESS_PHONE_NUMBER,
        "display_name": DEMO_BUSINESS_NAME,
        "city": "Bengaluru",
        "hours": "10 AM – 7 PM, Mon–Sat",
        "services": "Wooden toys, birthday parties, creative play sessions, memory quilts",
        "fallback_number": _seed_fallback_number(),
        "voice_id": "pMsXgVXv3BLzUgSXRplE",
        "outbound_welcome_template": (
            "Hi {customer_name}, this is Ananya calling from {business_name}! "
            "I was just speaking with you on our chat. How can I assist you today?"
        ),
        "inbound_welcome_template": (
            "Thank you for calling {{businessName}}! I'm Ananya, your AI assistant. "
            "How can I help you today?"
        ),
        "callback_trigger_phrase": "Would you like us to call you back for a more detailed discussion?",
    }
    biz = await json_storage.create_business(biz_data)

    # Seed shared prompt only if none exists
    templates = await json_storage.list_prompt_templates()
    if not templates or len(templates) == 0:
        await json_storage.create_prompt_template({
            "name": "default",
            "shared_system_prompt": DEFAULT_SHARED_PROMPT,
        })

    return {
        "status": "seeded",
        "business_id": str(biz["id"]),
        "dashboard_url": f"http://localhost:8000/?business_id={biz['id']}",
    }


class OutboundTestRequest(BaseModel):
    business_id: str
    customer_name: str = "Playground User"
    customer_phone: str
    chat_summary: str = "Playground-triggered callback request"


@router.get("/voice-preview")
async def voice_preview(voice_id: str):
    """Return MP3 preview audio for a given ElevenLabs voice id."""
    if not settings.ELEVENLABS_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="Direct preview audio is not configured. VAPI will still apply this voice on real calls.",
        )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": VOICE_PREVIEW_TEXT,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8},
    }
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.is_error:
            raise HTTPException(
                status_code=400,
                detail=f"Voice preview failed ({resp.status_code}): {resp.text}",
            )

    return Response(content=resp.content, media_type="audio/mpeg")


@router.post("/test-outbound")
async def test_outbound(req: OutboundTestRequest):
    """Trigger a real outbound callback for testing."""
    business = await json_storage.get_business(req.business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    try:
        # Trigger outbound callback (chat_summary provided separately)
        call = await trigger_outbound_callback(
            business=business,
            customer_name=req.customer_name,
            customer_phone=req.customer_phone,
            chat_summary=req.chat_summary,
            chat_history=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Outbound test failed: {e}")
    return {
        "status": "ok",
        "message": "Outbound call initiated",
        "call_id": call.get("id"),
    }


@router.post("/test-inbound")
async def test_inbound():
    """Simulate an inbound call for testing."""
    return {
        "status": "ok",
        "message": "Inbound tests are driven by /vapi-webhook events; use VAPI test webhook payloads.",
    }


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    business_id: str
    message: str
    history: Optional[list] = None


@router.post("/chat")
async def playground_chat(req: ChatRequest):
    """Chat endpoint for playground — uses real Groq + business system prompt."""
    business = await json_storage.get_business(req.business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    templates = await json_storage.list_prompt_templates()
    shared_prompt = DEFAULT_SHARED_PROMPT
    if templates and len(templates) > 0:
        template = templates[0]
        if isinstance(template, dict):
            shared_prompt = template.get("shared_system_prompt", DEFAULT_SHARED_PROMPT)
        elif hasattr(template, "shared_system_prompt"):
            shared_prompt = template.shared_system_prompt

    business_dict = {
        "display_name": str(business.get("display_name") or ""),
        "city": str(business.get("city") or ""),
        "hours": str(business.get("hours") or ""),
        "services": str(business.get("services") or ""),
        "fallback_number": str(business.get("fallback_number") or ""),
    }
    # Pass an explicit extra_vars so build_system_prompt signature remains stable
    system_prompt = prompt_builder.build_system_prompt(shared_prompt, business_dict, is_outbound=True, extra_vars={})

    messages = [{"role": "system", "content": system_prompt}]
    for h in (req.history or []):
        if isinstance(h, dict):
            role = h.get("role")
            content = h.get("content")
        else:
            role = getattr(h, "role", None)
            content = getattr(h, "content", None)

        if role and content is not None:
            messages.append({"role": str(role), "content": str(content)})
    messages.append({"role": "user", "content": req.message})

    response = groq_service.client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=cast(Any, messages),
        temperature=0.3,
        max_tokens=200,
    )
    reply = response.choices[0].message.content or "I'm not sure how to help with that."
    reply = _sanitize_playground_reply(reply) or "I'm here to help. Could you share a little more about what you need?"

    # Detect callback triggers
    triggers = ["callback", "book", "call you", "speak with", "contact", "team", "schedule"]
    source_text = f"{req.message.lower()} {reply.lower()}"
    needs_callback = any(t in source_text for t in triggers)

    # Generate chat summary from history for callback context
    # Find this section in playground_chat function (lines 245-250):
    # Generate chat summary from history for callback context
    chat_summary = ""
    if needs_callback and (req.history or []):
        # Build messages list for summarization
        history_messages = []
        for h in (req.history or []):
            if isinstance(h, dict):
                role = h.get("role")
                content = h.get("content")
            else:
                role = getattr(h, "role", None)
                content = getattr(h, "content", None)
            if role and content:
                prefix = "Customer:" if role == "user" else "Assistant:"
                history_messages.append(f"{prefix} {content}")
        
        # Create summary prompt
        summary_prompt = f"""Summarize this customer conversation in ONE sentence (max 15 words).
Focus on what the customer wants. Be specific.

Conversation:
{chr(10).join(history_messages)}

Summary:"""
        
        try:
            summary_response = groq_service.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=cast(Any, [{"role": "user", "content": summary_prompt}]),
                temperature=0.3,
                max_tokens=50,
            )
            summary_content = summary_response.choices[0].message.content
            chat_summary = summary_content.strip() if summary_content else "Customer requested a callback about their inquiry."
        except Exception as e:
            print(f"Summary generation failed: {e}")
            chat_summary = "Customer requested a callback about their inquiry."

    return {"reply": reply, "needs_callback": needs_callback, "chat_summary": chat_summary}


@router.get("/analytics/{business_id}")
async def get_analytics(business_id: str):
    """Return call analytics summary for a business."""
    logs = await json_storage.list_call_logs_for_business(business_id, limit=1000)
    
    total = len(logs)
    resolved = sum(1 for l in logs if l.get("outcome") == "resolved")
    transferred = sum(1 for l in logs if l.get("outcome") == "transferred")
    inbound = sum(1 for l in logs if l.get("call_type") == "inbound")
    outbound = sum(1 for l in logs if l.get("call_type") == "outbound")
    durations = [l.get("duration_seconds") or 0 for l in logs]
    avg_duration = int(sum(durations) / len(durations)) if durations else 0
    credits = sum(l.get("credits_used") or 0 for l in logs)
    resolution_rate = round(resolved / total * 100) if total else 0

    # Recent calls are already sorted by created_at descending by list_call_logs_for_business
    recent = logs[:10]
    recent_calls = [
        {
            "call_type": l.get("call_type", ""),
            "customer_phone": l.get("customer_phone", ""),
            "customer_name": l.get("customer_name", ""),
            "duration_seconds": l.get("duration_seconds", 0),
            "outcome": l.get("outcome", ""),
            "credits_used": l.get("credits_used", 0),
            "created_at": str(l.get("created_at", "")),
        }
        for l in recent
    ]

    return {
        "total": total,
        "inbound": inbound,
        "outbound": outbound,
        "resolved": resolved,
        "transferred": transferred,
        "resolution_rate": resolution_rate,
        "avg_duration_seconds": avg_duration,
        "credits_used": credits,
        "recent_calls": recent_calls,
    }


class GeneratePromptRequest(BaseModel):
    current_prompt: str
    business_name: str = "the business"
    city: str = "Bengaluru"
    industry: str = "general"


@router.post("/generate-prompt")
async def generate_system_prompt(req: GeneratePromptRequest):
    """
    Use Groq to generate an optimized voice assistant system prompt.
    Takes raw business info and formats it into a high-performance Voice AI prompt.
    """
    improvement_prompt = f"""You are an expert at optimizing text for Voice AI agents (like ElevenLabs + GPT).
    
    TASK:
    Take the "Raw Business Info" below and rewrite it into a clean, structured **System Prompt**.
    
    CRITICAL RULES:
    1. **DO NOT REMOVE ANY DETAILS.** Keep all specific data (Prices, Locations, Phone Numbers, Hours).
    2. **DO NOT USE PLACEHOLDERS** (like {{variable}}) unless they are generic (like {{businessName}}).
    3. **VOICE OPTIMIZATION:** Rewrite long sentences into short, punchy ones. The AI should speak naturally.
    4. **STRUCTURE:** Organize the text into these sections:
       - [Role] (Who the AI is)
       - [Business Facts] (Hard data: Price, Location, Hours)
       - [Conversation Flow] (How to handle questions)
       - [Rules] (Keep it under 20 words per response)
    
    RAW BUSINESS INFO:
    {req.current_prompt}
    
    Business Name: {req.business_name}
    City: {req.city}
    
    Return ONLY the optimized System Prompt. Do not add any explanation or chat."""

    try:
        response = groq_service.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=cast(Any, [
                {
                    "role": "system",
                    "content": "You are an expert at structuring raw business notes into high-performance Voice AI System Prompts.",
                },
                {"role": "user", "content": improvement_prompt},
            ]),
            temperature=0.3,
            max_tokens=1000,
        )
        generated_prompt = response.choices[0].message.content or req.current_prompt
    except Exception as e:
        print(f"Prompt generation failed: {e}")
        generated_prompt = req.current_prompt

    return {"prompt": generated_prompt}


class GenerateWelcomeRequest(BaseModel):
    type: str  # "outbound" or "inbound"
    current_message: str
    business_name: str = "the business"


@router.post("/generate-welcome")
async def generate_welcome_message(req: GenerateWelcomeRequest):
    """
    Use Groq to generate an optimized welcome message for inbound or outbound calls.
    """
    if req.type == "outbound":
        instruction = """This is an OUTBOUND callback message. The AI is calling the customer back after they requested it in a chat.
The message should:
- Greet the customer by name
- Reference the previous chat conversation
- Be warm and helpful
- Keep it under 20 words
- Use {{customer_name}} and {{business_name}} placeholders

Current message:
{current}

Business: {biz}

Return ONLY the improved message with {{customer_name}} and {{business_name}} placeholders preserved.""".format(
            current=req.current_message, biz=req.business_name
        )
    else:
        instruction = """This is an INBOUND call greeting. The customer called the business and the AI answered.
The message should:
- Thank the customer for calling
- Introduce the AI assistant
- Ask how to help
- Keep it under 15 words
- Use {{businessName}} placeholder

Current message:
{current}

Business: {biz}

Return ONLY the improved message with {{businessName}} placeholder preserved.""".format(
            current=req.current_message, biz=req.business_name
        )

    try:
        response = groq_service.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=cast(Any, [
                {
                    "role": "system",
                    "content": "You are an expert at crafting natural, friendly voice AI welcome messages.",
                },
                {"role": "user", "content": instruction},
            ]),
            temperature=0.5,
            max_tokens=100,
        )
        generated_message = response.choices[0].message.content or req.current_message
    except Exception as e:
        print(f"Welcome message generation failed: {e}")
        generated_message = req.current_message

    return {"message": generated_message}
