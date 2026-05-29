import re
import requests
from bs4 import BeautifulSoup


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def analyze_website(website: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 AI Receptionist Outreach Analyzer"
    }

    try:
        response = requests.get(website, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "clinic_name": None,
            "score": 0,
        }

    soup = BeautifulSoup(response.text, "html.parser")

    title = clean_text(soup.title.text) if soup.title else ""
    page_text = clean_text(soup.get_text(" ")).lower()
    html = response.text.lower()

    chatbot_keywords = [
        "intercom", "drift", "tawk", "crisp", "livechat",
        "zendesk", "chatbot", "chat widget", "messenger"
    ]

    booking_keywords = [
        "book appointment", "schedule appointment", "request appointment",
        "calendly", "zocdoc", "book now", "online booking"
    ]

    faq_keywords = [
        "faq", "frequently asked questions", "questions"
    ]

    has_chatbot = any(k in html for k in chatbot_keywords)
    has_booking = any(k in page_text for k in booking_keywords)
    has_contact_form = "<form" in html
    has_faq = any(k in page_text for k in faq_keywords)

    score = 40

    reasons = []

    if not has_chatbot:
        score += 25
        reasons.append("No visible chatbot or AI receptionist found")

    if not has_booking:
        score += 15
        reasons.append("No clear online booking call-to-action found")

    if not has_contact_form:
        score += 10
        reasons.append("No obvious contact form detected")

    if not has_faq:
        score += 10
        reasons.append("No FAQ section detected")

    if "dentist" in page_text or "dental" in page_text:
        score += 10
        reasons.append("Dental business detected")

    score = min(score, 100)

    return {
        "success": True,
        "clinic_name": title[:255] if title else None,
        "title": title,
        "has_chatbot": "yes" if has_chatbot else "no",
        "has_booking": "yes" if has_booking else "no",
        "has_contact_form": "yes" if has_contact_form else "no",
        "has_faq": "yes" if has_faq else "no",
        "score": score,
        "reasons": reasons,
        "text_sample": page_text[:1500],
    }