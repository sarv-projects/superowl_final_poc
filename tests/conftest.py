"""Pytest configuration and fixtures."""

import pytest_asyncio

from app.core import json_storage


@pytest_asyncio.fixture(autouse=True)
async def setup_storage():
    """Reset JSON storage before each test."""
    json_storage.BUSINESSES_FILE.write_text("{}")
    json_storage.CALL_LOGS_FILE.write_text("[]")
    json_storage.PROMPTS_FILE.write_text("{}")
    yield
    json_storage.BUSINESSES_FILE.write_text("{}")
    json_storage.CALL_LOGS_FILE.write_text("[]")
    json_storage.PROMPTS_FILE.write_text("{}")
