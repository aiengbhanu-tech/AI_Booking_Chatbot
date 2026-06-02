def generate_email_variants(prospect):
    clinic = prospect.clinic_name or "your clinic"

    email_1 = f"""
Hi,

I came across {clinic} and noticed there may be opportunities to improve patient engagement on your website.

We built an AI receptionist that answers questions 24/7, captures leads, and helps patients book appointments automatically.

Would you be open to a quick demo?
"""

    email_2 = f"""
Hi,

Many dental clinics lose potential patients after business hours.

Our AI receptionist helps capture those visitors, answer FAQs instantly, and improve appointment conversions.

Happy to show how it could work specifically for {clinic}.
"""

    dm = f"""
Hi! I checked out {clinic} and thought you might be interested in an AI receptionist that answers patient questions and captures appointments 24/7. Happy to share a quick demo if interested.
"""

    return {
        "email_1": email_1.strip(),
        "email_2": email_2.strip(),
        "dm": dm.strip(),
    }