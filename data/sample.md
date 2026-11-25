# RAG 测试知识库示例文档

## 项目简介

这是一个本地 RAG（Retrieval-Augmented Generation，检索增强生成）测试项目。
技术栈：LangChain/LangGraph + PostgreSQL(pgvector) + Ollama(qwen3-embedding)。

## 关键配置

- 向量数据库：pgvector（PostgreSQL 16 扩展），数据持久化在
  `/Users/alex/Documents/DockerVolumes/rag-test-pg`。
- Embedding 模型：qwen3-embedding:4b，通过 Ollama 在本机运行，
  输出向量维度为 2560，支持指令感知（instruction-aware）检索。
- 对话模型：qwen3.5:9b（本地 Ollama）。

## 常用命令

1. 启动数据库：`docker compose up -d`
2. 安装依赖：`uv sync`
3. 文档入库：`uv run python -m app.ingest [文件或目录...]`
   - `--reset` 清空后全量重建；`-o` 冲突时覆盖；`-n` 冲突时新建版本
4. 知识库管理：`uv run python -m app.docs list|history|use|rm`
5. 命令行问答：`uv run python -m app.cli "你的问题"`
6. 启动 API：`uv run uvicorn app.server:app --reload --port 8000`

## 检索约定

- 分块大小 800 字符，重叠 120 字符。
- 默认召回 top_k = 4 个片段。
- 检索使用 MMR（最大边际相关）以兼顾相关性与多样性。

## 版本管理说明

知识库支持同一文件多版本: 覆盖入库会清除历史, 新版本入库保留历史并可随时切换。
当前生效版本永远只有 一个, 检索只返回生效版本的片段。

## 运维备忘

容器名 rag-test-pg, 数据目录 /Users/alex/Documents/DockerVolumes/rag-test-pg。
