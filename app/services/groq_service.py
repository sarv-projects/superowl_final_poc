"""Groq API client for transcript summarization."""

from groq import Groq

from app.core.config import settings


class GroqService:
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)

    def summarize_transcript(self, transcript: str, call_type: str = "inbound") -> str:
        """Generate a concise summary of the call transcript."""
        # Handle empty or too-short transcripts
        if not transcript or len(transcript.strip()) < 10:
            return "Call completed. No substantial conversation to summarize."

        # Truncate very long transcripts to avoid token limits
        truncated = transcript[:3000] if len(transcript) > 3000 else transcript

        prompt = f"""Summarize this {call_type} call transcript in 2-3 sentences.
Include: what the customer needed, what was resolved, and any follow-up actions.

Transcript:
{truncated}

Summary:"""

        try:
            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that summarizes voice call transcripts. Provide clear, concise summaries focusing on what the customer wanted and what was accomplished.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=150,
            )
            summary = response.choices[0].message.content or "No summary available."
            return summary.strip()
        except Exception as e:
            print(f"ERROR in summarize_transcript: {e}")
            return f"Summary generation failed. Transcript length: {len(transcript)} chars."

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

        prompt = f"""Summarize this chat conversation in 1-2 concise sentences.
Focus on: the customer's main request/need and any key information they shared.
Keep it brief and factual.

Chat History:
{formatted_history}

Summary:"""

        response = self.client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that creates brief, accurate summaries of customer chat conversations.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=100,
        )
        return response.choices[0].message.content or "Chat summary unavailable."


groq_service = GroqService()
