"""VAPI API client for creating calls, transfers, and sending messages."""

from typing import Optional

import httpx

from app.core.config import settings


class VAPIService:
    def __init__(self):
        self.base_url = "https://api.vapi.ai"
        self.headers = {
            "Authorization": f"Bearer {settings.VAPI_API_KEY}",
            "Content-Type": "application/json",
        }

    async def create_call(
        self,
        assistant_config: dict,
        customer_number: str,
        customer_name: Optional[str] = None,
        phone_number_id: Optional[str] = None,
    ) -> dict:
        """Create a new outbound call."""
        payload = {
            "assistant": assistant_config,
            "phoneNumberId": phone_number_id or settings.VAPI_PHONE_NUMBER_ID,
            "customer": {
                "number": customer_number,
                "name": customer_name or customer_number,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/call",
                headers=self.headers,
                json=payload,
            )
            if resp.is_error:
                raise RuntimeError(
                    f"VAPI create_call failed ({resp.status_code}): {resp.text}"
                )
            return resp.json()

    async def create_call_from_assistant_id(
        self,
        assistant_id: str,
        customer_number: str,
        customer_name: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        assistant_overrides: Optional[dict] = None,
    ) -> dict:
        """Create a call using an existing VAPI assistant id."""
        payload = {
            "assistantId": assistant_id,
            "phoneNumberId": phone_number_id or settings.VAPI_PHONE_NUMBER_ID,
            "customer": {
                "number": customer_number,
                "name": customer_name or customer_number,
            },
        }
        if assistant_overrides:
            payload["assistantOverrides"] = assistant_overrides

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/call",
                headers=self.headers,
                json=payload,
            )
            if resp.is_error:
                raise RuntimeError(
                    f"VAPI create_call_from_assistant_id failed ({resp.status_code}): {resp.text}"
                )
            return resp.json()

    async def get_call_status(self, call_id: str) -> str:
        """Get current status of a call."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/call/{call_id}",
                headers=self.headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("status", "unknown")

    async def send_message(self, call_id: str, message: dict) -> dict:
        """Send a system message to an active call."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Use monitor.controlUrl or direct API
            # First get call details to find controlUrl
            call_resp = await client.get(
                f"{self.base_url}/call/{call_id}",
                headers=self.headers,
            )
            call_resp.raise_for_status()
            call_data = call_resp.json()

            control_url = call_data.get("monitor", {}).get("controlUrl")
            if not control_url:
                raise ValueError("No controlUrl found for call")

            payload = {
                "type": "add-message",
                "message": message,
            }

            resp = await client.post(
                control_url,
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def transfer_call(self, call_id: str, destination: dict) -> dict:
        """Transfer an active call to a new destination."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            call_resp = await client.get(
                f"{self.base_url}/call/{call_id}",
                headers=self.headers,
            )
            call_resp.raise_for_status()
            call_data = call_resp.json()

            control_url = call_data.get("monitor", {}).get("controlUrl")
            if not control_url:
                raise ValueError("No controlUrl found for call")

            payload = {
                "type": "transfer",
                "destination": destination,
            }

            resp = await client.post(
                control_url,
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def end_call(self, call_id: str) -> dict:
        """End an active call."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{self.base_url}/call/{call_id}",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()


vapi_client = VAPIService()
