"""FastAPI 服务: POST /ask。

启动:
    uv run uvicorn app.server:app --reload --port 8000
调用:
    curl -s localhost:8000/ask -H 'Content-Type: application/json' \
         -d '{"question": "RAG 项目的 embedding 模型是什么"}'
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.graph import ask as rag_ask

app = FastAPI(title="rag-test", version="0.1.0")


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    question: str
    answer: str
    sources: list[str]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    return AskResponse(**rag_ask(req.question))
