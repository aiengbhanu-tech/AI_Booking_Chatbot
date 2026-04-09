from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import json

from app.core.db import get_db
from app.tenants.models import Tenant
from app.rag.chat_service import run_chat, stream_chat
from app.leads.models import Lead

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

    return {
        "tenant_name": tenant.name,
        "welcome_message": f"Hi! I'm the assistant for {tenant.name}. How can I help?",
        "calendly_url": tenant.calendly_url,
        "primary_color": "#2563eb",
        "position": "right",
    }


@router.post("/chat")
def widget_chat(payload: ChatRequest, db: Session = Depends(get_db)):
    tenant = get_tenant_by_widget_key(payload.widget_key, db)

    if not payload.message:
        raise HTTPException(status_code=400, detail="Message is required")

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

    return {
        "ok": True,
        "lead_id": lead.id,
        "message": "Lead submitted successfully"
    }