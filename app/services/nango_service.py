"""Nango API client for OAuth proxy operations."""

from typing import Optional

import httpx

from app.core.config import settings


class NangoService:
    def __init__(self):
        self.base_url = settings.NANGO_BASE_URL
        self.secret_key = settings.NANGO_SECRET_KEY
        self.headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    async def create_session(self, end_user_id: str) -> dict:
        """Create a Nango connect session for Slack OAuth."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/connect/sessions",
                headers=self.headers,
                json={
                    "end_user": {"id": end_user_id},
                    "allowed_integrations": ["slack"],
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def proxy_request(
        self,
        connection_id: str,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
    ) -> dict:
        """Make a proxied request to Slack via Nango."""
        url = f"{self.base_url}/proxy/{endpoint}"
        headers = {
            **self.headers,
            "Connection-Id": connection_id,
            "Provider-Config-Key": settings.NANGO_INTEGRATION_ID,
        }
        if data and "channel" in data and isinstance(data["channel"], str):
           data["channel"] = data["channel"].lstrip("#")

        async with httpx.AsyncClient(timeout=30.0) as client:
            if method.upper() == "GET":
                resp = await client.get(url, headers=headers)
            elif method.upper() == "POST":
                resp = await client.post(url, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported method: {method}")

            resp.raise_for_status()
            return resp.json()

    async def get_connection(self, connection_id: str) -> dict:
        """Fetch Nango connection details for a connection ID (may include tokens/credentials)."""
        url = f"{self.base_url}/connections/{connection_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def list_channels(self, connection_id: str) -> list:
        """List Slack channels for a connected workspace."""
        try:
            result = await self.proxy_request(
                connection_id=connection_id,
                method="GET",
                endpoint="conversations.list?types=public_channel,private_channel&limit=200",
            )
        except httpx.HTTPStatusError as e:
            detail = e.response.text if e.response is not None else str(e)
            raise RuntimeError(f"Nango channels error: {detail}") from e
        channels = result.get("channels", [])
        return [c for c in channels if not c.get("is_archived", False)]


nango_client = NangoService()
