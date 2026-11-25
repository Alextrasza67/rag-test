"""文档入库：读取 data/ 下的 .md/.txt/.pdf，切块后写入 pgvector。

用法:
    uv run python -m app.ingest            # 增量追加 data/ 下所有文档
    uv run python -m app.ingest --reset    # 先清空向量库，再全量重建
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.vectorstore import get_vectorstore

LOADERS = {
    ".md": TextLoader,
    ".txt": TextLoader,
    ".pdf": PyPDFLoader,
}

# 每批写入的片段数，避免超大文档一次请求过长
BATCH_SIZE = 32


def load_documents(docs_dir: Path):
    docs = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        loader_cls = LOADERS.get(path.suffix.lower())
        if loader_cls is None:
            print(f"跳过不支持的文件: {path.name}")
            continue
        kwargs = {"encoding": "utf-8"} if loader_cls is TextLoader else {}
        file_docs = loader_cls(str(path), **kwargs).load()
        rel = path.relative_to(docs_dir)
        print(f"读取 {rel} -> {len(file_docs)} 个文档单元")
        docs.extend(file_docs)
    return docs


def reset_tables() -> None:
    """清空 langchain_pg_* 向量表。"""
    from sqlalchemy import create_engine, text

    s = get_settings()
    engine = create_engine(s.pg_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE langchain_pg_embedding, langchain_pg_collection"))
        print("已清空向量表")
    except Exception as e:  # 表还不存在等情况
        print(f"清空跳过 ({e.__class__.__name__}: 表可能尚未创建)")


def main() -> None:
    parser = argparse.ArgumentParser(description="文档入库到 pgvector")
    parser.add_argument("--reset", action="store_true", help="清空现有向量后全量重建")
    args = parser.parse_args()

    s = get_settings()
    if not s.docs_dir.exists():
        print(f"文档目录不存在: {s.docs_dir}")
        sys.exit(1)

    docs = load_documents(s.docs_dir)
    if not docs:
        print("没有找到可入库的文档 (.md/.txt/.pdf)")
        sys.exit(1)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    print(f"共 {len(docs)} 个文档单元, 切成 {len(chunks)} 个片段")

    if args.reset:
        reset_tables()

    store = get_vectorstore()
    total = 0
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        ids = store.add_documents(batch)
        total += len(ids)
        print(f"  入库进度: {total}/{len(chunks)}")

    print(f"✅ 本次写入 {total} 个片段 (表: {s.table_name})")
    print("提示: 不带 --reset 时为追加写入, 重复入库同一文件会产生重复片段")


if __name__ == "__main__":
    main()
