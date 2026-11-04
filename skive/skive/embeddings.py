"""임베딩 계산. chunks.embedding 컬럼 차원(1536)과 여기 모델이 항상 맞아야 한다."""

import os

from langchain_openai import OpenAIEmbeddings

MODEL = os.getenv("SKIVE_EMBEDDING_MODEL", "text-embedding-3-small")
DIMENSIONS = 1536


def get_embedder() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=MODEL, dimensions=DIMENSIONS)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return get_embedder().embed_documents(texts)


def embed_query(text: str) -> list[float]:
    return get_embedder().embed_query(text)
