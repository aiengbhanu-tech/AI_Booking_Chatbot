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


def _truncate_context(snippets: list[dict]) -> str:
    # Join snippets, clip to MAX_CONTEXT_CHARS
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
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is missing")

        q_vec = embed_texts([user_message])[0]

        qdrant = QdrantClient(url=settings.QDRANT_URL)
        snippets = retrieve_context(qdrant=qdrant, tenant_id=tenant.id, query_vector=q_vec)
        context = _truncate_context(snippets)

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

        return {
            "answer": assistant_text,
            "actions": actions,
            "sources": [{"url": s.get("url"), "score": s.get("score")} for s in snippets],
        }

    except Exception as e:
        print(f"[CHAT ERROR] tenant_id={tenant.id} error={repr(e)}")
        raise