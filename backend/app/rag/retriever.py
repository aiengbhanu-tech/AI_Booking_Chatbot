from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import settings


def retrieve_context(
    qdrant: QdrantClient,
    tenant_id: int,
    query_vector: list[float],
    top_k: int | None = None,
) -> list[dict]:
    top_k = top_k or settings.TOP_K

    hits = qdrant.search(
        collection_name=settings.QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=top_k,
        query_filter=qm.Filter(
            must=[qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=tenant_id))]
        ),
        with_payload=True,
    )

    results: list[dict] = []
    for h in hits:
        payload = h.payload or {}
        results.append(
            {
                "score": float(h.score),
                "url": payload.get("url"),
                "text": payload.get("text", ""),
                "chunk_index": payload.get("chunk_index"),
            }
        )
    return results