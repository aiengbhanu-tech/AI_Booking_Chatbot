import uuid
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, SessionLocal
from app.core.security import get_current_tenant
from app.tenants.models import Tenant
from app.ingest.crawler import fetch_sitemap_urls, crawl_internal_pages, fetch_html
from app.ingest.cleaner import html_to_text
from app.ingest.chunker import chunk_text
from app.ingest.embeddings import embed_texts
from app.ingest.vector_store import collection_for_dim

router = APIRouter()


# -----------------------------
# Schemas
# -----------------------------

class IngestRequest(BaseModel):
    website_url: HttpUrl | None = None
    max_pages: int | None = None


class IngestResponse(BaseModel):
    tenant_id: int
    pages_indexed: int
    chunks_indexed: int


# -----------------------------
# Helpers
# -----------------------------

def _run_ingestion(
    tenant: Tenant,
    website: str,
    db: Session,
    max_pages: int | None = None
) -> dict:

    if not settings.QDRANT_URL:
        raise RuntimeError("QDRANT_URL not set")

    qdrant = QdrantClient(url=settings.QDRANT_URL,
                          api_key=settings.QDRANT_API_KEY)

    urls = fetch_sitemap_urls(website)
    if not urls:
        urls = crawl_internal_pages(
            website,
            max_pages=max_pages or settings.CRAWL_MAX_PAGES
        )

    urls = urls[: (max_pages or settings.CRAWL_MAX_PAGES)]

    pages_indexed = 0
    chunks_indexed = 0

    for url in urls:
        try:
            html = fetch_html(url)
            text = html_to_text(html)

            if len(text) < 50:
                continue

            chunks = chunk_text(text)
            if not chunks:
                continue
            vectors = embed_texts(chunks)

            # Collection matching this embedding size (created on first use)
            collection = collection_for_dim(qdrant, len(vectors[0]), create=True)

            points: list[qm.PointStruct] = []

            for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
                points.append(
                    qm.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vec,
                        payload={
                            "tenant_id": tenant.id,
                            "url": url,
                            "chunk_index": idx,
                            "text": chunk,
                        },
                    )
                )

            # Replace this page's old chunks so re-indexing doesn't duplicate them
            qdrant.delete(
                collection_name=collection,
                points_selector=qm.FilterSelector(filter=qm.Filter(must=[
                    qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=tenant.id)),
                    qm.FieldCondition(key="url", match=qm.MatchValue(value=url)),
                ])),
            )
            qdrant.upsert(
                collection_name=collection,
                points=points
            )

            pages_indexed += 1
            chunks_indexed += len(points)

        except Exception as e:
            print(f"[INGEST ERROR] url={url} error={repr(e)}")
            continue

    return {
        "tenant_id": tenant.id,
        "pages_indexed": pages_indexed,
        "chunks_indexed": chunks_indexed,
    }


# -----------------------------
# Background task runner
# -----------------------------

def run_ingestion_for_tenant(tenant_id: int, website_url: str):
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            print(f"[INGEST ERROR] Tenant {tenant_id} not found")
            return

        _run_ingestion(
            tenant=tenant,
            website=website_url,
            db=db
        )

        print(f"[INGEST SUCCESS] tenant={tenant_id}")

    except Exception as e:
        import traceback
        print(f"[INGEST FATAL ERROR] tenant={tenant_id} error={repr(e)}")
        traceback.print_exc()

    finally:
        db.close()


# -----------------------------
# API Route
# -----------------------------

@router.post("", response_model=IngestResponse)
def ingest_website(
    payload: IngestRequest,
    background_tasks: BackgroundTasks,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    website = str(payload.website_url) if payload.website_url else tenant.website_url

    if not website:
        raise HTTPException(
            status_code=400,
            detail="website_url missing (provide in request or set on tenant)"
        )

    # Update tenant website if needed
    if payload.website_url and tenant.website_url != website:
        tenant.website_url = website
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

    # Run ingestion in background
    background_tasks.add_task(
        run_ingestion_for_tenant,
        tenant.id,
        website
    )

    return IngestResponse(
        tenant_id=tenant.id,
        pages_indexed=0,
        chunks_indexed=0
    )