import hashlib
import secrets
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.tenants.models import Tenant


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def _hash_api_key(api_key: str) -> str:
    # Stable hash (store hash only, not raw key)
    data = (settings.API_KEY_SALT + api_key).encode("utf-8")
    return hashlib.sha256(data).hexdigest()

def generate_api_key() -> str:
    # 32-48 chars safe token
    return secrets.token_urlsafe(32)

def verify_api_key(db: Session, api_key: str) -> Tenant | None:
    h = _hash_api_key(api_key)
    return db.query(Tenant).filter(Tenant.api_key_hash == h, Tenant.is_active == True).first()  # noqa: E712

def generate_widget_public_key() -> str:
    return "pub_" + secrets.token_urlsafe(24)

def get_current_tenant(
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> Tenant:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key")

    tenant = verify_api_key(db, api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return tenant