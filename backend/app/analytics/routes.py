from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.db import get_db
from app.core.security import get_current_tenant
from app.tenants.models import Tenant
from app.leads.models import Lead
from app.analytics.models import ChatMessage

router = APIRouter()


@router.get("/summary")
def summary(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    total_leads = db.query(func.count(Lead.id)).filter(Lead.tenant_id == tenant.id).scalar() or 0
    callbacks = (
        db.query(func.count(Lead.id))
        .filter(Lead.tenant_id == tenant.id, Lead.intent == "callback")
        .scalar()
        or 0
    )
    total_messages = db.query(func.count(ChatMessage.id)).filter(ChatMessage.tenant_id == tenant.id).scalar() or 0

    return {
        "tenant_id": tenant.id,
        "total_leads": int(total_leads),
        "callback_requests": int(callbacks),
        "total_messages": int(total_messages),
    }


@router.get("/chat-count")
def chat_count(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    total = db.query(func.count(ChatMessage.id)).filter(ChatMessage.tenant_id == tenant.id).scalar() or 0
    return {"total_messages": int(total)}


@router.get("/recent-chats")
def recent_chats(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.tenant_id == tenant.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "session_id": r.session_id,
            "role": r.role,
            "content": r.content,
            "created_at": str(r.created_at),
        }
        for r in rows
    ]