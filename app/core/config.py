"""Application configuration loaded from environment variables."""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from the environment or `.env` file."""

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }
    # VAPI
    VAPI_API_KEY: str
    VAPI_OUTBOUND_PHONE: str  # The phone number VAPI uses for outbound calls
    VAPI_PHONE_NUMBER_ID: str
    VAPI_INBOUND_ASSISTANT_ID: Optional[str] = None
    VAPI_OUTBOUND_ASSISTANT_ID: Optional[str] = None
    VAPI_OWNER_ASSISTANT_ID: Optional[str] = None
    VAPI_WEBHOOK_URL: str = "https://your-ngrok.ngrok-free.app/vapi-webhook"

    # Nango
    NANGO_SECRET_KEY: str
    NANGO_BASE_URL: str = "https://api.nango.dev"
    NANGO_INTEGRATION_ID: str = "slack"
    NANGO_WEBHOOK_SECRET: Optional[str] = None

    # Groq
    GROQ_API_KEY: str

    # Optional ElevenLabs key for in-UI voice previews
    ELEVENLABS_API_KEY: Optional[str] = None

    # Vobiz SIP
    VOBIZ_SIP_DOMAIN: str = "40942180.sip.vobiz.ai"

    # Demo business seed
    BUSINESS_PHONE_NUMBER: str = "+919901540581"
    BUSINESS_FALLBACK_NUMBER: Optional[str] = None

    # Slack (optional direct webhook)
    SLACK_WEBHOOK_URL: Optional[str] = None

    # Feature flags
    FALLBACK_ON_NO_ANI_MATCH: bool = False


settings = Settings()
