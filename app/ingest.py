"""文档入库：支持指定文件/目录、SHA-256 去重、同名冲突时覆盖或新建版本。

用法:
    uv run python -m app.ingest                       # 默认入库 data/ 全部
    uv run python -m app.ingest path1 path2 ...       # 指定文件或目录(可多个)
    uv run python -m app.ingest --reset               # 清空向量库与注册表后重建
    uv run python -m app.ingest -o report.pdf         # 冲突时全部覆盖
    uv run python -m app.ingest -n report.pdf         # 冲突时全部新建版本

冲突处理 (同名文件内容变化时):
    覆盖(overwrite)  清除该文件全部历史版本, 以新内容作为 v1
    新版本(new)      保留历史版本向量(置为 inactive), 新内容作为 vN+1 并生效
    跳过(skip)       不入库 (默认: 非交互环境自动跳过)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import create_engine, text

from app import registry
from app.config import get_settings
from app.vectorstore import get_vectorstore

LOADERS = {
    ".md": TextLoader,
    ".txt": TextLoader,
    ".pdf": PyPDFLoader,
}
BATCH_SIZE = 32


def load_file(path: Path, docs_dir: Path):
    """加载单个文件为文档单元列表。"""
    loader_cls = LOADERS.get(path.suffix.lower())
    if loader_cls is None:
        print(f"  跳过不支持的类型: {path.name}")
        return None
    kwargs = {"encoding": "utf-8"} if loader_cls is TextLoader else {}
    docs = loader_cls(str(path), **kwargs).load()
    rel = path.relative_to(docs_dir).as_posix() if docs_dir in path.parents or path.parent == docs_dir else str(path)
    for d in docs:
        d.metadata["rel_path"] = rel
    return docs, rel


def collect_targets(targets: list[str], docs_dir: Path) -> list[Path]:
    """展开目标为文件列表; 无参数时取 docs_dir 全部。"""
    if not targets:
        return sorted(p for p in docs_dir.rglob("*") if p.is_file() and not p.name.startswith("."))
    files: list[Path] = []
    for t in targets:
        p = Path(t).expanduser().resolve()
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.is_file() and not f.name.startswith(".")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"  路径不存在, 跳过: {t}")
    return files


def ask_conflict(rel: str, mode_flags: dict) -> str:
    """同名文件内容变化时询问用户: overwrite / new / skip。"""
    if mode_flags["overwrite"]:
        return "overwrite"
    if mode_flags["new_version"]:
        return "new"
    if not sys.stdin.isatty():
        print("  (非交互环境, 默认跳过; 可用 -o 覆盖 或 -n 新版本)")
        return "skip"
    while True:
        ans = input(f"  请选择 [c]覆盖 / [n]新版本 / [s]跳过: ").strip().lower()
        if ans in ("c", "overwrite", "覆盖"):
            return "overwrite"
        if ans in ("n", "new", "新版本"):
            return "new"
        if ans in ("s", "skip", "跳过", ""):
            return "skip"
        print("  无效输入, 请输入 c / n / s")


def process_file(path: Path, docs_dir: Path, splitter, mode_flags: dict) -> None:
    name = path.name
    loaded = load_file(path, docs_dir)
    if loaded is None:
        return
    docs, rel = loaded
    sha = registry.sha256_of(path)
    size = path.stat().st_size

    print(f"\n▶ {rel}  (sha256: {sha[:12]}..., {size} bytes)")

    # ---- 1) 内容级去重: 相同内容已在库中? ----
    same = registry.find_by_sha(sha)
    if same:
        for s in same:
            if s["rel_path"] == rel and s["is_active"]:
                print(f"  ⏭ 内容未变化且已生效 (v{s['version']}), 跳过")
                return
        print("  ⚠ 相同内容已存在于:")
        for s in same:
            print(f"     - {s['rel_path']} v{s['version']} {'[生效]' if s['is_active'] else '[历史]'}")
        if same[0]["rel_path"] == rel:
            # 同一文件的历史版本, 直接重新激活
            doc = registry.get_doc(rel)
            assert doc is not None
            registry.use_version(doc["doc_id"], int(same[0]["version"]))
            print(f"  ✅ 已重新激活 v{same[0]['version']}")
            return
        if not sys.stdin.isatty() or not mode_flags["interactive"]:
            print("  (默认跳过; 如需多份入库请手动处理)")
            return
        ans = input("  仍要作为新文档重复入库? [y/N]: ").strip().lower()
        if ans != "y":
            print("  跳过")
            return

    # ---- 2) 路径级判断: 新文档 or 冲突 ----
    doc = registry.get_doc(rel)
    chunks = splitter.split_documents(docs)
    print(f"  切成 {len(chunks)} 个片段")

    if doc is None:
        doc_id = registry.new_doc_id()
        version = 1
        action = "新文档"
    else:
        action = ask_conflict(rel, mode_flags)
        if action == "skip":
            print("  跳过")
            return
        if action == "overwrite":
            # 清除全部历史 (向量+登记), 当作全新文档
            registry.delete_document(doc["doc_id"])
            doc_id = registry.new_doc_id()
            version = 1
            print(f"  🗑 已清除 {rel} 的全部历史版本")
        else:  # new
            doc_id = doc["doc_id"]
            version = registry.next_version(doc_id)
            print(f"  保留历史版本, 新内容将作为 v{version}")

    # ---- 3) 向量携带血缘元数据后入库 ----
    for c in chunks:
        c.metadata["doc_id"] = doc_id
        c.metadata["version"] = str(version)
        c.metadata["active"] = True  # JSON 布尔, 与 use_version 的 jsonb_set 一致
        c.metadata["file_name"] = name

    store = get_vectorstore()
    total = 0
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        total += len(store.add_documents(batch))
        print(f"  向量入库: {total}/{len(chunks)}")

    # ---- 4) 登记注册表 (新版本场景会自动把旧版本向量置为 inactive) ----
    if doc is None or action == "overwrite":
        registry.register_version(rel, name, sha, size, len(chunks), doc_id=doc_id)
    else:
        registry.add_version(doc_id, version, sha, size, len(chunks))
    print(f"  ✅ 完成: {name} v{version} ({total} 个片段)")


def reset_all() -> None:
    s = get_settings()
    engine = create_engine(s.pg_url)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE langchain_pg_embedding, langchain_pg_collection"))
        conn.execute(text("DROP TABLE IF EXISTS doc_version, doc_registry CASCADE"))
    print("已清空向量表与文档注册表")


def main() -> None:
    parser = argparse.ArgumentParser(description="文档入库 (带去重与版本管理)")
    parser.add_argument("targets", nargs="*", help="要入库的文件或目录; 缺省为 data/ 全部")
    parser.add_argument("--reset", action="store_true", help="清空向量库与注册表后重建")
    parser.add_argument("-o", "--overwrite", action="store_true", help="冲突时全部覆盖(不询问)")
    parser.add_argument("-n", "--new-version", action="store_true", help="冲突时全部新建版本(不询问)")
    args = parser.parse_args()

    s = get_settings()
    if args.reset:
        reset_all()
    registry.ensure_schema()

    files = collect_targets(args.targets, s.docs_dir)
    if not files:
        print("没有找到可入库的文件 (.md/.txt/.pdf)")
        sys.exit(1)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""],
    )
    mode_flags = {
        "overwrite": args.overwrite,
        "new_version": args.new_version,
        "interactive": not (args.overwrite or args.new_version),
    }
    for f in files:
        process_file(f, s.docs_dir, splitter, mode_flags)

    print("\n完成。查看知识库清单: uv run python -m app.docs list")


if __name__ == "__main__":
    main()
