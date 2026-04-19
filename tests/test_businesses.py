"""Basic tests for business CRUD."""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_create_business():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/businesses/",
            json={
                "phone_number": "+919900123456",
                "display_name": "Test Business",
                "fallback_number": "+919900123456",
            },
        )
        assert response.status_code == 201
