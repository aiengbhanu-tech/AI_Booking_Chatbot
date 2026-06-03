def generate_audit(prospect):
    return f"""
Website Audit Report

Clinic:
{prospect.clinic_name}

Score:
{prospect.score}/100

Issues Found:
{prospect.audit_summary}

Recommendation:
Install an AI receptionist to capture leads, answer FAQs, and improve appointment conversions.

Estimated Benefit:
24/7 patient engagement and improved lead capture.
""".strip()