def generate_simple_pitch(website: str, findings: dict) -> str:
    clinic_name = findings.get("clinic_name") or "your clinic"
    reasons = findings.get("reasons", [])

    problem_line = reasons[0] if reasons else "your website may be missing some lead capture opportunities"

    return (
        f"Hi, I came across {clinic_name} and noticed that {problem_line.lower()}. "
        f"We built an AI receptionist for dental clinics that answers patient questions 24/7, "
        f"captures new leads, and helps visitors book appointments directly from the website. "
        f"I’d be happy to show you a quick demo customized for your clinic."
    )