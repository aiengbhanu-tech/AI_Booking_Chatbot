from fastapi import APIRouter, Depends
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import generate_api_key, _hash_api_key, get_current_tenant, generate_widget_public_key
from app.tenants.models import Tenant

router = APIRouter()


class TenantCreateIn(BaseModel):
    name: str
    website_url: HttpUrl | None = None
    contact_email: str | None = None
    calendly_url: str | None = None


class TenantCreateOut(BaseModel):
    id: int
    name: str
    api_key: str
    widget_key: str
    website_url: str | None = None


@router.post("", response_model=TenantCreateOut)
def create_tenant(payload: TenantCreateIn, db: Session = Depends(get_db)):
    api_key = generate_api_key()
    widget_key = generate_widget_public_key()
    t = Tenant(
        name=payload.name,
        website_url=str(payload.website_url) if payload.website_url else None,
        contact_email=payload.contact_email,
        calendly_url=payload.calendly_url,
        api_key_hash=_hash_api_key(api_key),
        api_key_last4=api_key[-4:],
        widget_public_key=widget_key,
        is_active=True,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return TenantCreateOut(
    id=t.id,
    name=t.name,
    api_key=api_key,
    widget_key=widget_key,
    website_url=t.website_url
    )


class TenantMeOut(BaseModel):
    id: int
    name: str
    website_url: str | None
    api_key_last4: str
    calendly_url: str | None
    contact_email: str | None


@router.get("/me", response_model=TenantMeOut)
def me(tenant: Tenant = Depends(get_current_tenant)):
    return TenantMeOut(
        id=tenant.id,
        name=tenant.name,
        website_url=tenant.website_url,
        api_key_last4=tenant.api_key_last4,
        calendly_url=tenant.calendly_url,
        contact_email=tenant.contact_email,
    )