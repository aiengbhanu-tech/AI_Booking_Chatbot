from typing import List
from app.core.config import settings

_model = None  # cache for sentence-transformers


def embed_texts(texts: List[str]) -> List[List[float]]:

    if settings.EMBEDDING_PROVIDER == "openai":
        return _embed_openai(texts)

    if settings.EMBEDDING_PROVIDER == "sentence_transformers":
        return _embed_sentence_transformers(texts)

    raise ValueError(f"Invalid embedding provider: {settings.EMBEDDING_PROVIDER}")


def _embed_openai(texts: List[str]):

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    resp = client.embeddings.create(
        model=settings.OPENAI_EMBED_MODEL,
        input=texts,
    )

    return [d.embedding for d in resp.data]


def _embed_sentence_transformers(texts: List[str]):

    global _model

    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.SENTENCE_TRANSFORMER_MODEL)

    vectors = _model.encode(texts)
    return vectors.tolist()