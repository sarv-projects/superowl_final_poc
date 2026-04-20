from fastapi import APIRouter, HTTPException

from app.core import json_storage
from app.schemas.call import OutboundCallbackRequest
from app.services.call_orchestrator import trigger_outbound_callback
from app.services.groq_service import groq_service  # ← add this

router = APIRouter()


@router.post("/outbound")
async def trigger_outbound(request: OutboundCallbackRequest):
    business = await json_storage.get_business(str(request.business_id))
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    if not bool(business.get("enable_voice_callbacks", True)):
        raise HTTPException(
            status_code=400, detail="Voice callbacks disabled for this business"
        )

    # ── Summarize chat history before passing to agent ──────────────────
    effective_summary = request.chat_summary
    if request.chat_history:
        try:
            effective_summary = groq_service.summarize_chat_history(request.chat_history)
        except Exception as e:
            print(f"Chat summarization failed, using raw summary: {e}")
            # falls back to whatever the frontend sent

    try:
        result = await trigger_outbound_callback(
            business=business,
            customer_name=request.customer_name,
            customer_phone=request.customer_phone,
            chat_summary=effective_summary,  # ← summarized, not raw
            chat_history=request.chat_history,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Outbound trigger failed: {e}")

    return {"call_id": result.get("id"), "status": "initiated"}