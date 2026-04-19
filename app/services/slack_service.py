"""Slack notification builders and senders."""

from typing import Optional

from app.services.nango_service import nango_client


class SlackService:
    async def send_live_call_notification(
        self,
        connection_id: str,
        channel: str,
        call_type: str,
        call_log_id: str,
        vapi_call_id: str,
        business_name: str,
        customer_phone: str,
        customer_name: Optional[str] = None,
        agent_name: str = "Roo",
        voice_name: str = "Priya",
    ) -> dict:
        """Send initial live call notification with Block Kit buttons."""
        if call_type == "inbound":
            header = "📥 Inbound Call — LIVE"
            color = "#22c27a"
        else:
            header = "📤 Outbound Callback — LIVE"
            color = "#5b5ef4"

        customer_display = customer_name or customer_phone

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{header}*  ·  🟢 *Active*  `0s`"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*CUSTOMER*\n{customer_display}"},
                    {"type": "mrkdwn", "text": f"*BUSINESS*\n{business_name}"},
                    {"type": "mrkdwn", "text": f"*PHONE*\n{customer_phone}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*AI AGENT*\n{agent_name} ({voice_name})",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*📝 LIVE TRANSCRIPT*\n_Waiting for first utterance..._",
                },
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🤫 Whisper to AI"},
                        "action_id": "whisper",
                        "value": vapi_call_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📞 Take Over Call"},
                        "action_id": "takeover",
                        "value": vapi_call_id,
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✋ Transfer to Me"},
                        "action_id": "transfer",
                        "value": vapi_call_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔇 End Call"},
                        "action_id": "end_call",
                        "value": vapi_call_id,
                        "style": "danger",
                    },
                ],
            },
        ]

        return await nango_client.proxy_request(
            connection_id=connection_id,
            method="POST",
            endpoint="chat.postMessage",
            data={
                "channel": channel,
                "blocks": blocks,
                "attachments": [{"color": color}],
            },
        )

    async def send_post_call_summary(
        self,
        connection_id: str,
        channel: str,
        call_type: str,
        customer_phone: str,
        customer_name: Optional[str],
        duration_seconds: int,
        outcome: str,
        summary: str,
        transcript_preview: str,
        credits_used: int,
        vapi_call_id: str,
        call_log_id: str,
    ) -> dict:
        """Send post-call summary with Block Kit buttons."""
        if call_type == "inbound":
            header = "📥 Inbound Call Completed"
            color = "#22c27a"
        else:
            header = "📤 Outbound Callback Completed"
            color = "#5b5ef4"

        outcome_badges = {
            "resolved": "✅ AI Resolved",
            "transferred": "🔀 Transferred to Owner",
            "abandoned": "⚠️ Unresolved",
            "timeout": "⏱️ Timeout",
            "owner_declined": "❌ Owner Declined",
        }
        outcome_badge = outcome_badges.get(outcome, outcome)

        duration_str = f"{duration_seconds // 60}m {duration_seconds % 60}s"
        customer_display = customer_name or customer_phone

        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{header}*  ·  {outcome_badge}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*CUSTOMER*\n{customer_display}"},
                    {"type": "mrkdwn", "text": f"*PHONE*\n{customer_phone}"},
                    {"type": "mrkdwn", "text": f"*DURATION*\n{duration_str}"},
                    {"type": "mrkdwn", "text": f"*CREDITS USED*\n{credits_used} cr"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🤖 AI SUMMARY*\n{summary}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📝 TRANSCRIPT (excerpt)*\n{transcript_preview}",
                },
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📄 Full Transcript"},
                        "action_id": "view_transcript",
                        "value": vapi_call_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📞 Call Back"},
                        "action_id": "callback",
                        "value": customer_phone,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Mark Resolved"},
                        "action_id": "mark_resolved",
                        "value": call_log_id,
                        "style": "primary",
                    },
                ],
            },
        ]

        return await nango_client.proxy_request(
            connection_id=connection_id,
            method="POST",
            endpoint="chat.postMessage",
            data={
                "channel": channel,
                "blocks": blocks,
                "attachments": [{"color": color}],
            },
        )

    async def send_owner_approval_request(
        self,
        connection_id: str,
        channel: str,
        customer_name: str,
        customer_phone: str,
        reason: str,
        call_id: str,
        business_name: str,
    ) -> dict:
        """Send Slack message asking owner to approve transfer to them."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📞 Transfer Request — {business_name}*"
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*CUSTOMER*\n{customer_name}"},
                    {"type": "mrkdwn", "text": f"*PHONE*\n{customer_phone}"},
                    {"type": "mrkdwn", "text": f"*REASON*\n{reason}"},
                    {"type": "mrkdwn", "text": f"*CALL ID*\n`{call_id}`"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Do you want to take this call?*"
            },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Yes, transfer to me"},
                        "action_id": "approve_transfer",
                        "style": "primary",
                        "value": call_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ No, stay on AI"},
                        "action_id": "decline_transfer",
                        "style": "danger",
                        "value": call_id,
                    },
                ],
            },
        ]

        return await nango_client.proxy_request(
            connection_id=connection_id,
            method="POST",
            endpoint="chat.postMessage",
            data={
                "channel": channel,
                "blocks": blocks,
                "attachments": [{"color": "#f59e0b"}],
            },
        )


slack_service = SlackService()
