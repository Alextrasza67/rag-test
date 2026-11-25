# rag-test — 本地 RAG Agent

LangChain/LangGraph + PostgreSQL(pgvector) + Ollama(qwen3-embedding) 的本地知识库问答。

## 架构

```
data/ 文档 → 切块 → qwen3-embedding:4b (Ollama 本地, 2560维)
                         ↓
              pgvector (PostgreSQL 16, Docker)
                         ↓
   用户提问 → MMR 检索 top-4 → DeepSeek 官方 API (deepseek-chat, flash)
                               生成带引用的答案
```

> 模型组合说明：M2 Pro 16GB 的 GPU 内存上限约 10.7GB，本地 9b 对话模型（8.6GB）
> 与 4b embedding（2.5GB）无法同时驻留、会互相驱逐。因此生成侧改为 DeepSeek
> 官方 API（Key 从系统环境变量 `RAG_DEEPSEEK_API_KEY` 读取），本地只驻留 embedding 模型。

## 环境要求

- macOS (Apple Silicon), Ollama 运行中: `qwen3-embedding:4b` + 一个对话模型
- Docker Desktop（拉取 `pgvector/pgvector:pg16` 镜像）

## 快速开始

```bash
# 0. 配置 DeepSeek API Key（系统环境变量，写入 ~/.zshrc 可持久化）
export RAG_DEEPSEEK_API_KEY=sk-xxx

# 1. 环境变量
cp .env.example .env   # 按需修改模型/密码

# 2. 启动数据库（数据持久化在 /Users/alex/Documents/DockerVolumes/rag-test-pg）
docker compose up -d

# 3. 安装依赖
uv sync

# 4. 文档入库（默认读取 data/ 下 .md/.txt/.pdf）
uv run python -m app.ingest

# 5. 命令行问答
uv run python -m app.cli "RAG 项目的 embedding 模型是什么"

# 6. HTTP API
uv run uvicorn app.server:app --reload --port 8000
curl -s localhost:8000/ask -H 'Content-Type: application/json' \
     -d '{"question": "向量存在哪里"}'
```

## 配置说明（.env）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `EMBEDDING_MODEL` | Ollama embedding 模型 | `qwen3-embedding:4b` |
| `RAG_DEEPSEEK_API_KEY` | DeepSeek API Key，**系统环境变量**（`export` 后使用） | 无 |
| `CHAT_MODEL` | 对话模型（flash 档 `deepseek-chat`；深度推理 `deepseek-reasoner`） | `deepseek-chat` |
| `PG_URL` | 数据库连接（必须用 `+psycopg`） | 本地 5432 |
| `TABLE_NAME` | 向量表名，**按 embedding 模型命名**，换模型即换表 | `docs_qwen3_embedding_4b` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块大小/重叠 | 800 / 120 |
| `TOP_K` | 召回片段数 | 4 |

## 常用运维

```bash
# 看库里有多少片段
docker exec rag-test-pg psql -U rag -d ragdb -c \
  "SELECT c.name AS collection, COUNT(e.id) AS chunks \
   FROM langchain_pg_embedding e \
   JOIN langchain_pg_collection c ON e.collection_id = c.uuid GROUP BY 1;"

# 清空重建（等价于 uv run python -m app.ingest --reset）
docker exec rag-test-pg psql -U rag -d ragdb -c \
  "TRUNCATE langchain_pg_embedding, langchain_pg_collection;"
```

## 添加数据

```bash
uv run python -m app.ingest [文件或目录...]   # 不带参数默认入库 data/ 全部
```

- 支持同时指定多个文件/目录，类型：`.md` / `.txt` / `.pdf`
- **SHA-256 去重**：内容未变化且已生效的文件自动跳过
- **同名冲突**（文件内容变化时）三选一：
  - `[c]` 覆盖：清除该文件全部历史版本，新内容作为 v1
  - `[n]` 新版本：历史版本向量保留但失活，新内容作为 vN+1 并生效
  - `[s]` 跳过
  - 可用 `-o` / `-n` 参数跳过询问；非交互环境默认跳过
- `--reset`：清空向量表与注册表后全量重建

### 版本管理

```bash
uv run python -m app.docs list                 # 全部文档与版本状态
uv run python -m app.docs history sample.md    # 单个文件的历史
uv run python -m app.docs use sample.md 1      # 切换生效版本
uv run python -m app.docs rm sample.md         # 删除文件(全部版本)
uv run python -m app.docs rm sample.md --version 1 -y   # 只删某版本
```

- 每个文档可以有多个版本，**同一时刻只有一个版本生效**
- 检索只返回「生效版本」的片段；切换版本即时生效，无需重建索引
- 历史版本向量保留在库中，可随时切回；引用会显示来源文件与版本（如 `faq.md v1`）

### 数据血缘（doc_registry）

向量片段通过元数据 `doc_id/version/active` 关联两张注册表：

- `doc_registry`：逻辑文档（rel_path 唯一）
- `doc_version`：物理版本（sha256、片段数、是否生效、入库时间）

删除版本/文件、覆盖、去重判断都以注册表为准，保证向量与登记一致。



## 常见问题

- **pull 镜像超时**：Docker Desktop 需跟随系统代理（Settings → Resources → Proxies → System），改完重启 Docker Desktop。
- **换 embedding 模型**：必须换 `TABLE_NAME` 并重新入库——不同模型维度不同（4b=2560, 8b=4096），且向量空间不通用。
- **SQLAlchemy 方言报错**：`PG_URL` 必须写 `postgresql+psycopg://`（psycopg3），不能省略 driver。
