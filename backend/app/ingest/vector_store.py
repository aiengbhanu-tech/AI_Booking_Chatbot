"""Pick the Qdrant collection that matches the current embedding size.

A Qdrant collection has a fixed vector size. Switching EMBEDDING_PROVIDER
(sentence-transformers = 384 dims, OpenAI text-embedding-3-small = 1536,
-3-large = 3072) used to make every upsert/search fail with
"Vector dimension error". Instead of deleting data, each size gets its own
collection:

- if QDRANT_COLLECTION exists with the right size (or doesn't exist yet), use it;
- otherwise use f"{QDRANT_COLLECTION}_{dim}".
"""
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import settings

_resolved: dict[int, str] = {}


def _vector_size(qdrant: QdrantClient, name: str) -> int | None:
    """Vector size of an existing collection, or None if it doesn't exist."""
    if not qdrant.collection_exists(name):
        return None
    vectors = qdrant.get_collection(name).config.params.vectors
    if isinstance(vectors, dict):  # named vectors
        vectors = next(iter(vectors.values()))
    return vectors.size


def collection_for_dim(qdrant: QdrantClient, dim: int, create: bool = False) -> str | None:
    """Collection name for vectors of length `dim`.

    With create=True the collection (and tenant_id index) is created if missing.
    With create=False returns None when nothing has been indexed at this size yet.
    """
    if dim in _resolved:
        return _resolved[dim]

    base = settings.QDRANT_COLLECTION
    base_size = _vector_size(qdrant, base)
    if base_size == dim:
        name = base
    elif base_size is None and create:
        name = base
    else:
        name = f"{base}_{dim}"
        if base_size is not None:
            print(f"[QDRANT] '{base}' holds {base_size}-dim vectors; using '{name}' for {dim}-dim embeddings")

    existing = _vector_size(qdrant, name)
    if existing is None:
        if not create:
            return None
        qdrant.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
    elif existing != dim:  # only possible for a hand-made collection with a clashing name
        raise RuntimeError(f"Qdrant collection '{name}' has size {existing}, expected {dim}")

    try:
        qdrant.create_payload_index(
            collection_name=name,
            field_name="tenant_id",
            field_schema=qm.PayloadSchemaType.INTEGER,
        )
    except Exception:
        pass  # index already exists

    _resolved[dim] = name
    return name
