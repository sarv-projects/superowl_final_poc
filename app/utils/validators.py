"""Validation helpers."""

import re


def validate_phone(phone: str) -> bool:
    """Check if phone number is in E.164 format or 10-digit."""
    pattern = r"^\+?[1-9]\d{1,14}$"
    return bool(re.match(pattern, phone))


def normalize_phone(phone: str) -> str:
    """Strip non-digits and ensure +91 prefix."""
    digits = "".join(filter(str.isdigit, str(phone or "")))
    if len(digits) == 10:
        return f"+91{digits}"
    return f"+{digits}" if digits else ""
