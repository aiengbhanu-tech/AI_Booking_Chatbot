from datetime import timedelta

from sqlalchemy.orm import Session

from app.voice.models import VoiceCallback, VoiceSettings
from app.voice.utils import next_allowed_call_time, normalize_phone, utcnow

OPEN_CALLBACK_STATUSES = ("pending", "dialing", "in_progress")


def get_voice_settings(db: Session, tenant_id: int) -> VoiceSettings | None:
    return db.query(VoiceSettings).filter(VoiceSettings.tenant_id == tenant_id).first()


def get_or_create_voice_settings(db: Session, tenant_id: int) -> VoiceSettings:
    vs = get_voice_settings(db, tenant_id)
    if vs:
        return vs
    vs = VoiceSettings(tenant_id=tenant_id)
    db.add(vs)
    db.commit()
    db.refresh(vs)
    return vs


def phone_line_ready(vs: VoiceSettings | None) -> bool:
    return bool(vs and vs.phone_enabled and vs.twilio_phone_number)


def schedule_callback(
    db: Session,
    vs: VoiceSettings,
    phone: str | None,
    reason: str,
    *,
    name: str | None = None,
    context: str | None = None,
    source_call_id: int | None = None,
    lead_id: int | None = None,
    delay_seconds: int | None = None,
) -> VoiceCallback | None:
    """Queue an AI callback. Returns None if callbacks are off or the number is unusable.

    De-duplicates: if this number already has an open callback, that one is reused
    (and its context extended) instead of calling the customer twice.
    """
    if not (phone_line_ready(vs) and vs.callback_enabled):
        return None

    number = normalize_phone(phone, vs.default_country_code)
    if not number or number == vs.twilio_phone_number:
        return None

    existing = (
        db.query(VoiceCallback)
        .filter(
            VoiceCallback.tenant_id == vs.tenant_id,
            VoiceCallback.phone == number,
            VoiceCallback.status.in_(OPEN_CALLBACK_STATUSES),
        )
        .first()
    )
    if existing:
        if context and context not in (existing.context or ""):
            existing.context = ((existing.context or "") + "\n" + context).strip()[:4000]
        if name and not existing.name:
            existing.name = name[:120]
        db.commit()
        return existing

    delay = vs.callback_delay_seconds if delay_seconds is None else delay_seconds
    due = next_allowed_call_time(
        utcnow() + timedelta(seconds=max(0, delay)),
        vs.timezone,
        vs.callback_window_start_hour,
        vs.callback_window_end_hour,
    )
    cb = VoiceCallback(
        tenant_id=vs.tenant_id,
        phone=number,
        name=(name or None) and name[:120],
        reason=reason,
        context=(context or None) and context[:4000],
        source_call_id=source_call_id,
        lead_id=lead_id,
        status="pending",
        attempts=0,
        max_attempts=max(1, vs.callback_max_attempts),
        next_attempt_at=due,
    )
    db.add(cb)
    db.commit()
    db.refresh(cb)
    return cb


def cancel_open_callbacks(db: Session, tenant_id: int, phone: str | None, note: str) -> int:
    """Customer reached us (e.g. called back in) — don't ring them again."""
    if not phone:
        return 0
    rows = (
        db.query(VoiceCallback)
        .filter(
            VoiceCallback.tenant_id == tenant_id,
            VoiceCallback.phone == phone,
            VoiceCallback.status == "pending",
        )
        .all()
    )
    for cb in rows:
        cb.status = "cancelled"
        cb.last_error = note
    if rows:
        db.commit()
    return len(rows)
