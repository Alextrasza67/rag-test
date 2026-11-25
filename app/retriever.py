"""检索器：PGVector + MMR，兼顾相关性与多样性。"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.vectorstore import get_vectorstore


@lru_cache
def get_retriever():
    s = get_settings()
    return get_vectorstore().as_retriever(
        search_type="mmr",
        search_kwargs={"k": s.top_k, "fetch_k": 20, "mmr_lambda": 0.5},
    )
