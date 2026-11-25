"""文档注册表：记录向量数据的来源文件、哈希与版本，支撑去重与版本管理。

表结构:
    doc_registry  逻辑文档 (一个路径一条): doc_id, rel_path, file_name, latest_version
    doc_version   物理版本 (一个版本一条): sha256, size, chunk_count, is_active, ingested_at

向量关联:
    langchain_pg_embedding.cmetadata 内保存 doc_id / version / active 字段,
    通过 cmetadata->>'doc_id' 与注册表逻辑关联 (jsonb 无法建外键, 由本模块保证一致)。
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import create_engine, text

from app.config import get_settings

_engine = None

_DDL = """
CREATE TABLE IF NOT EXISTS doc_registry (
    doc_id         UUID PRIMARY KEY,
    rel_path       TEXT NOT NULL UNIQUE,
    file_name      TEXT NOT NULL,
    latest_version INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS doc_version (
    doc_id       UUID NOT NULL REFERENCES doc_registry(doc_id) ON DELETE CASCADE,
    version      INTEGER NOT NULL,
    sha256       TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    chunk_count  INTEGER NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT FALSE,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, version)
);
"""


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().pg_url, pool_pre_ping=True)
    return _engine


def ensure_schema() -> None:
    with get_engine().begin() as conn:
        conn.execute(text(_DDL))


def sha256_of(path) -> str:
    """流式计算文件 SHA-256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def new_doc_id() -> str:
    return str(uuid.uuid4())


# ---------- 查询 ----------

def get_doc(rel_path: str) -> dict | None:
    """按路径取逻辑文档 (doc_id 统一转 str, 避免 uuid.UUID 进入 JSONB)。"""
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT doc_id, rel_path, file_name, latest_version FROM doc_registry WHERE rel_path = :p"),
            {"p": rel_path},
        ).mappings().first()
    if not row:
        return None
    d = dict(row)
    d["doc_id"] = str(d["doc_id"])
    return d


def find_by_sha(sha256: str) -> list[dict]:
    """按内容哈希查找已有版本（用于内容级去重）。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """SELECT r.rel_path, r.file_name, v.version, v.is_active
                   FROM doc_version v JOIN doc_registry r ON v.doc_id = r.doc_id
                   WHERE v.sha256 = :s ORDER BY r.rel_path, v.version"""
            ),
            {"s": sha256},
        ).mappings().all()
    return [dict(r) for r in rows]


def list_documents() -> list[dict]:
    """全部文档及其版本摘要。"""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """SELECT r.rel_path, r.file_name, r.latest_version,
                          v.version, v.chunk_count, v.is_active, v.ingested_at, v.sha256
                   FROM doc_registry r
                   LEFT JOIN doc_version v ON v.doc_id = r.doc_id
                   ORDER BY r.rel_path, v.version"""
            )
        ).mappings().all()
    return [dict(r) for r in rows]


def resolve_doc(name: str) -> dict | None:
    """按完整路径或文件名（唯一时）解析文档。"""
    doc = get_doc(name)
    if doc:
        return doc
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT doc_id, rel_path, file_name, latest_version FROM doc_registry WHERE file_name = :n"),
            {"n": name},
        ).mappings().all()
    if len(rows) == 1:
        d = dict(rows[0])
        d["doc_id"] = str(d["doc_id"])
        return d
    if len(rows) > 1:
        raise SystemExit(f"文件名 '{name}' 匹配到多个文档, 请用完整相对路径:\n  " + "\n  ".join(r["rel_path"] for r in rows))
    return None


# ---------- 写入 ----------

def _mark_vectors(conn, doc_id: str, active_version: int | None) -> None:
    """把某文档全部向量置为 inactive, 再激活指定版本。"""
    doc_id = str(doc_id)
    conn.execute(
        text(
            """UPDATE langchain_pg_embedding
               SET cmetadata = jsonb_set(cmetadata, '{active}', 'false'::jsonb)
               WHERE cmetadata->>'doc_id' = :d"""
        ),
        {"d": doc_id},
    )
    if active_version is not None:
        conn.execute(
            text(
                """UPDATE langchain_pg_embedding
                   SET cmetadata = jsonb_set(cmetadata, '{active}', 'true'::jsonb)
                   WHERE cmetadata->>'doc_id' = :d AND cmetadata->>'version' = :v"""
            ),
            {"d": doc_id, "v": str(active_version)},
        )


def register_version(
    rel_path: str,
    file_name: str,
    sha256: str,
    size_bytes: int,
    chunk_count: int,
    doc_id: str | None = None,
    overwrite: bool = False,
) -> tuple[str, int]:
    """登记一个新文档 (v1) 并使其生效; overwrite=True 时先清除该路径的全部历史。

    doc_id 由调用方预生成 (向量元数据需先于入库携带 doc_id)。
    """
    doc_id = doc_id or str(uuid.uuid4())
    with get_engine().begin() as conn:
        if overwrite:
            conn.execute(
                text("DELETE FROM langchain_pg_embedding WHERE cmetadata->>'doc_id' = :d"),
                {"d": _doc_id_of(conn, rel_path)},
            )
            conn.execute(text("DELETE FROM doc_registry WHERE rel_path = :p"), {"p": rel_path})
        conn.execute(
            text("INSERT INTO doc_registry (doc_id, rel_path, file_name) VALUES (:i, :p, :n)"),
            {"i": doc_id, "p": rel_path, "n": file_name},
        )
        version = conn.execute(
            text("INSERT INTO doc_version (doc_id, version, sha256, size_bytes, chunk_count, is_active) "
                 "VALUES (:d, 1, :s, :z, :c, TRUE) RETURNING version"),
            {"d": doc_id, "s": sha256, "z": size_bytes, "c": chunk_count},
        ).scalar_one()
    return doc_id, int(version)


def _doc_id_of(conn, rel_path: str) -> str:
    return conn.execute(
        text("SELECT doc_id FROM doc_registry WHERE rel_path = :p"), {"p": rel_path}
    ).scalar_one()


def next_version(doc_id: str) -> int:
    """查询下一个可用版本号 (入库前写入向量元数据用)。"""
    with get_engine().connect() as conn:
        return int(conn.execute(
            text("SELECT COALESCE(MAX(version), 0) + 1 FROM doc_version WHERE doc_id = :d"),
            {"d": doc_id},
        ).scalar_one())


def add_version(doc_id: str, version: int, sha256: str, size_bytes: int, chunk_count: int) -> int:
    """为已有文档追加指定版本号的版本并激活 (旧版本向量保留, 仅置为 inactive)。"""
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """INSERT INTO doc_version (doc_id, version, sha256, size_bytes, chunk_count, is_active)
                   VALUES (:d, :v, :s, :z, :c, TRUE)"""
            ),
            {"d": doc_id, "v": version, "s": sha256, "z": size_bytes, "c": chunk_count},
        )
        conn.execute(
            text("UPDATE doc_registry SET latest_version = :v WHERE doc_id = :d"),
            {"v": version, "d": doc_id},
        )
        conn.execute(
            text("UPDATE doc_version SET is_active = FALSE WHERE doc_id = :d AND version <> :v"),
            {"d": doc_id, "v": version},
        )
        _mark_vectors(conn, doc_id, version)
    return version


def use_version(doc_id: str, version: int) -> None:
    """切换生效版本 (向量不动, 只改标记)。"""
    with get_engine().begin() as conn:
        n = conn.execute(
            text("SELECT COUNT(*) FROM doc_version WHERE doc_id = :d AND version = :v"),
            {"d": doc_id, "v": version},
        ).scalar_one()
        if not n:
            raise SystemExit(f"版本 v{version} 不存在")
        conn.execute(
            text("UPDATE doc_version SET is_active = FALSE WHERE doc_id = :d"), {"d": doc_id}
        )
        conn.execute(
            text("UPDATE doc_version SET is_active = TRUE WHERE doc_id = :d AND version = :v"),
            {"d": doc_id, "v": version},
        )
        _mark_vectors(conn, doc_id, version)


def delete_document(doc_id: str, version: int | None = None) -> int:
    """删除整个文档或单个版本 (含向量)。返回删除的向量数。"""
    with get_engine().begin() as conn:
        if version is None:
            cond = "cmetadata->>'doc_id' = :d"
            params: dict[str, Any] = {"d": doc_id}
        else:
            cond = "cmetadata->>'doc_id' = :d AND cmetadata->>'version' = :v"
            params = {"d": doc_id, "v": str(version)}
        deleted = conn.execute(
            text(f"DELETE FROM langchain_pg_embedding WHERE {cond} RETURNING id"), params
        ).rowcount or 0
        if version is None:
            conn.execute(text("DELETE FROM doc_registry WHERE doc_id = :d"), {"d": doc_id})
        else:
            conn.execute(
                text("DELETE FROM doc_version WHERE doc_id = :d AND version = :v"),
                {"d": doc_id, "v": version},
            )
            remaining = conn.execute(
                text("SELECT COUNT(*) FROM doc_version WHERE doc_id = :d"), {"d": doc_id}
            ).scalar_one()
            if not remaining:  # 版本删光后移除文档登记
                conn.execute(text("DELETE FROM doc_registry WHERE doc_id = :d"), {"d": doc_id})
    return int(deleted)


def clear_all() -> None:
    """清空注册表 (配合向量表 TRUNCATE 使用)。"""
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM doc_version"))
        conn.execute(text("DELETE FROM doc_registry"))
