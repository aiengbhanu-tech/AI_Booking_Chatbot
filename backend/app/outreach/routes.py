from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.outreach.models import Prospect
from app.outreach.schemas import AnalyzeWebsiteRequest, ProspectOut
from app.outreach.website_analyzer import analyze_website
from app.outreach.pitch_generator import generate_simple_pitch

router = APIRouter()


@router.post("/analyze", response_model=ProspectOut)
def analyze_prospect(payload: AnalyzeWebsiteRequest, db: Session = Depends(get_db)):
    website = str(payload.website)

    findings = analyze_website(website)
    pitch = generate_simple_pitch(website, findings)

    audit_summary = "\n".join(findings.get("reasons", []))

    prospect = Prospect(
        clinic_name=findings.get("clinic_name"),
        website=website,
        country=payload.country,
        city=payload.city,
        has_chatbot=findings.get("has_chatbot", "unknown"),
        has_booking=findings.get("has_booking", "unknown"),
        has_contact_form=findings.get("has_contact_form", "unknown"),
        has_faq=findings.get("has_faq", "unknown"),
        score=findings.get("score", 0),
        status="new",
        audit_summary=audit_summary,
        pitch=pitch,
        raw_findings=findings,
    )

    db.add(prospect)
    db.commit()
    db.refresh(prospect)

    return prospect


@router.get("/prospects", response_model=list[ProspectOut])
def list_prospects(db: Session = Depends(get_db)):
    return db.query(Prospect).order_by(Prospect.id.desc()).limit(100).all()