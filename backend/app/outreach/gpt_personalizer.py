def generate_personalized_outreach(prospect):
    clinic = prospect.clinic_name or "your clinic"
    audit = prospect.audit_summary or "Your website may have lead capture opportunities."

    return {
        "cold_email": f"""Hi,

I came across {clinic} and noticed this on your website:

{audit}

We built an AI receptionist for dental clinics that answers patient questions 24/7, captures leads, and helps visitors book appointments.

Would you be open to seeing a quick demo?""",

        "follow_up": f"""Hi, just following up.

I had shared an idea for {clinic}: an AI receptionist that can answer patient questions and capture appointment leads even after office hours.

Would a 5-minute demo be useful?""",

        "linkedin_dm": f"""Hi, I checked out {clinic}. We help dental clinics add an AI receptionist to answer patient questions and capture appointments 24/7. Happy to share a quick demo.""",

        "call_script": f"""Hi, this is Bhanu. I’m reaching out because we help dental clinics like {clinic} capture more patient inquiries from their website using an AI receptionist. Is this a bad time for a 30-second explanation?"""
    }