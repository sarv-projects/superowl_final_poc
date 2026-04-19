"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-10
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("phone_number", sa.String(20), unique=True, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("city", sa.String(255)),
        sa.Column("hours", sa.Text()),
        sa.Column("services", sa.Text()),
        sa.Column("fallback_number", sa.String(20), nullable=False),
        sa.Column("nango_connection_id", UUID(as_uuid=True)),
        sa.Column("slack_workspace", sa.String(255)),
        sa.Column("slack_live_channel", sa.String(50)),
        sa.Column("slack_summary_channel", sa.String(50)),
        sa.Column("voice_id", sa.String(100), server_default="pMsXgVXv3BLzUgSXRplE"),
        sa.Column("outbound_welcome_template", sa.Text()),
        sa.Column(
            "callback_trigger_phrase",
            sa.String(255),
            server_default="Would you like us to call you back?",
        ),
        sa.Column("max_call_duration_minutes", sa.Integer(), server_default="10"),
        sa.Column("enable_voice_callbacks", sa.Boolean(), server_default=sa.true()),
        sa.Column("inject_chat_context", sa.Boolean(), server_default=sa.true()),
        sa.Column("post_call_summary_to_chat", sa.Boolean(), server_default=sa.false()),
        sa.Column("inbound_welcome_template", sa.Text()),
        sa.Column(
            "enable_inbound_call_handling", sa.Boolean(), server_default=sa.true()
        ),
        sa.Column(
            "human_transfer_on_escalation", sa.Boolean(), server_default=sa.true()
        ),
        sa.Column(
            "check_with_owner_before_transfer", sa.Boolean(), server_default=sa.true()
        ),
        sa.Column("owner_check_method", sa.String(20), server_default="slack"),
        sa.Column("owner_check_timeout_seconds", sa.Integer(), server_default="30"),
        sa.Column(
            "intent_based_transfer_detection", sa.Boolean(), server_default=sa.true()
        ),
        sa.Column("owner_initiated_handover", sa.Boolean(), server_default=sa.true()),
        sa.Column("live_transcript_to_slack", sa.Boolean(), server_default=sa.true()),
        sa.Column("whisper_coaching_via_slack", sa.Boolean(), server_default=sa.true()),
        sa.Column("call_recording_enabled", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
    )
    op.create_index("idx_businesses_phone", "businesses", ["phone_number"])

    op.create_table(
        "prompt_templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("shared_system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
    )

    op.create_table(
        "call_logs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "business_id",
            UUID(as_uuid=True),
            sa.ForeignKey("businesses.id"),
            nullable=False,
        ),
        sa.Column("call_type", sa.String(20), nullable=False),
        sa.Column("vapi_call_id", sa.String(255), unique=True, nullable=False),
        sa.Column("customer_phone", sa.String(20)),
        sa.Column("customer_name", sa.String(255)),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("outcome", sa.String(50)),
        sa.Column("transcript", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("credits_used", sa.Integer()),
        sa.Column("slack_live_thread_ts", sa.String(50)),
        sa.Column("slack_summary_thread_ts", sa.String(50)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_index("idx_call_logs_business", "call_logs", ["business_id"])
    op.create_index("idx_call_logs_vapi", "call_logs", ["vapi_call_id"])


def downgrade() -> None:
    op.drop_table("call_logs")
    op.drop_table("prompt_templates")
    op.drop_table("businesses")
