"""Prompt template model - Pydantic-based."""

from typing import Optional
from pydantic import BaseModel


class PromptTemplate(BaseModel):
    """Prompt template model for JSON storage."""
    id: Optional[str] = None
    shared_system_prompt: str
    updated_at: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "shared_system_prompt": "You are a helpful assistant...",
            }
        }
