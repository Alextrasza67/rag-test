"""pgvector 向量库封装。"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.models import get_embeddings


@lru_cache
def get_vectorstore():
    from langchain_postgres import PGVector

    s = get_settings()
    return PGVector(
        embeddings=get_embeddings(),
        collection_name=s.collection_name,
        connection=s.pg_url,
        use_jsonb=True,
    )
