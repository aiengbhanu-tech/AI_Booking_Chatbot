"""Regression: 'Vector dimension error: expected dim: 384, got 1536' after switching
EMBEDDING_PROVIDER from sentence-transformers to OpenAI."""
import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import settings
from app.ingest import service as ingest_service
from app.ingest import vector_store
from app.rag.retriever import retrieve_context
from app.tenants.models import Tenant


def vec(dim, hot):
    v = [0.0] * dim
    v[hot] = 1.0
    return v


@pytest.fixture
def qdrant(monkeypatch):
    q = QdrantClient(":memory:")
    vector_store._resolved.clear()
    monkeypatch.setattr(settings, "QDRANT_URL", "http://qdrant.test")
    monkeypatch.setattr(ingest_service, "QdrantClient", lambda **kw: q)
    yield q
    vector_store._resolved.clear()


def fake_site(monkeypatch, pages: dict[str, str], dim: int):
    monkeypatch.setattr(ingest_service, "fetch_sitemap_urls", lambda site: list(pages))
    monkeypatch.setattr(ingest_service, "fetch_html", lambda url: pages[url])
    monkeypatch.setattr(ingest_service, "html_to_text", lambda html: html)
    monkeypatch.setattr(ingest_service, "chunk_text", lambda text: [text])
    # "pricing" pages point one way, everything else another
    monkeypatch.setattr(ingest_service, "embed_texts",
                        lambda chunks: [vec(dim, 0 if "price" in c.lower() else 1) for c in chunks])


PAGES = {
    "https://clinic.example/pricing": "Our teeth cleaning price is $120 and whitening costs $300 per session.",
    "https://clinic.example/contact": "Visit us at 12 Main Street, Dallas. Open Monday to Friday 9am to 6pm.",
}


def test_old_384_collection_no_longer_breaks_openai_ingestion(qdrant, monkeypatch):
    # The state on the user's machine: collection created earlier by sentence-transformers
    qdrant.create_collection(settings.QDRANT_COLLECTION,
                             vectors_config=qm.VectorParams(size=384, distance=qm.Distance.COSINE))
    fake_site(monkeypatch, PAGES, dim=1536)

    out = ingest_service._run_ingestion(Tenant(id=7, name="Clinic"), "https://clinic.example", db=None)
    assert out["pages_indexed"] == 2 and out["chunks_indexed"] == 2

    # Old data untouched; new vectors in a size-specific collection
    assert qdrant.get_collection(settings.QDRANT_COLLECTION).config.params.vectors.size == 384
    assert qdrant.get_collection(f"{settings.QDRANT_COLLECTION}_1536").config.params.vectors.size == 1536

    hits = retrieve_context(qdrant, 7, vec(1536, 0))
    assert hits and "price" in hits[0]["text"]
    assert retrieve_context(qdrant, 999, vec(1536, 0)) == []  # tenant isolation


def test_fresh_install_uses_base_collection(qdrant, monkeypatch):
    fake_site(monkeypatch, PAGES, dim=1536)
    ingest_service._run_ingestion(Tenant(id=1, name="Clinic"), "https://clinic.example", db=None)
    assert qdrant.collection_exists(settings.QDRANT_COLLECTION)
    assert not qdrant.collection_exists(f"{settings.QDRANT_COLLECTION}_1536")
    assert retrieve_context(qdrant, 1, vec(1536, 1))[0]["url"] == "https://clinic.example/contact"


def test_reindex_replaces_instead_of_duplicating(qdrant, monkeypatch):
    fake_site(monkeypatch, PAGES, dim=1536)
    tenant = Tenant(id=3, name="Clinic")
    ingest_service._run_ingestion(tenant, "https://clinic.example", db=None)
    ingest_service._run_ingestion(tenant, "https://clinic.example", db=None)
    assert qdrant.count(settings.QDRANT_COLLECTION).count == 2


def test_search_before_anything_indexed_returns_empty(qdrant):
    assert retrieve_context(qdrant, 1, vec(1536, 0)) == []
