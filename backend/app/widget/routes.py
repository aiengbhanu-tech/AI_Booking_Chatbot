from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session
from fastapi import Depends

from app.core.db import get_db
from app.tenants.models import Tenant
from app.rag.chat_service import run_chat

router = APIRouter()


@router.get("/config")
def widget_config(widget_key: str, db: Session = Depends(get_db)):

    tenant = (
        db.query(Tenant)
        .filter(Tenant.widget_public_key == widget_key)
        .first()
    )

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "tenant_name": tenant.name,
        "welcome_message": f"Hi! I'm the assistant for {tenant.name}. How can I help?",
        "calendly_url": tenant.calendly_url,
        "primary_color": "#2563eb",
        "position": "right",
    }

@router.post("/chat")
def widget_chat(payload: dict, db: Session = Depends(get_db)):

    widget_key = payload.get("widget_key")

    tenant = (
        db.query(Tenant)
        .filter(Tenant.widget_public_key == widget_key)
        .first()
    )

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    message = payload.get("message")

    return run_chat(
        db=db,
        tenant=tenant,
        user_message=message,
        session_id=payload.get("session_id"),
    )