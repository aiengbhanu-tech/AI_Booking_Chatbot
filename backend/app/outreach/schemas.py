from pydantic import BaseModel, HttpUrl
from typing import Optional, Any


class AnalyzeWebsiteRequest(BaseModel):
    website: HttpUrl
    country: Optional[str] = None
    city: Optional[str] = None


class ProspectOut(BaseModel):
    id: int
    clinic_name: Optional[str]
    website: str
    country: Optional[str]
    city: Optional[str]
    has_chatbot: str
    has_booking: str
    has_contact_form: str
    has_faq: str
    score: int
    status: str
    audit_summary: Optional[str]
    pitch: Optional[str]
    raw_findings: Optional[Any]

    class Config:
        from_attributes = True