"""知识库文档管理命令。

用法:
    uv run python -m app.docs list                 # 全部文档与版本
    uv run python -m app.docs history <文件>       # 单个文件的版本历史
    uv run python -m app.docs use <文件> <版本号>  # 切换生效版本
    uv run python -m app.docs rm <文件> [--version N] [-y]  # 删除文件或某版本
"""
from __future__ import annotations

import argparse
import sys

from app import registry


def _fmt_time(ts) -> str:
    return ts.strftime("%m-%d %H:%M") if ts else "-"


def cmd_list() -> None:
    rows = registry.list_documents()
    if not rows:
        print("知识库为空 (可用 uv run python -m app.ingest 入库)")
        return
    print(f"{'文档':<34} {'版本':<6} {'状态':<6} {'片段':<6} {'入库时间':<14} sha256")
    print("-" * 92)
    cur = None
    for r in rows:
        if r["rel_path"] != cur:
            cur = r["rel_path"]
            print(f"{r['file_name']:<34}", end="")
        else:
            print(f"{'':<34}", end="")
        active = "✅生效" if r["is_active"] else "历史"
        print(
            f" v{r['version']:<5} {active:<6} {r['chunk_count']:<6} "
            f"{_fmt_time(r['ingested_at']):<14} {r['sha256'][:12]}..."
        )


def cmd_history(name: str) -> None:
    doc = registry.resolve_doc(name)
    if not doc:
        print(f"未找到文档: {name}")
        sys.exit(1)
    rows = [r for r in registry.list_documents() if r["rel_path"] == doc["rel_path"]]
    print(f"{doc['rel_path']}  (共 {len(rows)} 个版本)")
    for r in rows:
        mark = " ← 生效" if r["is_active"] else ""
        print(
            f"  v{r['version']}  {r['chunk_count']} 片段  "
            f"{_fmt_time(r['ingested_at'])}  sha256:{r['sha256'][:12]}...{mark}"
        )


def cmd_use(name: str, version: int) -> None:
    doc = registry.resolve_doc(name)
    if not doc:
        print(f"未找到文档: {name}")
        sys.exit(1)
    registry.use_version(doc["doc_id"], version)
    print(f"✅ {doc['rel_path']} 已切换到 v{version} (历史版本向量保留但不再参与检索)")


def cmd_rm(name: str, version: int | None, assume_yes: bool) -> None:
    doc = registry.resolve_doc(name)
    if not doc:
        print(f"未找到文档: {name}")
        sys.exit(1)
    if version is None:
        rows = [r for r in registry.list_documents() if r["rel_path"] == doc["rel_path"]]
        print(f"将删除 {doc['rel_path']} 的全部 {len(rows)} 个版本及其向量")
    else:
        print(f"将删除 {doc['rel_path']} 的 v{version}")
    if not assume_yes:
        ans = input("确认? [y/N]: ").strip().lower()
        if ans != "y":
            print("已取消")
            return
    n = registry.delete_document(doc["doc_id"], version)
    print(f"✅ 已删除 {n} 个向量片段")
    if version is None:
        print("文档登记已移除")
    else:
        left = [r for r in registry.list_documents() if r["rel_path"] == doc["rel_path"]]
        if left and not any(r["is_active"] for r in left):
            names = ", ".join(f"v{r['version']}" for r in left)
            print(f"⚠ 生效版本已删除, 剩余版本: {names}")
            print(f"  可用 uv run python -m app.docs use {name} <版本号> 重新指定生效版本")


def main() -> None:
    parser = argparse.ArgumentParser(description="知识库文档管理")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="全部文档与版本")
    p_h = sub.add_parser("history", help="单个文件的版本历史")
    p_h.add_argument("file")
    p_u = sub.add_parser("use", help="切换生效版本")
    p_u.add_argument("file")
    p_u.add_argument("version", type=int)
    p_r = sub.add_parser("rm", help="删除文件或某版本")
    p_r.add_argument("file")
    p_r.add_argument("--version", type=int, default=None)
    p_r.add_argument("-y", action="store_true", help="跳过确认")
    args = parser.parse_args()

    registry.ensure_schema()
    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "history":
        cmd_history(args.file)
    elif args.cmd == "use":
        cmd_use(args.file, args.version)
    elif args.cmd == "rm":
        cmd_rm(args.file, args.version, args.y)


if __name__ == "__main__":
    main()
