from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.core.db import Base


class Prospect(Base):
    __tablename__ = "prospects"

    id = Column(Integer, primary_key=True, index=True)
    clinic_name = Column(String(255), nullable=True)
    website = Column(Text, nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)

    has_chatbot = Column(String(10), default="unknown")
    has_booking = Column(String(10), default="unknown")
    has_contact_form = Column(String(10), default="unknown")
    has_faq = Column(String(10), default="unknown")

    score = Column(Integer, default=0)
    status = Column(String(50), default="new")

    audit_summary = Column(Text, nullable=True)
    pitch = Column(Text, nullable=True)
    raw_findings = Column(JSON, nullable=True)
    
    email_variant_1 = Column(Text, nullable=True)
    email_variant_2 = Column(Text, nullable=True)
    dm_variant = Column(Text, nullable=True)
    
    notes = Column(Text, nullable=True)
    last_contacted_at = Column(DateTime(timezone=True), nullable=True)
    next_followup_at = Column(DateTime(timezone=True), nullable=True)

    audit_report = Column(Text, nullable=True)
    campaign_name = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())