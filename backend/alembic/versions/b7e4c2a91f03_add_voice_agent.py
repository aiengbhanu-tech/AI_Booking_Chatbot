"""add voice agent (merged relay-voice): voice_settings, voice_callbacks, voice_calls

Revision ID: b7e4c2a91f03
Revises: a134bff9748b
Create Date: 2026-11-20 18:00:00.000000

Purely additive: no existing table is altered, so the chatbot keeps working
exactly as before. Voice stays off for every tenant until enabled.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e4c2a91f03"
down_revision: Union[str, None] = "a134bff9748b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("web_voice_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("phone_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("twilio_phone_number", sa.String(32), nullable=True),
        sa.Column("forward_to_number", sa.String(32), nullable=True),
        sa.Column("ring_business_first", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ring_timeout_seconds", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("missed_call_mode", sa.String(20), nullable=False, server_default="ai_answer"),
        sa.Column("callback_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("callback_delay_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("callback_max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("callback_retry_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("callback_window_start_hour", sa.Integer(), nullable=False, server_default="9"),
        sa.Column("callback_window_end_hour", sa.Integer(), nullable=False, server_default="19"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("default_country_code", sa.String(6), nullable=False, server_default="+1"),
        sa.Column("auto_callback_web_leads", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sms_booking_link_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("voice", sa.String(32), nullable=True),
        sa.Column("greeting", sa.Text(), nullable=True),
        sa.Column("extra_instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_voice_settings_tenant_id", "voice_settings", ["tenant_id"], unique=True)
    op.create_index("ix_voice_settings_twilio_phone_number", "voice_settings", ["twilio_phone_number"], unique=True)

    op.create_table(
        "voice_callbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("reason", sa.String(30), nullable=False, server_default="missed_call"),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("source_call_id", sa.Integer(), nullable=True),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_call_sid", sa.String(64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_voice_callbacks_tenant_id", "voice_callbacks", ["tenant_id"])
    op.create_index("ix_voice_callbacks_due", "voice_callbacks", ["status", "next_attempt_at"])

    op.create_table(
        "voice_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False, server_default="inbound"),
        sa.Column("provider_call_sid", sa.String(64), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("from_number", sa.String(32), nullable=True),
        sa.Column("to_number", sa.String(32), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ringing"),
        sa.Column("answered_by", sa.String(20), nullable=True),
        sa.Column("outcome", sa.String(40), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("transcript", sa.JSON(), nullable=True),
        sa.Column("tool_events", sa.JSON(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("callback_id", sa.Integer(), sa.ForeignKey("voice_callbacks.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_voice_calls_tenant_id", "voice_calls", ["tenant_id"])
    op.create_index("ix_voice_calls_provider_call_sid", "voice_calls", ["provider_call_sid"], unique=True)
    op.create_index("ix_voice_calls_session_id", "voice_calls", ["session_id"])
    op.create_index("ix_voice_calls_tenant_started", "voice_calls", ["tenant_id", "started_at"])


def downgrade() -> None:
    op.drop_table("voice_calls")
    op.drop_table("voice_callbacks")
    op.drop_table("voice_settings")
