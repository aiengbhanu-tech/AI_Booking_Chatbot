from sqlalchemy import String, Boolean, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # api keys
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    api_key_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    
    widget_public_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # settings (json later)
    calendly_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())