"""Shared dependencies for FastAPI."""

from app.services.groq_service import groq_service
from app.services.nango_service import nango_client
from app.services.prompt_builder import prompt_builder
from app.services.slack_service import slack_service
from app.services.vapi_service import vapi_client

__all__ = [
    "vapi_client",
    "nango_client",
    "slack_service",
    "groq_service",
    "prompt_builder",
]
