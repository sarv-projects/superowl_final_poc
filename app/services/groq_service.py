"""Groq API client for transcript summarization and chat history."""

import html
import re
from groq import Groq

from app.core.config import settings


class GroqService:
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)

    def summarize_transcript(self, transcript: str, call_type: str = "inbound") -> str:
        """Generate a high-quality, clean summary of the call transcript."""
        if not transcript or len(transcript.strip()) < 10:
            return "Call completed. No substantial conversation to summarize."

        # === STRONG CLEANING ===
        cleaned = re.sub(r'\d{2}:\d{2}:\d{2}\s*-\s*', '', transcript)
        cleaned = re.sub(r'(Assistant|User|Customer|Caller|Roo|Priya):\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        cleaned = cleaned.replace("<", "").replace(">", "")

        # Safe truncation
        truncated = cleaned[:4000] if len(cleaned) > 4000 else cleaned

        prompt = f"""You are an expert call summarizer for {call_type} calls.

Summarize the transcript in **maximum 3 short sentences** using this exact structure:

- Customer wanted: [main request in one short phrase]
- What happened: [key events + escalation if any]
- Follow-up needed: [any action or note, or "None"]

Transcript:
{truncated}

Summary:"""

        try:
            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise, professional call summarizer. Never repeat the transcript. Always be concise, factual, and follow the exact structure requested.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=220,
            )
            # Guard against None content from the API
            content = getattr(response.choices[0].message, "content", None)
            if not content or not isinstance(content, str):
                return "Summary generation failed (empty response)."
            summary = content.strip()
            return html.escape(summary, quote=True)
        except Exception as e:
            print(f"ERROR in summarize_transcript: {e}")
            return f"Summary generation failed ({len(transcript)} chars)."

    def summarize_chat_history(self, messages: list) -> str:
        """Generate a concise summary of a chat conversation history."""
        if not messages:
            return "No conversation history available."

        # Format chat history for the summarizer
        formatted_history = "\n".join([
            f"{msg.get('role', 'unknown').upper()}: {msg.get('content', '')}"
            for msg in messages
            if isinstance(msg, dict) and msg.get('content')
        ])

        if not formatted_history.strip():
            return "No conversation content to summarize."

        prompt = f"""Summarize the customer's main request in ONE short phrase, 5 words max.
No full sentences. No punctuation. Just the core topic.

Examples:
- booking a birthday party
- pricing for wooden toys
- availability this weekend

Chat History:
{formatted_history}

Short phrase:"""

        response = self.client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": "You extract the core customer request as a short phrase only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=30,
        )
        content = getattr(response.choices[0].message, "content", None)
        if content and isinstance(content, str) and content.strip():
            return content.strip()
        return "Chat summary unavailable."


groq_service = GroqService()