"""集中配置：从 .env 读取，所有模块统一从这里拿参数。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@lru_cache
def get_settings() -> "Settings":
    return Settings()


class Settings:
    """RAG 应用配置。"""

    def __init__(self) -> None:
        self.ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.embedding_model: str = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:4b")

        self.chat_model: str = os.getenv("CHAT_MODEL", "deepseek-chat")
        self.deepseek_base_url: str = os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
        )

        self.pg_url: str = os.getenv(
            "PG_URL",
            "postgresql+psycopg://rag:rag123456@localhost:5432/ragdb",
        )
        self.table_name: str = os.getenv("TABLE_NAME", "docs_qwen3_embedding_4b")

        self.docs_dir: Path = PROJECT_ROOT / os.getenv("DOCS_DIR", "data")
        self.chunk_size: int = int(os.getenv("CHUNK_SIZE", "800"))
        self.chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "120"))
        self.top_k: int = int(os.getenv("TOP_K", "4"))

    @property
    def collection_name(self) -> str:
        """langchain-postgres 用 collection 做逻辑隔离，直接复用表名。"""
        return self.table_name
