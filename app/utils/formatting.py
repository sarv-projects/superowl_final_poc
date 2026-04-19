"""Formatting utilities."""


def format_duration(seconds: int) -> str:
    """Convert seconds to mm:ss."""
    m = seconds // 60
    s = seconds % 60
    return f"{m}m {s:02d}s"


def truncate(text: str, max_len: int = 150) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
