from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import settings


def retrieve_context(
    qdrant: QdrantClient,
    tenant_id: int,
    query_vector: list[float],
    top_k: int | None = None,
) -> list[dict]:

    if not query_vector:
        return []

    top_k = min(top_k or settings.TOP_K, 20)

    try:
        hits = qdrant.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=query_vector,
            limit=top_k,
            query_filter=qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="tenant_id",
                        match=qm.MatchValue(value=tenant_id),
                    )
                ]
            ),
            with_payload=True,
        )

    except Exception as e:
        print(f"[RETRIEVER ERROR] tenant={tenant_id} error={repr(e)}")
        return []

    results: list[dict] = []

    for h in hits:
        payload = h.payload if isinstance(h.payload, dict) else {}

        results.append(
            {
                "score": float(h.score),
                "url": payload.get("url"),
                "text": payload.get("text", ""),
                "chunk_index": payload.get("chunk_index"),
            }
        )

    return results