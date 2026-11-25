"""模型工厂：embedding 本地 Ollama + 对话 DeepSeek 官方 API。"""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from app.config import get_settings

# embedding 模型驻留时间(秒)：避免每次请求重新加载进内存
KEEP_ALIVE = 1800


@lru_cache
def get_embeddings() -> OllamaEmbeddings:
    """qwen3-embedding 走 Ollama 本地服务。"""
    s = get_settings()
    return OllamaEmbeddings(
        model=s.embedding_model,
        base_url=s.ollama_base_url,
        keep_alive=KEEP_ALIVE,
    )


@lru_cache
def get_chat_model():
    """对话/生成模型：DeepSeek 官方 API（OpenAI 兼容协议）。

    API Key 从系统环境变量读取:
        export RAG_DEEPSEEK_API_KEY=sk-xxx   # 官方控制台申请

    其他对话参数在 .env 中配置:
        CHAT_MODEL=deepseek-chat             # flash 档; 深度思考可用 deepseek-reasoner
    """
    s = get_settings()
    api_key = os.getenv("RAG_DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "未配置 RAG_DEEPSEEK_API_KEY: 请先设置系统环境变量 "
            "export RAG_DEEPSEEK_API_KEY=sk-xxx (DeepSeek 官方 API Key)"
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=s.chat_model,
        api_key=api_key,
        base_url=s.deepseek_base_url,
        temperature=0.1,
        timeout=60,
    )
