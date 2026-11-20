import json
from datetime import timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import get_current_tenant
from app.tenants.models import Tenant
from app.voice import twilio_client as tw
from app.voice.calls import finalize_call
from app.voice.models import VoiceCall, VoiceCallback, VoiceSettings
from app.voice.phone_bridge import handle_media_stream
from app.voice.prompts import build_instructions, session_config
from app.voice.service import (
    cancel_open_callbacks,
    get_or_create_voice_settings,
    get_voice_settings,
    phone_line_ready,
    schedule_callback,
)
from app.voice.tools import ToolContext, execute_tool, tools_for
from app.voice.utils import normalize_phone, sign_token, tz_or_utc, utcnow, verify_token
from app.voice.worker import reschedule_callback

router = APIRouter()


# ======================================================================
# Dashboard (private X-API-Key)
# ======================================================================

class VoiceSettingsIO(BaseModel):
    web_voice_enabled: bool = False
    phone_enabled: bool = False
    twilio_phone_number: str | None = None
    forward_to_number: str | None = None
    ring_business_first: bool = True
    ring_timeout_seconds: int = Field(20, ge=5, le=60)
    missed_call_mode: str = "ai_answer"
    callback_enabled: bool = True
    callback_delay_seconds: int = Field(60, ge=0, le=86400)
    callback_max_attempts: int = Field(2, ge=1, le=5)
    callback_retry_minutes: int = Field(15, ge=1, le=1440)
    callback_window_start_hour: int = Field(9, ge=0, le=23)
    callback_window_end_hour: int = Field(19, ge=1, le=24)
    timezone: str = "UTC"
    default_country_code: str = "+1"
    auto_callback_web_leads: bool = False
    sms_booking_link_enabled: bool = False
    voice: str | None = None
    greeting: str | None = Field(None, max_length=500)
    extra_instructions: str | None = Field(None, max_length=3000)

    @field_validator("missed_call_mode")
    @classmethod
    def _mode(cls, v):
        if v not in ("ai_answer", "callback_only"):
            raise ValueError("missed_call_mode must be 'ai_answer' or 'callback_only'")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v != "UTC" and tz_or_utc(v) is timezone.utc:
            raise ValueError("Unknown timezone (use an IANA name like America/New_York)")
        return v

    @field_validator("default_country_code")
    @classmethod
    def _cc(cls, v):
        v = (v or "+1").strip()
        if not v.startswith("+") or not v[1:].isdigit() or len(v) > 5:
            raise ValueError("Country code must look like +1 or +91")
        return v

    @field_validator("voice", "greeting", "extra_instructions", "twilio_phone_number", "forward_to_number")
    @classmethod
    def _blank(cls, v):
        return (v or "").strip() or None


def _settings_out(vs: VoiceSettings | None) -> dict:
    base = VoiceSettingsIO().model_dump() if vs is None else {
        k: getattr(vs, k) for k in VoiceSettingsIO.model_fields
    }
    webhook_base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    return {
        "settings": base,
        "platform": {
            "openai_configured": bool(settings.OPENAI_API_KEY),
            "twilio_configured": tw.is_configured(),
            "public_base_url": settings.PUBLIC_BASE_URL,
            "realtime_model": settings.REALTIME_MODEL,
            "webhooks": {
                "voice_url": f"{webhook_base}/v1/voice/twilio/incoming" if webhook_base else None,
                "status_callback_url": f"{webhook_base}/v1/voice/twilio/status" if webhook_base else None,
            },
        },
    }


@router.get("/settings")
def read_settings(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    return _settings_out(get_voice_settings(db, tenant.id))


@router.put("/settings")
def update_settings(payload: VoiceSettingsIO, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    data = payload.model_dump()
    cc = data["default_country_code"]
    for k in ("twilio_phone_number", "forward_to_number"):
        if data[k]:
            n = normalize_phone(data[k], cc)
            if not n:
                raise HTTPException(400, f"{k} is not a valid phone number")
            data[k] = n
    if data["phone_enabled"] and not data["twilio_phone_number"]:
        raise HTTPException(400, "Add your Twilio phone number before enabling the phone line")
    if data["twilio_phone_number"] and data["twilio_phone_number"] == data["forward_to_number"]:
        raise HTTPException(400, "Forward-to number must be different from the Twilio number")

    vs = get_or_create_voice_settings(db, tenant.id)
    for k, v in data.items():
        setattr(vs, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That Twilio number is already connected to another workspace")
    db.refresh(vs)
    return _settings_out(vs)


def _call_out(c: VoiceCall, full: bool = False) -> dict:
    out = {
        "id": c.id,
        "channel": c.channel,
        "direction": c.direction,
        "from_number": c.from_number,
        "to_number": c.to_number,
        "status": c.status,
        "answered_by": c.answered_by,
        "outcome": c.outcome,
        "summary": c.summary,
        "duration_seconds": c.duration_seconds,
        "callback_id": c.callback_id,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "ended_at": c.ended_at.isoformat() if c.ended_at else None,
    }
    if full:
        out["transcript"] = c.transcript or []
        out["tool_events"] = c.tool_events or []
    return out


def _cb_out(cb: VoiceCallback) -> dict:
    return {
        "id": cb.id,
        "phone": cb.phone,
        "name": cb.name,
        "reason": cb.reason,
        "context": cb.context,
        "status": cb.status,
        "attempts": cb.attempts,
        "max_attempts": cb.max_attempts,
        "next_attempt_at": cb.next_attempt_at.isoformat() if cb.next_attempt_at else None,
        "last_error": cb.last_error,
        "created_at": cb.created_at.isoformat() if cb.created_at else None,
    }


@router.get("/summary")
def voice_summary(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    def count(*filters):
        return int(db.query(func.count(VoiceCall.id)).filter(VoiceCall.tenant_id == tenant.id, *filters).scalar() or 0)

    def cb_count(*filters):
        return int(db.query(func.count(VoiceCallback.id)).filter(VoiceCallback.tenant_id == tenant.id, *filters).scalar() or 0)

    return {
        "total_calls": count(VoiceCall.channel == "phone"),
        "web_voice_sessions": count(VoiceCall.channel == "web"),
        "ai_handled": count(VoiceCall.answered_by == "ai", VoiceCall.status == "completed"),
        "missed_calls": count(VoiceCall.channel == "phone", VoiceCall.direction == "inbound", VoiceCall.status == "missed"),
        "callbacks_pending": cb_count(VoiceCallback.status.in_(("pending", "dialing", "in_progress"))),
        "callbacks_completed": cb_count(VoiceCallback.status == "completed"),
    }


@router.get("/calls")
def list_calls(
    channel: str | None = None,
    limit: int = 50,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    q = db.query(VoiceCall).filter(VoiceCall.tenant_id == tenant.id)
    if channel in ("phone", "web"):
        q = q.filter(VoiceCall.channel == channel)
    rows = q.order_by(VoiceCall.started_at.desc()).limit(min(max(limit, 1), 200)).all()
    return [_call_out(c) for c in rows]


@router.get("/calls/{call_id}")
def get_call(call_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    c = db.query(VoiceCall).filter(VoiceCall.id == call_id, VoiceCall.tenant_id == tenant.id).first()
    if not c:
        raise HTTPException(404, "Call not found")
    return _call_out(c, full=True)


@router.get("/callbacks")
def list_callbacks(
    status: str | None = None,
    limit: int = 50,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    q = db.query(VoiceCallback).filter(VoiceCallback.tenant_id == tenant.id)
    if status:
        q = q.filter(VoiceCallback.status == status)
    rows = q.order_by(VoiceCallback.created_at.desc()).limit(min(max(limit, 1), 200)).all()
    return [_cb_out(cb) for cb in rows]


class ManualCallbackIn(BaseModel):
    phone: str
    name: str | None = None
    context: str | None = Field(None, max_length=1000)


@router.post("/callbacks")
def create_callback(payload: ManualCallbackIn, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    vs = get_voice_settings(db, tenant.id)
    if not (phone_line_ready(vs) and vs.callback_enabled):
        raise HTTPException(400, "Enable the phone line and callbacks in Voice settings first")
    cb = schedule_callback(db, vs, payload.phone, "requested", name=payload.name,
                           context=payload.context, delay_seconds=0)
    if not cb:
        raise HTTPException(400, "Invalid phone number")
    return _cb_out(cb)


@router.post("/callbacks/{cb_id}/cancel")
def cancel_callback(cb_id: int, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    cb = db.query(VoiceCallback).filter(VoiceCallback.id == cb_id, VoiceCallback.tenant_id == tenant.id).first()
    if not cb:
        raise HTTPException(404, "Callback not found")
    if cb.status == "pending":
        cb.status = "cancelled"
        cb.last_error = "Cancelled from dashboard"
        db.commit()
    return _cb_out(cb)


# ======================================================================
# Website widget voice (public widget key, browser <-> OpenAI over WebRTC)
# ======================================================================

def _tenant_by_widget(db: Session, widget_key: str) -> Tenant:
    t = db.query(Tenant).filter(Tenant.widget_public_key == widget_key, Tenant.is_active == True).first()  # noqa: E712
    if not t:
        raise HTTPException(404, "Tenant not found")
    return t


class WebSessionIn(BaseModel):
    widget_key: str
    session_id: str = Field(..., max_length=100)
    sdp: str = Field(..., max_length=100_000)


@router.post("/web/session")
def web_session(payload: WebSessionIn, db: Session = Depends(get_db)):
    tenant = _tenant_by_widget(db, payload.widget_key)
    vs = get_voice_settings(db, tenant.id)
    if not (vs and vs.web_voice_enabled):
        raise HTTPException(403, "Voice is not enabled for this assistant")
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, "Voice is temporarily unavailable")

    # Light abuse guard: cap concurrent-ish sessions per widget session
    recent = (
        db.query(func.count(VoiceCall.id))
        .filter(VoiceCall.tenant_id == tenant.id, VoiceCall.session_id == payload.session_id,
                VoiceCall.ended_at.is_(None))
        .scalar()
    )
    if recent and recent >= 3:
        raise HTTPException(429, "Too many open voice sessions")

    cfg = session_config(build_instructions(tenant, vs, "web"), tools_for("web", tenant, vs), vs, phone=False)
    try:
        r = httpx.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            files={"sdp": (None, payload.sdp), "session": (None, json.dumps(cfg))},
            timeout=20,
        )
    except httpx.HTTPError as e:
        print("[WEB VOICE SESSION ERROR]", repr(e))
        raise HTTPException(502, "Voice provider unreachable")
    if r.status_code >= 400:
        print("[WEB VOICE SESSION REFUSED]", r.status_code, r.text[:300])
        raise HTTPException(502, "Voice provider refused the session")

    call = VoiceCall(tenant_id=tenant.id, channel="web", direction="inbound",
                     session_id=payload.session_id, status="ai_active", answered_by="ai")
    db.add(call)
    db.commit()
    db.refresh(call)
    return {
        "sdp": r.text,
        "voice_call_id": call.id,
        "token": sign_token("web", call.id, tenant.id),
        "max_seconds": settings.VOICE_MAX_WEB_SESSION_SECONDS,
        "greeting": (vs.greeting if vs.greeting else
                     f"Greet the visitor warmly as the AI assistant for {tenant.name} and ask how you can help. One short sentence."),
    }


def _web_call(db: Session, widget_key: str, call_id: int, token: str) -> tuple[Tenant, VoiceCall]:
    tenant = _tenant_by_widget(db, widget_key)
    if not verify_token(token, "web", call_id, tenant.id):
        raise HTTPException(403, "Invalid voice session")
    call = db.query(VoiceCall).filter(VoiceCall.id == call_id, VoiceCall.tenant_id == tenant.id,
                                      VoiceCall.channel == "web").first()
    if not call:
        raise HTTPException(404, "Voice session not found")
    return tenant, call


class WebToolIn(BaseModel):
    widget_key: str
    voice_call_id: int
    token: str
    name: str = Field(..., max_length=64)
    arguments: dict = Field(default_factory=dict)


@router.post("/web/tool")
def web_tool(payload: WebToolIn, db: Session = Depends(get_db)):
    tenant, call = _web_call(db, payload.widget_key, payload.voice_call_id, payload.token)
    if call.ended_at:
        raise HTTPException(409, "Voice session already ended")
    events = list(call.tool_events or [])
    if len(events) >= 60:
        raise HTTPException(429, "Too many actions in this session")
    ctx = ToolContext(tenant_id=tenant.id, channel="web", voice_call_id=call.id, session_id=call.session_id)
    started = utcnow()
    result = execute_tool(ctx, payload.name, payload.arguments)
    events.append({"name": payload.name, "args": payload.arguments, "ok": bool(result.get("ok")),
                   "ms": int((utcnow() - started).total_seconds() * 1000)})
    call.tool_events = events
    db.commit()
    return {"result": result, "actions": ctx.controls}


class WebEndIn(BaseModel):
    widget_key: str
    voice_call_id: int
    token: str
    duration_seconds: int = Field(0, ge=0, le=7200)
    transcript: list[dict] = Field(default_factory=list, max_length=400)


@router.post("/web/end")
def web_end(payload: WebEndIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    tenant, call = _web_call(db, payload.widget_key, payload.voice_call_id, payload.token)
    if call.ended_at:
        return {"ok": True}
    transcript = [
        {"role": "assistant" if t.get("role") == "assistant" else "user", "text": str(t.get("text") or "")[:4000]}
        for t in payload.transcript if isinstance(t, dict)
    ]
    events = list(call.tool_events or [])
    duration = min(payload.duration_seconds, settings.VOICE_MAX_WEB_SESSION_SECONDS + 60)
    # Summarising may take a few seconds; don't block the widget.
    background.add_task(finalize_call, call.id, transcript, events, duration, mirror_to_chat=True)
    return {"ok": True}


# ======================================================================
# Twilio phone webhooks
# ======================================================================

def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


async def twilio_params(request: Request) -> dict[str, str]:
    form = {k: str(v) for k, v in (await request.form()).items()}
    if settings.PUBLIC_BASE_URL:
        url = settings.PUBLIC_BASE_URL.rstrip("/") + request.url.path
        if request.url.query:
            url += "?" + request.url.query
    else:
        url = str(request.url)
    if not tw.validate_signature(url, form, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(403, "Invalid Twilio signature")
    return form


def _stream_twiml(call: VoiceCall) -> str:
    return tw.twiml(tw.connect_stream({
        "voice_call_id": str(call.id),
        "token": sign_token("stream", call.id),
    }))


def _get_call(db: Session, voice_call_id: int | None = None, sid: str | None = None) -> VoiceCall | None:
    q = db.query(VoiceCall)
    if voice_call_id is not None:
        return q.filter(VoiceCall.id == voice_call_id).first()
    if sid:
        return q.filter(VoiceCall.provider_call_sid == sid).first()
    return None


@router.post("/twilio/incoming")
def twilio_incoming(p: dict = Depends(twilio_params), db: Session = Depends(get_db)):
    to, frm, sid = p.get("To"), p.get("From"), p.get("CallSid")
    vs = db.query(VoiceSettings).filter(VoiceSettings.twilio_phone_number == to).first()
    if not phone_line_ready(vs):
        return _xml(tw.twiml(tw.say("Sorry, this line is not available right now. Goodbye."), tw.hangup()))

    call = _get_call(db, sid=sid)
    if not call:
        call = VoiceCall(tenant_id=vs.tenant_id, channel="phone", direction="inbound",
                         provider_call_sid=sid, from_number=frm, to_number=to, status="ringing")
        db.add(call)
        db.commit()
        db.refresh(call)

    # They reached us, so any callback we owed them is no longer needed.
    cancel_open_callbacks(db, vs.tenant_id, frm, "Customer called in again")

    if vs.ring_business_first and vs.forward_to_number:
        call.status = "forwarded"
        db.commit()
        action = tw.public_url("/v1/voice/twilio/dial-complete", voice_call_id=call.id)
        return _xml(tw.twiml(tw.dial(vs.forward_to_number, action, vs.ring_timeout_seconds, caller_id=frm)))

    return _xml(_ai_or_fallback(db, call, vs))


def _ai_or_fallback(db: Session, call: VoiceCall, vs: VoiceSettings) -> str:
    if vs.missed_call_mode == "callback_only" or not settings.OPENAI_API_KEY:
        call.status = "missed"
        db.commit()
        schedule_callback(db, vs, call.from_number, "missed_call",
                          context="Called while the team was unavailable.", source_call_id=call.id)
        return tw.twiml(tw.say("Sorry we missed you. We'll call you right back. Goodbye."), tw.hangup())
    return _stream_twiml(call)


@router.post("/twilio/dial-complete")
def twilio_dial_complete(voice_call_id: int, p: dict = Depends(twilio_params), db: Session = Depends(get_db)):
    call = _get_call(db, voice_call_id)
    if not call:
        return _xml(tw.twiml(tw.hangup()))
    if p.get("DialCallStatus") == "completed":
        call.answered_by = "business"
        call.status = "completed"
        call.outcome = "answered_by_business"
        db.commit()
        return _xml(tw.twiml(tw.hangup()))
    # Business didn't pick up (busy / no-answer / failed) — caller still on the line.
    vs = get_voice_settings(db, call.tenant_id)
    if not phone_line_ready(vs):
        return _xml(tw.twiml(tw.hangup()))
    return _xml(_ai_or_fallback(db, call, vs))


@router.post("/twilio/status")
def twilio_status(p: dict = Depends(twilio_params), db: Session = Depends(get_db)):
    """Status callback for the Twilio number (configure in the Twilio console)."""
    status = p.get("CallStatus")
    if status not in ("completed", "busy", "no-answer", "failed", "canceled"):
        return {"ok": True}
    call = _get_call(db, sid=p.get("CallSid"))
    if not call or call.ended_at or call.direction != "inbound":
        return {"ok": True}
    duration = int(p.get("CallDuration") or 0)
    if call.status == "ai_active":
        return {"ok": True}  # the media-stream bridge finalises AI calls itself
    if call.answered_by == "business":
        call.ended_at = utcnow()
        call.duration_seconds = duration
        db.commit()
        return {"ok": True}
    # Caller hung up while ringing the business, or line was busy -> missed call.
    cid = call.id
    db.close()
    finalize_call(cid, [], [], duration)
    return {"ok": True}


@router.post("/twilio/outbound")
def twilio_outbound(voice_call_id: int, p: dict = Depends(twilio_params), db: Session = Depends(get_db)):
    call = _get_call(db, voice_call_id)
    if not call:
        return _xml(tw.twiml(tw.hangup()))
    if not call.provider_call_sid:
        call.provider_call_sid = p.get("CallSid")
    answered_by = p.get("AnsweredBy") or ""
    if answered_by.startswith("machine") or answered_by == "fax":
        tenant = db.query(Tenant).filter(Tenant.id == call.tenant_id).first()
        call.status = "voicemail"
        cb = db.query(VoiceCallback).filter(VoiceCallback.id == call.callback_id).first() if call.callback_id else None
        if cb:
            cb.status = "voicemail"
        db.commit()
        name = tenant.name if tenant else "the business"
        return _xml(tw.twiml(
            tw.say(f"Hi, this is the virtual assistant from {name}, returning your call. "
                   f"Please call us back whenever it's convenient. Thank you!"),
            tw.hangup()))
    db.commit()
    return _xml(_stream_twiml(call))


@router.post("/twilio/outbound-status")
def twilio_outbound_status(voice_call_id: int, p: dict = Depends(twilio_params), db: Session = Depends(get_db)):
    status = p.get("CallStatus")
    call = _get_call(db, voice_call_id)
    if not call or call.ended_at:
        return {"ok": True}
    if status in ("busy", "no-answer", "failed", "canceled"):
        call.status = "failed" if status == "failed" else "missed"
        call.outcome = status.replace("-", "_")
        call.ended_at = utcnow()
        cb = db.query(VoiceCallback).filter(VoiceCallback.id == call.callback_id).first() if call.callback_id else None
        if cb and cb.status in ("dialing", "in_progress"):
            reschedule_callback(cb, get_voice_settings(db, call.tenant_id), f"Call {status}")
        db.commit()
    elif status == "completed" and call.status == "voicemail":
        call.ended_at = utcnow()
        call.duration_seconds = int(p.get("CallDuration") or 0)
        call.outcome = "voicemail_left"
        db.commit()
    return {"ok": True}


@router.post("/twilio/transfer-complete")
def twilio_transfer_complete(p: dict = Depends(twilio_params), db: Session = Depends(get_db)):
    if p.get("DialCallStatus") == "completed":
        return _xml(tw.twiml(tw.hangup()))
    call = _get_call(db, sid=p.get("CallSid"))
    if call:
        vs = get_voice_settings(db, call.tenant_id)
        if vs:
            number = call.from_number if call.direction == "inbound" else call.to_number
            schedule_callback(db, vs, number, "requested",
                              context="Asked for a person; transfer was not answered.", source_call_id=call.id)
    return _xml(tw.twiml(
        tw.say("Sorry, nobody could pick up right now. We'll call you back as soon as possible. Goodbye."),
        tw.hangup()))


@router.websocket("/twilio/media-stream")
async def twilio_media_stream(ws: WebSocket):
    await handle_media_stream(ws)
