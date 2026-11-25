"""检索器：PGVector + MMR，兼顾相关性与多样性。

只检索「生效版本」的向量: 入库时每个片段的元数据带 active 标记,
切换版本/覆盖后旧版本片段被置为 active=false, 不再参与召回。
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.vectorstore import get_vectorstore

ACTIVE_FILTER = {"active": True}  # 与元数据中的 JSON 布尔一致 (勿用字符串)


@lru_cache
def get_retriever():
    s = get_settings()
    return get_vectorstore().as_retriever(
        search_type="mmr",
        search_kwargs={
            "k": s.top_k,
            "fetch_k": 20,
            "mmr_lambda": 0.5,
            "filter": ACTIVE_FILTER,
        },
    )
