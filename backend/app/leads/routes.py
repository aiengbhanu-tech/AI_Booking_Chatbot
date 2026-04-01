from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_tenant
from app.tenants.models import Tenant
from app.leads.models import Lead

router = APIRouter()


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    email: str | None
    phone: str | None
    intent: str
    notes: str | None
    created_at: datetime


@router.get("", response_model=list[LeadOut])
def list_leads(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    limit: int = 50,
):
    q = (
        db.query(Lead)
        .filter(Lead.tenant_id == tenant.id)
        .order_by(Lead.created_at.desc())
        .limit(min(limit, 200))
    )
    return q.all()