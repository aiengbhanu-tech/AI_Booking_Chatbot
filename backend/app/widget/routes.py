from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import json

from app.core.db import get_db
from app.tenants.models import Tenant
from app.rag.chat_service import run_chat, stream_chat
from app.leads.models import Lead
from app.voice.service import get_voice_settings, schedule_callback
from app.plans import (
    MIN_WEB_VOICE_SECONDS,
    can_chat,
    chat_limit_message,
    voice_seconds_remaining,
)
from app.core.config import settings

router = APIRouter()


# -------------------------
# Schemas
# -------------------------

class ChatRequest(BaseModel):
    widget_key: str
    message: str
    session_id: str | None = None


class LeadRequest(BaseModel):
    widget_key: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    intent: str = "inquiry"
    notes: str | None = None
    session_id: str | None = None


# -------------------------
# Helpers
# -------------------------

def get_tenant_by_widget_key(widget_key: str, db: Session) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.widget_public_key == widget_key).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


# -------------------------
# Routes
# -------------------------

@router.get("/config")
def widget_config(widget_key: str, db: Session = Depends(get_db)):
    tenant = get_tenant_by_widget_key(widget_key, db)
    vs = get_voice_settings(db, tenant.id)

    return {
        "tenant_name": tenant.name,
        "welcome_message": f"Hi! I'm the assistant for {tenant.name}. How can I help?",
        "calendly_url": tenant.calendly_url,
        "primary_color": "#2563eb",
        "position": "right",
        # Voice agent inside the widget (off unless enabled in the dashboard)
        "voice_enabled": bool(vs and vs.web_voice_enabled),
        # "realtime" = realistic AI voice (uses plan minutes), "browser" = free browser voice
        "voice_mode": _voice_mode(db, tenant, vs),
    }


def _voice_mode(db: Session, tenant: Tenant, vs) -> str:
    if not (vs and vs.web_voice_enabled):
        return "off"
    if (
        vs.web_voice_engine == "auto"
        and settings.OPENAI_API_KEY
        and voice_seconds_remaining(db, tenant) >= MIN_WEB_VOICE_SECONDS
    ):
        return "realtime"
    return "browser"


def _limit_response(tenant: Tenant) -> dict:
    return {
        "answer": chat_limit_message(tenant),
        "actions": [{"type": "show_lead_form", "intent": "inquiry",
                     "message": f"Leave your details and the {tenant.name} team will contact you."}],
        "sources": [],
    }


@router.post("/chat")
def widget_chat(payload: ChatRequest, db: Session = Depends(get_db)):
    tenant = get_tenant_by_widget_key(payload.widget_key, db)

    if not payload.message:
        raise HTTPException(status_code=400, detail="Message is required")

    if not can_chat(db, tenant, payload.session_id):
        return _limit_response(tenant)

    return run_chat(
        db=db,
        tenant=tenant,
        user_message=payload.message,
        session_id=payload.session_id,
    )


@router.get("/chat/stream")
def widget_chat_stream(
    widget_key: str,
    message: str,
    session_id: str,
    db: Session = Depends(get_db),
):
    tenant = get_tenant_by_widget_key(widget_key, db)

    if not can_chat(db, tenant, session_id):
        limited = _limit_response(tenant)

        def limit_generator():
            yield "data: " + json.dumps({"type": "token", "content": limited["answer"]}) + "\n\n"
            yield "data: " + json.dumps({"type": "done", **limited}) + "\n\n"

        return StreamingResponse(limit_generator(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    def event_generator():
        for chunk in stream_chat(
            db=db,
            tenant=tenant,
            user_message=message,
            session_id=session_id,
        ):
            yield f"data: {json.dumps(chunk)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/lead")
def widget_create_lead(payload: LeadRequest, db: Session = Depends(get_db)):
    tenant = get_tenant_by_widget_key(payload.widget_key, db)

    lead = Lead(
        tenant_id=tenant.id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        intent=payload.intent,
        notes=payload.notes,
        session_id=payload.session_id,
    )

    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Optional: have the AI phone agent call this visitor back right away.
    if payload.intent == "callback" and payload.phone:
        try:
            vs = get_voice_settings(db, tenant.id)
            if vs and vs.auto_callback_web_leads:
                schedule_callback(
                    db, vs, payload.phone, "web_lead",
                    name=payload.name, context=payload.notes, lead_id=lead.id, delay_seconds=30,
                )
        except Exception as e:  # never let voice issues break lead capture
            db.rollback()
            print("[WIDGET AUTO-CALLBACK ERROR]", repr(e))

    return {
        "ok": True,
        "lead_id": lead.id,
        "message": "Lead submitted successfully"
    }