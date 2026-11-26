from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_tenant
from app.tenants.models import Tenant
from app.rag.chat_service import run_chat
from app.plans import can_chat, chat_limit_message
import uuid

router = APIRouter()


# -------------------------
# Schemas
# -------------------------

class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


class ChatOut(BaseModel):
    answer: str
    actions: list[dict]
    sources: list[dict]


# -------------------------
# Route
# -------------------------

@router.post("/chat", response_model=ChatOut)
def chat(
    payload: ChatIn,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    # Validate input
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Every conversation needs an id so it can be counted against the plan
    session_id = payload.session_id or f"api_{uuid.uuid4().hex[:20]}"
    if not can_chat(db, tenant, session_id):
        raise HTTPException(status_code=429, detail=chat_limit_message(tenant))

    try:
        result = run_chat(
            db=db,
            tenant=tenant,
            user_message=payload.message,
            session_id=session_id,
        )

        # Basic structure validation
        if not isinstance(result, dict):
            raise ValueError("Invalid response format from chat service")

        return ChatOut(**result)

    except Exception as e:
        print(f"[CHAT ERROR] tenant={tenant.id} error={repr(e)}")

        raise HTTPException(
            status_code=500,
            detail="Something went wrong while processing the chat request"
        )