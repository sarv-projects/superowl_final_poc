"""Pydantic schemas for call-related requests/responses."""

import uuid
from typing import Optional

from pydantic import BaseModel


class OutboundCallbackRequest(BaseModel):
    business_id: uuid.UUID
    customer_name: str
    customer_phone: str
    chat_summary: str
    chat_history: Optional[list] = None
