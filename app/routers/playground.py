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
    """Seed a demo business and shared prompt. Idempotent."""
    businesses = await json_storage.list_businesses()
    existing = next((biz for biz in businesses if biz.get("display_name") == DEMO_BUSINESS_NAME), None)

    if existing:
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
        "outbound_welcome_template": "Hi {customer_name}, this is Ananya calling from {business_name}! I was just speaking with you on our chat. How can I assist you today?",
        "inbound_welcome_template": "Thank you for calling {{businessName}}! I'm Ananya, your AI assistant. How can I help you today?",
        "callback_trigger_phrase": "Would you like us to call you back for a more detailed discussion?",
    }
    biz = await json_storage.create_business(biz_data)

    templates = await json_storage.list_prompt_templates()
    if not templates:
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
        raise HTTPException(status_code=400, detail="ElevenLabs API key not configured.")
    
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
            raise HTTPException(status_code=400, detail=f"Voice preview failed: {resp.text}")
    
    return Response(content=resp.content, media_type="audio/mpeg")


@router.post("/test-outbound")
async def test_outbound(req: OutboundTestRequest):
    """Trigger a real outbound callback for testing."""
    business = await json_storage.get_business(req.business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    try:
        call = await trigger_outbound_callback(
            business=business,
            customer_name=req.customer_name,
            customer_phone=req.customer_phone,
            chat_summary=req.chat_summary,
            chat_history=None,
        )
        return {
            "status": "ok",
            "message": "Outbound call initiated",
            "call_id": call.get("id"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Outbound test failed: {e}")


class ChatMessage(BaseModel):
    role: str
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
    if templates:
        template = templates[0]
        shared_prompt = template.get("shared_system_prompt", DEFAULT_SHARED_PROMPT) if isinstance(template, dict) else getattr(template, "shared_system_prompt", DEFAULT_SHARED_PROMPT)

    business_dict = {
        "display_name": str(business.get("display_name") or ""),
        "city": str(business.get("city") or ""),
        "hours": str(business.get("hours") or ""),
        "services": str(business.get("services") or ""),
        "fallback_number": str(business.get("fallback_number") or ""),
    }

    system_prompt = prompt_builder.build_system_prompt(
        shared_prompt, business_dict, is_outbound=True, extra_vars={}
    )

    messages = [{"role": "system", "content": system_prompt}]
    for h in (req.history or []):
        if isinstance(h, dict) and h.get("role") and h.get("content"):
            messages.append({"role": str(h["role"]), "content": str(h["content"])})
    messages.append({"role": "user", "content": req.message})

    response = groq_service.client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=cast(Any, messages),
        temperature=0.3,
        max_tokens=200,
    )
    reply = response.choices[0].message.content or "I'm here to help. Could you share more details?"
    reply = _sanitize_playground_reply(reply)

    # Detect callback trigger
    source_text = f"{req.message.lower()} {reply.lower()}"
    needs_callback = any(word in source_text for word in ["callback", "book", "call you", "speak with", "contact", "schedule", "owner"])

    # Use the improved Groq service for chat summary
    chat_summary = "Customer requested a callback about their inquiry."
    if needs_callback and req.history:
        chat_summary = groq_service.summarize_chat_history(req.history)

    return {
        "reply": reply,
        "needs_callback": needs_callback,
        "chat_summary": chat_summary
    }


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
    """Use Groq to generate an optimized voice assistant system prompt."""
    improvement_prompt = f"""You are an expert at optimizing text for Voice AI agents.

TASK: Rewrite the "Raw Business Info" into a clean, structured System Prompt.

CRITICAL RULES:
- Keep ALL details (prices, locations, hours, etc.)
- Use short, natural sentences for voice
- Structure clearly with sections

RAW BUSINESS INFO:
{req.current_prompt}

Business Name: {req.business_name}
City: {req.city}

Return ONLY the optimized System Prompt."""

    try:
        response = groq_service.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=cast(Any, [
                {"role": "system", "content": "You are an expert at structuring raw business notes into high-performance Voice AI System Prompts."},
                {"role": "user", "content": improvement_prompt},
            ]),
            temperature=0.3,
            max_tokens=1000,
        )
        generated_prompt = response.choices[0].message.content or req.current_prompt
    except Exception:
        generated_prompt = req.current_prompt

    return {"prompt": generated_prompt}


class GenerateWelcomeRequest(BaseModel):
    type: str
    current_message: str
    business_name: str = "the business"


@router.post("/generate-welcome")
async def generate_welcome_message(req: GenerateWelcomeRequest):
    """Use Groq to generate an optimized welcome message."""
    if req.type == "outbound":
        instruction = f"""This is an OUTBOUND callback message. Make it warm, reference the previous chat, and be under 20 words.
Current message: {req.current_message}
Business: {req.business_name}
Return ONLY the improved message."""
    else:
        instruction = f"""This is an INBOUND greeting. Thank the customer and ask how to help. Keep it under 15 words.
Current message: {req.current_message}
Business: {req.business_name}
Return ONLY the improved message."""

    try:
        response = groq_service.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=cast(Any, [
                {"role": "system", "content": "You are an expert at crafting natural, friendly voice AI welcome messages."},
                {"role": "user", "content": instruction},
            ]),
            temperature=0.5,
            max_tokens=100,
        )
        generated_message = response.choices[0].message.content or req.current_message
    except Exception:
        generated_message = req.current_message

    return {"message": generated_message}