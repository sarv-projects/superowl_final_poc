"""JSON-based persistent storage layer."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio

# Data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BUSINESSES_FILE = DATA_DIR / "businesses.json"
CALL_LOGS_FILE = DATA_DIR / "call_logs.json"
PROMPTS_FILE = DATA_DIR / "prompts.json"

# In-memory lock for concurrent writes
_write_lock = asyncio.Lock()


def _ensure_files():
    """Ensure all JSON files exist."""
    if not BUSINESSES_FILE.exists():
        BUSINESSES_FILE.write_text("{}")
    if not CALL_LOGS_FILE.exists():
        CALL_LOGS_FILE.write_text("[]")
    if not PROMPTS_FILE.exists():
        PROMPTS_FILE.write_text("{}")


_ensure_files()


# ============================================================================
# BUSINESS STORAGE
# ============================================================================

async def get_business(business_id: str) -> Optional[Dict[str, Any]]:
    """Get a business by ID."""
    businesses = json.loads(BUSINESSES_FILE.read_text() or "{}")
    return businesses.get(business_id)


async def get_business_by_phone(phone_number: str) -> Optional[Dict[str, Any]]:
    """Get a business by phone number."""
    if not phone_number:
        return None

    query_digits = "".join(filter(str.isdigit, str(phone_number)))
    businesses = json.loads(BUSINESSES_FILE.read_text() or "{}")
    for business in businesses.values():
        stored_phone = business.get("phone_number")
        if stored_phone == phone_number:
            return business

        stored_digits = "".join(filter(str.isdigit, str(stored_phone or "")))
        if query_digits and stored_digits and query_digits == stored_digits:
            return business

        # Match local 10-digit suffix to handle +country-code variations.
        if (
            len(query_digits) >= 10
            and len(stored_digits) >= 10
            and query_digits[-10:] == stored_digits[-10:]
        ):
            return business
    return None


async def list_businesses() -> List[Dict[str, Any]]:
    """List all businesses."""
    businesses = json.loads(BUSINESSES_FILE.read_text() or "{}")
    return list(businesses.values())


async def create_business(business_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new business."""
    async with _write_lock:
        businesses = json.loads(BUSINESSES_FILE.read_text() or "{}")
        
        business_id = str(uuid.uuid4())
        business_data["id"] = business_id
        now = datetime.utcnow().isoformat()
        business_data["created_at"] = now
        business_data["updated_at"] = now
        
        businesses[business_id] = business_data
        BUSINESSES_FILE.write_text(json.dumps(businesses, indent=2))
    
    return business_data


async def update_business(business_id: str, business_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update an existing business."""
    async with _write_lock:
        businesses = json.loads(BUSINESSES_FILE.read_text() or "{}")
        
        if business_id not in businesses:
            return None
        
        # Preserve ID and created_at
        business_data["id"] = business_id
        business_data["created_at"] = businesses[business_id].get("created_at", datetime.utcnow().isoformat())
        business_data["updated_at"] = datetime.utcnow().isoformat()
        
        businesses[business_id] = business_data
        BUSINESSES_FILE.write_text(json.dumps(businesses, indent=2))
    
    return business_data


async def delete_business(business_id: str) -> bool:
    """Delete a business."""
    async with _write_lock:
        businesses = json.loads(BUSINESSES_FILE.read_text() or "{}")
        
        if business_id in businesses:
            del businesses[business_id]
            BUSINESSES_FILE.write_text(json.dumps(businesses, indent=2))
            return True
        return False


# ============================================================================
# CALL LOG STORAGE
# ============================================================================

async def create_call_log(call_log_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new call log."""
    async with _write_lock:
        call_logs = json.loads(CALL_LOGS_FILE.read_text() or "[]")
        
        call_log_data["id"] = str(uuid.uuid4())
        call_log_data["created_at"] = datetime.utcnow().isoformat()
        
        call_logs.append(call_log_data)
        CALL_LOGS_FILE.write_text(json.dumps(call_logs, indent=2))
    
    return call_log_data


async def get_call_log(call_log_id: str) -> Optional[Dict[str, Any]]:
    """Get a call log by ID."""
    call_logs = json.loads(CALL_LOGS_FILE.read_text() or "[]")
    for log in call_logs:
        if log.get("id") == call_log_id:
            return log
    return None


async def get_call_log_by_vapi_id(vapi_call_id: str) -> Optional[Dict[str, Any]]:
    """Get a call log by VAPI call ID."""
    call_logs = json.loads(CALL_LOGS_FILE.read_text() or "[]")
    for log in call_logs:
        if log.get("vapi_call_id") == vapi_call_id:
            return log
    return None


async def update_call_log(call_log_id: str, call_log_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update an existing call log."""
    async with _write_lock:
        call_logs = json.loads(CALL_LOGS_FILE.read_text() or "[]")
        
        for i, log in enumerate(call_logs):
            if log.get("id") == call_log_id:
                call_log_data["id"] = call_log_id
                call_log_data["created_at"] = log.get("created_at", datetime.utcnow().isoformat())
                call_logs[i] = call_log_data
                CALL_LOGS_FILE.write_text(json.dumps(call_logs, indent=2))
                return call_log_data
    
    return None


async def list_call_logs_for_business(business_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """List recent call logs for a business."""
    call_logs = json.loads(CALL_LOGS_FILE.read_text() or "[]")
    filtered = [log for log in call_logs if log.get("business_id") == business_id]
    # Sort by created_at descending
    filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return filtered[:limit]


async def list_all_call_logs(limit: int = 1000) -> List[Dict[str, Any]]:
    """List recent call logs across all businesses."""
    call_logs = json.loads(CALL_LOGS_FILE.read_text() or "[]")
    call_logs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return call_logs[:limit]


# ============================================================================
# PROMPT STORAGE
# ============================================================================

async def create_prompt_template(prompt_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new prompt template."""
    async with _write_lock:
        prompts = json.loads(PROMPTS_FILE.read_text() or "{}")
        
        prompt_id = str(uuid.uuid4())
        prompt_data["id"] = prompt_id
        prompt_data["created_at"] = datetime.utcnow().isoformat()
        
        prompts[prompt_id] = prompt_data
        PROMPTS_FILE.write_text(json.dumps(prompts, indent=2))
    
    return prompt_data


async def get_prompt_template(prompt_id: str) -> Optional[Dict[str, Any]]:
    """Get a prompt template by ID."""
    prompts = json.loads(PROMPTS_FILE.read_text() or "{}")
    return prompts.get(prompt_id)


async def list_prompt_templates() -> List[Dict[str, Any]]:
    """List all prompt templates."""
    prompts = json.loads(PROMPTS_FILE.read_text() or "{}")
    return list(prompts.values())


async def update_prompt_template(prompt_id: str, prompt_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a prompt template."""
    async with _write_lock:
        prompts = json.loads(PROMPTS_FILE.read_text() or "{}")
        
        if prompt_id not in prompts:
            return None
        
        prompt_data["id"] = prompt_id
        prompt_data["created_at"] = prompts[prompt_id].get("created_at", datetime.utcnow().isoformat())
        prompts[prompt_id] = prompt_data
        PROMPTS_FILE.write_text(json.dumps(prompts, indent=2))
    
    return prompt_data


async def delete_prompt_template(prompt_id: str) -> bool:
    """Delete a prompt template."""
    async with _write_lock:
        prompts = json.loads(PROMPTS_FILE.read_text() or "{}")
        
        if prompt_id in prompts:
            del prompts[prompt_id]
            PROMPTS_FILE.write_text(json.dumps(prompts, indent=2))
            return True
        return False


