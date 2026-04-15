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


# -------------------------
# Chat Storage
# -------------------------

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


# -------------------------
# Context Helpers
# -------------------------

def _truncate_context(snippets: list[dict]) -> str:
    parts = []
    for s in snippets:
        url = s.get("url") or ""
        text = (s.get("text") or "").strip()
        if not text:
            continue
        parts.append(f"[Source: {url}]\n{text}")
    return "\n---\n".join(parts)[: settings.MAX_CONTEXT_CHARS]


def _normalize_whitespace(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _split_sentences(text: str) -> list[str]:
    text = _normalize_whitespace(text)
    if not text:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _extract_best_lines(snippets: list[dict], max_sentences: int = 4) -> list[str]:
    sentences = []
    seen = set()

    for s in snippets[:4]:
        text = _normalize_whitespace(s.get("text") or "")
        for sent in _split_sentences(text):
            if len(sent) < 25:
                continue
            key = sent.lower()
            if key in seen:
                continue
            seen.add(key)
            sentences.append(sent)
            if len(sentences) >= max_sentences:
                return sentences

    return sentences


# -------------------------
# Intent Detection
# -------------------------

def _detect_intent(user_message: str) -> str:
    lower = (user_message or "").lower()

    if any(k in lower for k in ["book", "appointment", "schedule"]):
        return "booking"
    if any(k in lower for k in ["call me", "callback", "contact me"]):
        return "callback"
    if any(k in lower for k in ["price", "cost", "fees"]):
        return "pricing"
    if any(k in lower for k in ["location", "address", "where"]):
        return "location"

    return "general"


# -------------------------
# Fallback Answer
# -------------------------

def _build_human_fallback_answer(user_message: str, snippets: list[dict], tenant: Tenant) -> str:
    intent = _detect_intent(user_message)
    best = _extract_best_lines(snippets)

    if not best:
        return f"I’d be happy to help. Please contact {tenant.name} directly for more details."

    return "\n\n".join(best[:2])


# -------------------------
# OpenAI
# -------------------------

def _try_openai_chat(context: str, user_message: str):
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    return client.chat.completions.create(
        model=settings.OPENAI_CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(user_message, context)},
        ],
        tools=TOOLS,
        tool_choice="auto",
        temperature=0.2,
    )


# -------------------------
# Actions
# -------------------------

def _fallback_actions(tenant: Tenant, user_message: str) -> list[dict]:
    actions = []
    lower = (user_message or "").lower()

    if tenant.calendly_url and "book" in lower:
        actions.append({"type": "open_calendly", "url": tenant.calendly_url})

    if "call" in lower or "callback" in lower:
        actions.append({"type": "show_lead_form", "intent": "callback"})

    return actions


# -------------------------
# MAIN CHAT
# -------------------------

def run_chat(db: Session, tenant: Tenant, user_message: str, session_id: str | None = None) -> dict:
    try:
        save_chat_message(db, tenant.id, session_id, "user", user_message)

        # embeddings
        try:
            q_vec = embed_texts([user_message])[0]
        except Exception:
            q_vec = []

        # retrieve context
        snippets = []
        if settings.QDRANT_URL and q_vec:
            try:
                qdrant = QdrantClient(url=settings.QDRANT_URL,
                        api_key=settings.QDRANT_API_KEY)
                snippets = retrieve_context(qdrant, tenant.id, q_vec)
            except Exception as e:
                print("[QDRANT ERROR]", e)

        context = _truncate_context(snippets)
        actions = []

        try:
            if not settings.OPENAI_API_KEY:
                raise RuntimeError("Missing API key")

            resp = _try_openai_chat(context, user_message)

            msg = resp.choices[0].message if resp and resp.choices else None

            if msg and msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except:
                        args = {}

                    if tc.function.name == "create_lead":
                        lead = Lead(
                            tenant_id=tenant.id,
                            name=args.get("name"),
                            email=args.get("email"),
                            phone=args.get("phone"),
                            intent=args.get("intent", "inquiry"),
                            session_id=session_id,
                        )
                        db.add(lead)
                        db.commit()
                        db.refresh(lead)
                        actions.append({"type": "lead_created", "lead_id": lead.id})

            answer = msg.content if msg and msg.content else None

        except Exception as e:
            print("[OPENAI ERROR]", e)
            answer = None

        if not answer:
            answer = _build_human_fallback_answer(user_message, snippets, tenant)
            actions = _fallback_actions(tenant, user_message)

        save_chat_message(db, tenant.id, session_id, "assistant", answer)

        return {
            "answer": answer,
            "actions": actions,
            "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
        }

    except Exception as e:
        print("[CHAT ERROR]", e)
        return {
            "answer": f"Sorry, something went wrong. Please contact {tenant.name}.",
            "actions": _fallback_actions(tenant, user_message),
            "sources": [],
        }


# -------------------------
# STREAM CHAT
# -------------------------

def stream_chat(db, tenant, user_message: str, session_id: str | None = None):
    try:
        save_chat_message(db, tenant.id, session_id, "user", user_message)

        try:
            q_vec = embed_texts([user_message])[0]
        except:
            q_vec = []

        snippets = []
        if settings.QDRANT_URL and q_vec:
            try:
                qdrant = QdrantClient(url=settings.QDRANT_URL,
                        api_key=settings.QDRANT_API_KEY)
                snippets = retrieve_context(qdrant, tenant.id, q_vec)
            except:
                pass

        context = _truncate_context(snippets)

        try:
            client = OpenAI(api_key=settings.OPENAI_API_KEY)

            stream = client.chat.completions.create(
                model=settings.OPENAI_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(user_message, context)},
                ],
                stream=True,
            )

            full = ""

            for part in stream:
                delta = part.choices[0].delta.content if part.choices else None
                if delta:
                    full += delta
                    yield {"type": "token", "content": delta}

            if not full.strip():
                full = _build_human_fallback_answer(user_message, snippets, tenant)

            save_chat_message(db, tenant.id, session_id, "assistant", full)

            yield {
                "type": "done",
                "answer": full,
                "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
                "actions": _fallback_actions(tenant, user_message),
            }

        except Exception as e:
            print("[STREAM ERROR]", e)
            answer = _build_human_fallback_answer(user_message, snippets, tenant)

            for word in answer.split():
                yield {"type": "token", "content": word + " "}

            yield {
                "type": "done",
                "answer": answer,
                "sources": [],
                "actions": _fallback_actions(tenant, user_message),
            }

    except Exception as e:
        print("[STREAM FATAL ERROR]", e)
        yield {"type": "error", "message": "Assistant unavailable"}