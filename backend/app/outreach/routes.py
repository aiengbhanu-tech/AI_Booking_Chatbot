import csv
import io
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from app.core.db import get_db
from app.outreach.models import Prospect
from app.outreach.schemas import AnalyzeWebsiteRequest, ProspectOut
from app.outreach.website_analyzer import analyze_website
from app.outreach.pitch_generator import generate_simple_pitch

class UpdateStatusRequest(BaseModel):
    status: str

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

@router.post("/import-csv")
def import_prospects_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed")

    content = file.file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))

    created = []

    for row in reader:
        website = row.get("website")

        if not website:
            continue

        if not website.startswith("http"):
            website = "https://" + website

        findings = analyze_website(website)
        pitch = generate_simple_pitch(website, findings)
        audit_summary = "\n".join(findings.get("reasons", []))

        prospect = Prospect(
            clinic_name=row.get("clinic_name") or findings.get("clinic_name"),
            website=website,
            email=row.get("email"),
            phone=row.get("phone"),
            country=row.get("country"),
            city=row.get("city"),
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
        created.append(prospect)

    db.commit()

    return {
        "message": "CSV imported successfully",
        "count": len(created)
    }
    
@router.get("/prospects/filter", response_model=list[ProspectOut])
def filter_prospects(
    min_score: Optional[int] = None,
    status: Optional[str] = None,
    country: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Prospect)

    if min_score is not None:
        query = query.filter(Prospect.score >= min_score)

    if status:
        query = query.filter(Prospect.status == status)

    if country:
        query = query.filter(Prospect.country == country)

    return query.order_by(Prospect.score.desc()).limit(200).all()


@router.patch("/prospects/{prospect_id}/status", response_model=ProspectOut)
def update_prospect_status(
    prospect_id: int,
    payload: UpdateStatusRequest,
    db: Session = Depends(get_db)
):
    allowed_statuses = [
        "new",
        "contacted",
        "replied",
        "demo_booked",
        "closed",
        "lost"
    ]

    if payload.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Use one of: {allowed_statuses}"
        )

    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()

    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    prospect.status = payload.status
    db.commit()
    db.refresh(prospect)

    return prospect