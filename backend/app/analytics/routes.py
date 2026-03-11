from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.db import get_db
from app.core.security import get_current_tenant
from app.tenants.models import Tenant
from app.leads.models import Lead

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
    return {"tenant_id": tenant.id, "total_leads": int(total_leads), "callback_requests": int(callbacks)}