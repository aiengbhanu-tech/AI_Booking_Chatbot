import uuid
from fastapi import APIRouter, Depends, HTTPException
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

router = APIRouter()


class IngestRequest(BaseModel):
    website_url: HttpUrl | None = None
    max_pages: int | None = None


class IngestResponse(BaseModel):
    tenant_id: int
    pages_indexed: int
    chunks_indexed: int


def _get_embedding_dimension() -> int:
    probe = embed_texts(["hello world"])
    if not probe or not probe[0]:
        raise RuntimeError("Embedding provider returned empty vectors")
    return len(probe[0])


def _ensure_collection(qdrant: QdrantClient):
    collections = qdrant.get_collections().collections
    exists = any(c.name == settings.QDRANT_COLLECTION for c in collections)
    if not exists:
        vector_size = _get_embedding_dimension()
        qdrant.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
        )


def _run_ingestion(tenant: Tenant, website: str, db: Session, max_pages: int | None = None) -> dict:
    qdrant = QdrantClient(url=settings.QDRANT_URL)
    _ensure_collection(qdrant)

    urls = fetch_sitemap_urls(website)
    if not urls:
        urls = crawl_internal_pages(website, max_pages=max_pages or settings.CRAWL_MAX_PAGES)

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
            vectors = embed_texts(chunks)

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

            qdrant.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)
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


def run_ingestion_for_tenant(tenant_id: int, website_url: str):
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return
        _run_ingestion(tenant=tenant, website=website_url, db=db)
    finally:
        db.close()


@router.post("", response_model=IngestResponse)
def ingest_website(
    payload: IngestRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    website = str(payload.website_url) if payload.website_url else tenant.website_url
    if not website:
        raise HTTPException(status_code=400, detail="website_url missing (provide in request or set on tenant)")

    if payload.website_url and tenant.website_url != website:
        tenant.website_url = website
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

    result = _run_ingestion(
        tenant=tenant,
        website=website,
        db=db,
        max_pages=payload.max_pages,
    )
    return IngestResponse(**result)