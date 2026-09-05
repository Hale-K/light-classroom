# 架构

轻课堂是 **FastAPI 模块化单体 + React 管理端**，不是 Spring Cloud 微服务。学校之间用租户（`tenant.code`）隔离，请求头 `X-School-Code` 决定当前学校。

```
浏览器
  ├─ 学校端  /login
  └─ 平台超管 /admin/login
        │
        ▼
  静态资源（frontend-react/dist）
        │  /api/v1
        ▼
  FastAPI（JWT + 多租户 + RBAC）
        │
        ├─ PostgreSQL     业务数据
        ├─ Redis          缓存 / Celery 结果
        ├─ RabbitMQ       Celery 队列 scheduling、academic
        ├─ MinIO / COS    文件中心
        ├─ Celery Worker  排课 CP-SAT（分钟级 CPU）
        └─ 可选 Prometheus  刮取 /metrics
```

排课生成入队任务 `scheduling.generate`：白天约 150s、晚课约 100s，最多换 5 组随机种子。反代不要 60 秒掐断，SSE 不要缓冲。

开发时前端 Vite 默认 `5176`，把 `/api/v1` 代理到 `127.0.0.1:8001`；`backend/docker-compose.yml` 里 API 常映射 `8000`，端口不一致时设 `VITE_DEV_PROXY`。

学校端右下角「轻课堂助手」按 Agentic RAG 工作：按需取说明书或查本校 API，不检索源码。见 [教务助手](assistant-agent.md)。
