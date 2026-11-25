"""RAG 主流程（LangGraph）：retrieve -> generate。"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph

from app.models import get_chat_model
from app.retriever import get_retriever

SYSTEM_PROMPT = """你是严谨的中文知识库问答助手。仅依据给定的参考资料回答问题。
规则:
1. 答案必须来自参考资料, 不得编造。
2. 引用资料时在句末标注 [序号], 序号对应参考资料编号。
3. 资料不足以回答时, 直接说明"知识库中没有足够的信息"。"""

GENERATE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "参考资料:\n{context}\n\n问题: {question}"),
    ]
)


class RAGState(TypedDict):
    question: str
    context: list[Document]
    answer: str


def _format_docs(docs: list[Document]) -> str:
    parts: list[str] = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        source = meta.get("source", "unknown")
        page = meta.get("page")
        loc = f" 第{page + 1}页" if isinstance(page, int) else ""
        parts.append(f"[{i}] ({source}{loc})\n{doc.page_content}")
    return "\n\n".join(parts)


def _retrieve(state: RAGState) -> dict:
    docs = get_retriever().invoke(state["question"])
    return {"context": docs}


def _generate(state: RAGState) -> dict:
    chain = GENERATE_PROMPT | get_chat_model() | StrOutputParser()
    answer = chain.invoke(
        {"context": _format_docs(state["context"]), "question": state["question"]}
    )
    return {"answer": answer}


def build_graph():
    g = StateGraph(RAGState)
    g.add_node("retrieve", _retrieve)
    g.add_node("generate", _generate)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
    return g.compile()


_app = None


def get_rag_app():
    global _app
    if _app is None:
        _app = build_graph()
    return _app


def ask(question: str) -> dict:
    """执行一次 RAG 问答，返回答案与来源。"""
    result = get_rag_app().invoke({"question": question})
    sources = sorted({str(d.metadata.get("source", "unknown")) for d in result["context"]})
    return {"question": question, "answer": result["answer"], "sources": sources}
