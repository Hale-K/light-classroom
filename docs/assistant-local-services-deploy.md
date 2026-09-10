# 教务助手本地模型与基础服务部署

本文说明在 Docker Desktop 和本机 Ollama 上启动教务助手依赖的推荐方式。

## 组件职责

```text
light-classroom backend
   ├─ PostgreSQL + pgvector：保存意图样例和向量
   ├─ Redis：缓存、队列和运行状态
   ├─ BGE embedding：把中文文本转换为向量
   └─ Ollama：提供 qwen3:8b 等对话模型
```

## Ollama 是否必须

如果要使用本地 `qwen3:8b` 作为对话模型，Ollama 是必须的。它负责生成回答、规划工具调用和执行 Agent Loop。

Ollama **不负责** PostgreSQL 的向量检索。BGE embedding 和 pgvector 是另一条链路：

```text
用户问题 → BGE embedding → pgvector 相似度检索 → 意图/Harness 路由
用户问题 → Ollama qwen3:8b → 回答或工具调用
```

## 启动 Ollama

确认模型已存在：

```powershell
ollama list
```

没有模型时下载：

```powershell
ollama pull qwen3:8b
```

启动服务（Ollama 通常会作为桌面服务运行）：

```powershell
ollama serve
```

默认地址为 `http://127.0.0.1:11434`。在服务商配置中填写：

```text
类型：Ollama（本地）
Base URL：http://127.0.0.1:11434
模型：qwen3:8b
```

## Docker Desktop 基础服务

PostgreSQL、pgvector 和 Redis 建议由 Docker Desktop 常驻运行。启动后先确认容器健康，再启动 backend：

```powershell
docker compose up -d postgres redis
docker compose ps
```

数据库必须启用 `vector` 扩展。应用启动时会执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## BGE embedding 当前实现

当前 backend 使用 `sentence-transformers` 在进程内加载本地 BGE 模型，模型路径由配置项控制：

```text
ASSISTANT_EMBEDDING_MODEL_PATH=E:\llm-models\embedding\bge-base-zh-v1.5
```

模型是懒加载的：第一次进行意图识别时加载，之后在进程内复用。Docker Desktop 启动 PostgreSQL 或 Redis **不会自动启动 BGE**。

如果以后要让 BGE 像 Redis 一样独立常驻，需要增加一个 embedding HTTP 服务，并把 backend 的 embedding provider 改为远程 provider；这属于后续改造，当前部署不应把 BGE 地址误填成 Ollama 地址。

## 启动和检查顺序

1. 启动 Docker Desktop。
2. 启动 PostgreSQL/pgvector 和 Redis 容器。
3. 确认 Ollama 正在运行，并能执行 `ollama run qwen3:8b`。
4. 配置 BGE 本地目录 `E:\llm-models\embedding\bge-base-zh-v1.5`。
5. 启动 backend 和 frontend。
6. 在服务商管理页测试 Ollama 连接，并将其设为默认模型。
7. 首次发送助手请求后检查 backend 日志，确认 BGE 已成功加载、pgvector 查询没有报错。

## 常见误区

- Ollama 只提供对话模型，不等于 pgvector。
- `qwen3:8b` 不能替代 BGE embedding 模型。
- BGE 目录不存在时，意图识别会回退；这不会自动修复模型路径。
- 多个 backend worker 会各自加载一份进程内 BGE 模型，需要预留足够内存。
