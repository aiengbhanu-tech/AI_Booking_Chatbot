"""Background loop that places AI callbacks (missed calls, requested callbacks).

Runs inside the API process (started from main.lifespan). Rows are claimed with
SELECT ... FOR UPDATE SKIP LOCKED, so running several API replicas is safe.
"""
import asyncio
from datetime import timedelta

from app.core.config import settings
from app.core.db import SessionLocal
from app.voice import twilio_client
from app.voice.models import VoiceCall, VoiceCallback
from app.voice.service import get_voice_settings, phone_line_ready
from app.voice.utils import next_allowed_call_time, utcnow

BATCH = 5
STALE_DIALING = timedelta(minutes=10)


def reschedule_callback(cb: VoiceCallback, vs, error: str | None) -> None:
    cb.last_error = error
    if cb.attempts >= cb.max_attempts:
        cb.status = "failed"
        return
    cb.status = "pending"
    retry = utcnow() + timedelta(minutes=vs.callback_retry_minutes if vs else 15)
    cb.next_attempt_at = next_allowed_call_time(
        retry,
        vs.timezone if vs else "UTC",
        vs.callback_window_start_hour if vs else 9,
        vs.callback_window_end_hour if vs else 19,
    )


def process_due_callbacks() -> int:
    if not twilio_client.is_configured():
        return 0
    db = SessionLocal()
    placed = 0
    try:
        # Recover rows stuck in "dialing" (e.g. process died mid-call setup)
        stale = (
            db.query(VoiceCallback)
            .filter(VoiceCallback.status == "dialing", VoiceCallback.updated_at < utcnow() - STALE_DIALING)
            .all()
        )
        for cb in stale:
            reschedule_callback(cb, get_voice_settings(db, cb.tenant_id), "Timed out while dialing")
        db.commit()

        q = (
            db.query(VoiceCallback)
            .filter(VoiceCallback.status == "pending", VoiceCallback.next_attempt_at <= utcnow())
            .order_by(VoiceCallback.next_attempt_at)
            .limit(BATCH)
        )
        if db.bind.dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        due = q.all()

        for cb in due:
            vs = get_voice_settings(db, cb.tenant_id)
            if not (phone_line_ready(vs) and vs.callback_enabled):
                cb.status = "cancelled"
                cb.last_error = "Phone line or callbacks disabled"
                continue
            # Respect calling hours even if settings changed after scheduling
            allowed = next_allowed_call_time(utcnow(), vs.timezone, vs.callback_window_start_hour, vs.callback_window_end_hour)
            if allowed > utcnow() + timedelta(minutes=1):
                cb.next_attempt_at = allowed
                continue
            cb.status = "dialing"
            cb.attempts += 1
        db.commit()

        for cb in [c for c in due if c.status == "dialing"]:
            vs = get_voice_settings(db, cb.tenant_id)
            call = VoiceCall(
                tenant_id=cb.tenant_id,
                channel="phone",
                direction="outbound",
                from_number=vs.twilio_phone_number,
                to_number=cb.phone,
                status="ringing",
                callback_id=cb.id,
            )
            db.add(call)
            db.commit()
            db.refresh(call)
            try:
                sid = twilio_client.create_call(
                    to=cb.phone,
                    from_=vs.twilio_phone_number,
                    answer_url=twilio_client.public_url("/v1/voice/twilio/outbound", voice_call_id=call.id),
                    status_url=twilio_client.public_url("/v1/voice/twilio/outbound-status", voice_call_id=call.id),
                )
                call.provider_call_sid = sid
                cb.last_call_sid = sid
                placed += 1
            except Exception as e:
                print("[CALLBACK DIAL ERROR]", repr(e))
                call.status = "failed"
                call.ended_at = utcnow()
                reschedule_callback(cb, vs, str(e)[:500])
            db.commit()
        return placed
    except Exception as e:
        print("[CALLBACK WORKER ERROR]", repr(e))
        db.rollback()
        return placed
    finally:
        db.close()


async def callback_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(process_due_callbacks)
        except Exception as e:
            print("[CALLBACK LOOP ERROR]", repr(e))
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.VOICE_CALLBACK_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
