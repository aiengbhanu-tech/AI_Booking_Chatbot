from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class VoiceSettings(Base):
    """Per-tenant voice configuration. Absent row == voice fully disabled,
    so existing tenants keep the exact chat-only behaviour."""

    __tablename__ = "voice_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id"), nullable=False, unique=True, index=True
    )

    # Voice button inside the website chat widget
    web_voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Phone line (Twilio)
    phone_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    twilio_phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
    forward_to_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ring_business_first: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ring_timeout_seconds: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    # What happens when the business does not pick up: "ai_answer" | "callback_only"
    missed_call_mode: Mapped[str] = mapped_column(String(20), default="ai_answer", nullable=False)

    # Missed-call callbacks
    callback_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    callback_delay_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    callback_max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    callback_retry_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    callback_window_start_hour: Mapped[int] = mapped_column(Integer, default=9, nullable=False)
    callback_window_end_hour: Mapped[int] = mapped_column(Integer, default=19, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    default_country_code: Mapped[str] = mapped_column(String(6), default="+1", nullable=False)
    # Auto-call website visitors who ask for a callback in the chat widget
    auto_callback_web_leads: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Text the Calendly link to callers who want to book
    sms_booking_link_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Persona
    voice: Mapped[str | None] = mapped_column(String(32), nullable=True)
    greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VoiceCall(Base):
    """One voice conversation: a phone call (inbound/outbound) or a widget voice session."""

    __tablename__ = "voice_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # phone | web
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="inbound")  # inbound | outbound
    provider_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    from_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ringing | forwarded | ai_active | completed | missed | voicemail | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ringing")
    answered_by: Mapped[str | None] = mapped_column(String(20), nullable=True)  # business | ai
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    transcript: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_events: Mapped[list | None] = mapped_column(JSON, nullable=True)

    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    callback_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("voice_callbacks.id"), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_voice_calls_tenant_started", "tenant_id", "started_at"),)


class VoiceCallback(Base):
    """An outbound AI call we owe a customer (missed call, or a requested callback)."""

    __tablename__ = "voice_callbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str] = mapped_column(String(30), nullable=False, default="missed_call")  # missed_call | requested | web_lead
    context: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_call_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # pending | dialing | in_progress | completed | voicemail | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_voice_callbacks_due", "status", "next_attempt_at"),)
