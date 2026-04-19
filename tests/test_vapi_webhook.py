"""Tests for VAPI webhook handler."""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_assistant_request_ani_not_found():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/vapi-webhook",
            json={
                "message": {"type": "assistant-request"},
                "call": {"phoneNumber": {"number": "+1234567890", "diversion": None}},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "assistant" in data
        assert "not configured" in data["assistant"]["firstMessage"]
