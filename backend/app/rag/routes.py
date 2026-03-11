from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_tenant
from app.tenants.models import Tenant
from app.rag.chat_service import run_chat

router = APIRouter()


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


class ChatOut(BaseModel):
    answer: str
    actions: list[dict]
    sources: list[dict]


@router.post("/chat", response_model=ChatOut)
def chat(
    payload: ChatIn,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    result = run_chat(db=db, tenant=tenant, user_message=payload.message, session_id=payload.session_id)
    return ChatOut(**result)