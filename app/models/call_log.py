"""Call log model for analytics and debugging - Pydantic-based."""

from typing import Optional
from pydantic import BaseModel


class CallLog(BaseModel):
    """Call log model for JSON storage."""
    id: Optional[str] = None
    business_id: str
    call_type: str  # inbound | outbound
    vapi_call_id: str
    customer_phone: Optional[str] = None
    customer_name: Optional[str] = None
    duration_seconds: Optional[int] = None
    outcome: Optional[str] = None  # resolved | transferred | abandoned | timeout | owner_declined
    transcript: Optional[str] = None
    summary: Optional[str] = None
    credits_used: Optional[int] = None
    slack_live_thread_ts: Optional[str] = None
    slack_summary_thread_ts: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "business_id": "some-uuid",
                "call_type": "outbound",
                "vapi_call_id": "vapi-call-id",
                "customer_phone": "+19876543210",
            }
        }
