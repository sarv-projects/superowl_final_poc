"""Business (tenant) model - Pydantic-based."""

from typing import Optional
from pydantic import BaseModel


class Business(BaseModel):
    """Business tenant model for JSON storage."""
    id: Optional[str] = None
    phone_number: str
    display_name: str
    kb: Optional[str] = None
    fallback_number: str

    # Slack integration
    nango_connection_id: Optional[str] = None
    slack_workspace: Optional[str] = None
    slack_channel: Optional[str] = None

    # Voice config (shared)
    voice_id: str = "pMsXgVXv3BLzUgSXRplE"

    # Outbound settings
    outbound_welcome_template: Optional[str] = None
    callback_trigger_phrase: str = "Would you like us to call you back?"
    max_call_duration_minutes: int = 10
    enable_voice_callbacks: bool = True
    inject_chat_context: bool = True
    post_call_summary_to_chat: bool = False

    # Inbound settings
    inbound_welcome_template: Optional[str] = None
    enable_inbound_call_handling: bool = True

    # Shared behavior
    human_transfer_on_escalation: bool = True
    check_with_owner_before_transfer: bool = True
    owner_check_method: str = "slack"  # slack | call | both
    owner_check_timeout_seconds: int = 30
    intent_based_transfer_detection: bool = True
    owner_initiated_handover: bool = True
    live_transcript_to_slack: bool = True
    whisper_coaching_via_slack: bool = True
    call_recording_enabled: bool = True

    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "phone_number": "+19876543210",
                "display_name": "Acme Corp",
                "fallback_number": "+19876543211",
            }
        }
