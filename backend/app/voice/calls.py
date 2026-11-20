from datetime import timedelta

from app.analytics.models import ChatMessage
from app.core.db import SessionLocal
from app.voice.models import VoiceCall, VoiceCallback
from app.voice.prompts import summarize_transcript
from app.voice.service import get_voice_settings, schedule_callback
from app.voice.utils import utcnow

OUTCOME_PRIORITY = [
    ("transfer_to_human", "transferred"),
    ("request_appointment", "appointment_requested"),
    ("send_booking_link", "booking_link_sent"),
    ("request_callback", "callback_requested"),
    ("create_lead", "lead_captured"),
]


def derive_outcome(transcript: list[dict], tool_events: list[dict]) -> str:
    ok_tools = {e.get("name") for e in tool_events if e.get("ok")}
    for tool, outcome in OUTCOME_PRIORITY:
        if tool in ok_tools:
            return outcome
    if any(t.get("role") == "user" and (t.get("text") or "").strip() for t in transcript):
        return "info_provided"
    return "no_conversation"


def finalize_call(
    voice_call_id: int,
    transcript: list[dict],
    tool_events: list[dict],
    duration_seconds: int | None,
    *,
    mirror_to_chat: bool = False,
) -> None:
    """Persist transcript/outcome; detect a phone call that ended with no real conversation
    and queue a missed-call callback for it. Runs in a worker thread."""
    db = SessionLocal()
    try:
        call = db.query(VoiceCall).filter(VoiceCall.id == voice_call_id).first()
        if not call:
            return
        transcript = [t for t in transcript if (t.get("text") or "").strip()][:400]
        call.transcript = transcript
        call.tool_events = tool_events[:100]
        call.duration_seconds = duration_seconds
        call.ended_at = utcnow()
        call.outcome = derive_outcome(transcript, tool_events)

        caller_spoke = call.outcome != "no_conversation"
        if call.status not in ("voicemail", "failed"):
            call.status = "completed" if caller_spoke else "missed"
        db.commit()

        # Widget voice sessions also land in the chat history, so the existing
        # "messages" analytics and session views keep working unchanged.
        if mirror_to_chat and call.session_id:
            for t in transcript:
                db.add(ChatMessage(
                    tenant_id=call.tenant_id,
                    session_id=call.session_id,
                    role="assistant" if t.get("role") == "assistant" else "user",
                    content=("🎤 " + t["text"])[:8000],
                ))
            db.commit()

        if call.callback_id:
            cb = db.query(VoiceCallback).filter(VoiceCallback.id == call.callback_id).first()
            if cb and cb.status in ("dialing", "in_progress"):
                if caller_spoke:
                    cb.status = "completed"
                elif cb.attempts >= cb.max_attempts:
                    cb.status = "failed"
                    cb.last_error = "Answered but no conversation"
                else:
                    vs = get_voice_settings(db, call.tenant_id)
                    cb.status = "pending"
                    cb.next_attempt_at = utcnow() + timedelta(minutes=vs.callback_retry_minutes if vs else 15)
                db.commit()

        # An inbound phone call where the caller never got to talk = missed call.
        if call.channel == "phone" and call.direction == "inbound" and not caller_spoke and call.answered_by != "business":
            vs = get_voice_settings(db, call.tenant_id)
            if vs:
                schedule_callback(db, vs, call.from_number, "missed_call",
                                  context="Caller hung up before speaking to anyone.", source_call_id=call.id)

        if caller_spoke:
            summary = summarize_transcript(transcript)
            if summary:
                call.summary = summary
                db.commit()
    except Exception as e:
        print("[VOICE FINALIZE ERROR]", repr(e))
        db.rollback()
    finally:
        db.close()
