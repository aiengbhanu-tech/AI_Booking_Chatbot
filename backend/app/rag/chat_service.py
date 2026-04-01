import json
import re
from openai import OpenAI
from qdrant_client import QdrantClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingest.embeddings import embed_texts
from app.rag.prompts import SYSTEM_PROMPT, build_user_prompt
from app.rag.retriever import retrieve_context
from app.rag.tools import TOOLS
from app.leads.models import Lead
from app.tenants.models import Tenant
from app.analytics.models import ChatMessage


def save_chat_message(db: Session, tenant_id: int, session_id: str | None, role: str, content: str):
    if not session_id or not content:
        return
    db.add(
        ChatMessage(
            tenant_id=tenant_id,
            session_id=session_id,
            role=role,
            content=content,
        )
    )
    db.commit()


def _truncate_context(snippets: list[dict]) -> str:
    parts: list[str] = []
    for s in snippets:
        url = s.get("url") or ""
        text = (s.get("text") or "").strip()
        if not text:
            continue
        parts.append(f"[Source: {url}]\n{text}\n")
    joined = "\n---\n".join(parts)
    return joined[: settings.MAX_CONTEXT_CHARS]


def _normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _split_sentences(text: str) -> list[str]:
    text = _normalize_whitespace(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _extract_best_lines(snippets: list[dict], max_sentences: int = 4) -> list[str]:
    sentences: list[str] = []
    seen: set[str] = set()

    for s in snippets[:4]:
        text = _normalize_whitespace(s.get("text") or "")
        if not text:
            continue

        for sent in _split_sentences(text):
            cleaned = sent.strip()
            if len(cleaned) < 25:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            sentences.append(cleaned)
            if len(sentences) >= max_sentences:
                return sentences

    return sentences


def _detect_intent(user_message: str) -> str:
    lower = (user_message or "").lower()

    booking_keywords = [
        "book", "appointment", "schedule", "consultation", "consult", "visit", "meet doctor"
    ]
    callback_keywords = [
        "call me", "callback", "call back", "phone me", "contact me", "speak to someone"
    ]
    pricing_keywords = [
        "price", "pricing", "cost", "fees", "fee", "charges", "how much"
    ]
    location_keywords = [
        "location", "address", "where are you", "where is", "directions", "located"
    ]

    if any(k in lower for k in booking_keywords):
        return "booking"
    if any(k in lower for k in callback_keywords):
        return "callback"
    if any(k in lower for k in pricing_keywords):
        return "pricing"
    if any(k in lower for k in location_keywords):
        return "location"
    return "general"


def _extract_location_hint(snippets: list[dict]) -> str | None:
    text = " ".join(_normalize_whitespace(s.get("text") or "") for s in snippets[:3])

    patterns = [
        r"\b\d{2,6}\s+[A-Za-z0-9\s.,#-]{8,120}\b(?:TX|CA|NY|FL|IL|WA|NJ|PA|OH|GA|NC|VA|AZ|CO|MA)\b\s*\d{5}",
        r"\b[A-Za-z\s]+Office\s+\d{2,6}\s+[A-Za-z0-9\s.,#-]{8,120}\b",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return _normalize_whitespace(m.group(0))

    return None


def _extract_pricing_hint(snippets: list[dict]) -> str | None:
    for s in snippets[:4]:
        text = _normalize_whitespace(s.get("text") or "")
        if not text:
            continue
        lower = text.lower()
        if any(k in lower for k in ["price", "pricing", "cost", "fees", "fee", "$"]):
            return text[:280]
    return None


def _build_human_fallback_answer(user_message: str, snippets: list[dict], tenant: Tenant) -> str:
    intent = _detect_intent(user_message)
    best_lines = _extract_best_lines(snippets, max_sentences=4)

    if not best_lines:
        if intent == "booking":
            return (
                f"I’d be happy to help with booking. "
                f"Please use the booking option below or contact {tenant.name} directly."
            )

        if intent == "callback":
            return (
                f"Sure — please share your phone number and preferred time, "
                f"and someone from {tenant.name} can get back to you."
            )

        if intent == "pricing":
            return (
                f"Pricing can vary depending on the treatment and your specific needs. "
                f"The best next step is to request a consultation with {tenant.name}."
            )

        if intent == "location":
            return (
                f"I couldn’t find the exact location details right now. "
                f"Please check the clinic website or contact {tenant.name} directly."
            )

        return (
            f"I found some relevant information, but I can’t generate a full AI response right now. "
            f"Please contact {tenant.name} directly if you need immediate help."
        )

    if intent == "booking":
        core = best_lines[0]
        answer = (
            f"Yes, I can help with that.\n\n"
            f"{core}"
        )
        if tenant.calendly_url:
            answer += "\n\nYou can use the booking option below to schedule a consultation."
        else:
            answer += "\n\nYou can contact the clinic directly to schedule a visit."
        return answer

    if intent == "callback":
        core = best_lines[0]
        return (
            f"Sure — here’s some relevant information:\n\n"
            f"{core}\n\n"
            f"If you'd like a callback, please share your phone number and preferred time."
        )

    if intent == "pricing":
        pricing_hint = _extract_pricing_hint(snippets)
        if pricing_hint:
            return (
                f"Pricing can depend on the treatment and your needs.\n\n"
                f"{pricing_hint}\n\n"
                f"If you'd like, you can book a consultation to get more specific pricing."
            )

        return (
            f"Pricing usually depends on the type of treatment and your individual case.\n\n"
            f"{best_lines[0]}\n\n"
            f"If you'd like, you can book a consultation for exact pricing."
        )

    if intent == "location":
        location_hint = _extract_location_hint(snippets)
        if location_hint:
            return f"The clinic appears to be located at:\n\n{location_hint}"
        return (
            f"Here’s what I found related to location:\n\n"
            f"{best_lines[0]}"
        )

    if len(best_lines) == 1:
        answer = best_lines[0]
    else:
        answer = f"{best_lines[0]}\n\n{best_lines[1]}"
        if len(best_lines) > 2:
            answer += f"\n\n{best_lines[2]}"

    answer += "\n\nLet me know if you'd like help with booking, pricing, or location details."
    return answer


def _try_openai_chat(context: str, user_message: str):
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(user_message=user_message, context=context)},
    ]

    return client.chat.completions.create(
        model=settings.OPENAI_CHAT_MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        temperature=0.2,
    )


def _fallback_actions(tenant: Tenant, user_message: str) -> list[dict]:
    actions: list[dict] = []
    lower = (user_message or "").lower()

    booking_keywords = [
        "book", "appointment", "schedule", "consultation", "consult", "visit", "meet doctor"
    ]
    callback_keywords = [
        "call me", "callback", "call back", "phone me", "contact me", "speak to someone"
    ]
    pricing_keywords = [
        "price", "pricing", "cost", "fees", "fee", "charges", "how much"
    ]
    location_keywords = [
        "location", "address", "where are you", "where is", "directions", "located"
    ]

    if tenant.calendly_url and any(k in lower for k in booking_keywords):
        actions.append({"type": "open_calendly", "url": tenant.calendly_url})
        actions.append({
            "type": "show_lead_form",
            "intent": "appointment",
            "message": "You can also leave your details and the clinic can contact you."
        })

    if any(k in lower for k in callback_keywords):
        actions.append({
            "type": "show_lead_form",
            "intent": "callback",
            "message": "Please share your details for a callback."
        })

    if any(k in lower for k in pricing_keywords):
        actions.append({
            "type": "show_lead_form",
            "intent": "pricing",
            "message": "If you'd like exact pricing, leave your details and request a consultation."
        })

    if any(k in lower for k in location_keywords):
        actions.append({
            "type": "location_suggested",
            "message": "I can help with location details from the website information."
        })

    return actions

def run_chat(
    db: Session,
    tenant: Tenant,
    user_message: str,
    session_id: str | None = None,
) -> dict:
    try:
        save_chat_message(db, tenant.id, session_id, "user", user_message)

        q_vec = embed_texts([user_message])[0]
        qdrant = QdrantClient(url=settings.QDRANT_URL)
        snippets = retrieve_context(qdrant=qdrant, tenant_id=tenant.id, query_vector=q_vec)
        context = _truncate_context(snippets)

        if settings.CHAT_PROVIDER == "mock":
            assistant_text = _build_human_fallback_answer(user_message, snippets, tenant)
            save_chat_message(db, tenant.id, session_id, "assistant", assistant_text)
            return {
                "answer": assistant_text,
                "actions": _fallback_actions(tenant, user_message),
                "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
            }

        actions: list[dict] = []

        try:
            if not settings.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY is missing")

            resp = _try_openai_chat(context=context, user_message=user_message)
            choice = resp.choices[0]
            msg = choice.message

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")

                    if name == "create_lead":
                        lead = Lead(
                            tenant_id=tenant.id,
                            name=args.get("name"),
                            email=args.get("email"),
                            phone=args.get("phone"),
                            intent=args.get("intent", "inquiry"),
                            notes=args.get("notes"),
                            session_id=session_id,
                        )
                        db.add(lead)
                        db.commit()
                        db.refresh(lead)
                        actions.append({"type": "lead_created", "lead_id": lead.id})

                    elif name == "request_callback":
                        lead = Lead(
                            tenant_id=tenant.id,
                            name=None,
                            email=None,
                            phone=args.get("phone"),
                            intent="callback",
                            notes=f"Preferred time: {args.get('preferred_time')}. Notes: {args.get('notes')}",
                            session_id=session_id,
                        )
                        db.add(lead)
                        db.commit()
                        db.refresh(lead)
                        actions.append({"type": "callback_requested", "lead_id": lead.id})

                    elif name == "book_via_calendly":
                        if tenant.calendly_url:
                            actions.append({"type": "open_calendly", "url": tenant.calendly_url})
                        else:
                            actions.append({"type": "missing_calendly", "message": "Calendly not configured for tenant."})

            assistant_text = msg.content or _build_human_fallback_answer(user_message, snippets, tenant)

        except Exception as openai_error:
            print(f"[OPENAI FALLBACK] tenant_id={tenant.id} error={repr(openai_error)}")
            assistant_text = _build_human_fallback_answer(user_message, snippets, tenant)
            actions = _fallback_actions(tenant, user_message)

        save_chat_message(db, tenant.id, session_id, "assistant", assistant_text)

        return {
            "answer": assistant_text,
            "actions": actions,
            "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
        }

    except Exception as e:
        print(f"[CHAT ERROR] tenant_id={tenant.id} error={repr(e)}")
        return {
            "answer": f"I’m sorry, I’m temporarily unavailable. Please contact {tenant.name} directly.",
            "actions": _fallback_actions(tenant, user_message),
            "sources": [],
        }


def stream_chat(db, tenant, user_message: str, session_id: str | None = None):
    try:
        save_chat_message(db, tenant.id, session_id, "user", user_message)

        q_vec = embed_texts([user_message])[0]
        qdrant = QdrantClient(url=settings.QDRANT_URL)
        snippets = retrieve_context(qdrant=qdrant, tenant_id=tenant.id, query_vector=q_vec)
        context = _truncate_context(snippets)

        if settings.CHAT_PROVIDER == "mock":
            answer = _build_human_fallback_answer(user_message, snippets, tenant)
            save_chat_message(db, tenant.id, session_id, "assistant", answer)
            for token in answer.split():
                yield {"type": "token", "content": token + " "}
            yield {
                "type": "done",
                "answer": answer,
                "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
                "actions": _fallback_actions(tenant, user_message),
            }
            return

        try:
            if not settings.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY missing")

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            stream = client.chat.completions.create(
                model=settings.OPENAI_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(user_message=user_message, context=context)},
                ],
                temperature=0.2,
                stream=True,
            )

            full_text = ""

            for part in stream:
                delta = part.choices[0].delta.content if part.choices and part.choices[0].delta else None
                if delta:
                    full_text += delta
                    yield {"type": "token", "content": delta}

            if not full_text.strip():
                full_text = _build_human_fallback_answer(user_message, snippets, tenant)

            save_chat_message(db, tenant.id, session_id, "assistant", full_text)

            yield {
                "type": "done",
                "answer": full_text,
                "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
                "actions": [],
            }

        except Exception as openai_error:
            print(f"[STREAM OPENAI FALLBACK] tenant_id={tenant.id} error={repr(openai_error)}")
            answer = _build_human_fallback_answer(user_message, snippets, tenant)
            save_chat_message(db, tenant.id, session_id, "assistant", answer)

            for token in answer.split():
                yield {"type": "token", "content": token + " "}

            yield {
                "type": "done",
                "answer": answer,
                "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
                "actions": _fallback_actions(tenant, user_message),
            }

    except Exception as e:
        print(f"[STREAM CHAT ERROR] tenant_id={tenant.id} error={repr(e)}")
        yield {"type": "error", "message": "Assistant temporarily unavailable"}