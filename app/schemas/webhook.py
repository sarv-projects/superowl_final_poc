"""Pydantic schemas for webhook payloads."""

from pydantic import BaseModel


class PromptUpdate(BaseModel):
    prompt: str
