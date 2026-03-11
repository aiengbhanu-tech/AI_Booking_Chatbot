import json
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


def run_chat(
    db: Session,
    tenant: Tenant,
    user_message: str,
    session_id: str | None = None,
) -> dict:
    try:
        if not settings.OPENAI_API_KEY and settings.CHAT_PROVIDER == "openai":
            raise RuntimeError("OPENAI_API_KEY is missing")

        save_chat_message(db, tenant.id, session_id, "user", user_message)

        q_vec = embed_texts([user_message])[0]
        qdrant = QdrantClient(url=settings.QDRANT_URL)
        snippets = retrieve_context(qdrant=qdrant, tenant_id=tenant.id, query_vector=q_vec)
        context = _truncate_context(snippets)

        if settings.CHAT_PROVIDER == "mock":
            assistant_text = f"Demo response for: {user_message}"
            save_chat_message(db, tenant.id, session_id, "assistant", assistant_text)
            return {
                "answer": assistant_text,
                "actions": [],
                "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
            }

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(user_message=user_message, context=context)},
        ]

        resp = client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )

        choice = resp.choices[0]
        msg = choice.message

        actions: list[dict] = []

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

        assistant_text = msg.content or "How can I help you?"
        save_chat_message(db, tenant.id, session_id, "assistant", assistant_text)

        return {
            "answer": assistant_text,
            "actions": actions,
            "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
        }

    except Exception as e:
        print(f"[CHAT ERROR] tenant_id={tenant.id} error={repr(e)}")
        raise


def stream_chat(db, tenant, user_message: str, session_id: str | None = None):
    if not settings.OPENAI_API_KEY and settings.CHAT_PROVIDER == "openai":
        yield {"type": "error", "message": "OPENAI_API_KEY missing"}
        return

    try:
        save_chat_message(db, tenant.id, session_id, "user", user_message)

        q_vec = embed_texts([user_message])[0]
        qdrant = QdrantClient(url=settings.QDRANT_URL)
        snippets = retrieve_context(qdrant=qdrant, tenant_id=tenant.id, query_vector=q_vec)
        context = _truncate_context(snippets)

        if settings.CHAT_PROVIDER == "mock":
            answer = f"Demo response for: {user_message}"
            save_chat_message(db, tenant.id, session_id, "assistant", answer)
            for token in answer.split():
                yield {"type": "token", "content": token + " "}
            yield {
                "type": "done",
                "answer": answer,
                "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
                "actions": [],
            }
            return

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

        save_chat_message(db, tenant.id, session_id, "assistant", full_text)

        yield {
            "type": "done",
            "answer": full_text,
            "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
            "actions": [],
        }

    except Exception as e:
        print(f"[STREAM CHAT ERROR] tenant_id={tenant.id} error={repr(e)}")
        yield {"type": "error", "message": "Assistant temporarily unavailable"}