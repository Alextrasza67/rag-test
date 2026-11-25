"""命令行问答入口。

用法:
    uv run python -m app.cli "RAG 项目的 embedding 模型是什么"
"""
from __future__ import annotations

import argparse

from app.graph import ask


def main() -> None:
    parser = argparse.ArgumentParser(description="本地 RAG 知识库问答")
    parser.add_argument("question", help="要问的问题")
    args = parser.parse_args()

    result = ask(args.question)
    print("\n=== 答案 ===")
    print(result["answer"])
    if result["sources"]:
        print("\n=== 来源 ===")
        for src in result["sources"]:
            print(f"- {src}")


if __name__ == "__main__":
    main()
