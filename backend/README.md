# 轻课堂后端

FastAPI 模块化单体：教务 API、排课求解、Celery 异步任务。

生产发布、密钥、迁移、回滚见仓库根目录 **[docs/deploy.md](../docs/deploy.md)**。下文只覆盖本机开发。

## 技术栈

FastAPI · SQLModel / SQLAlchemy · PostgreSQL · Redis · RabbitMQ（Celery）· MinIO / COS · （可选）Kafka

排课白天/晚课使用 OR-Tools CP-SAT（`ortools`，请自行装进环境；尚未写入 `pyproject.toml`）。

## 目录

```
backend/
├── app/                 # 入口、路由、模型、服务、Worker
├── tests/
├── docker-compose.yml   # 开发编排（含 --reload，非生产镜像）
├── Dockerfile
└── .env.example
```

## 快速启动

```bash
cp .env.example .env
docker compose up -d
# API：http://localhost:8000/docs
# 健康检查：http://localhost:8000/health
```

本机只跑 API 时，先起 postgres / redis / rabbitmq / minio，再：

```bash
pip install -e ".[dev]"
pip install ortools
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker -Q scheduling,academic --loglevel=info
```

启动时自动建表并同步结构（新增/修改/删除字段随模型生效，幂等），写入内置角色、菜单权限、平台超管与学科字典；全环境生效，见部署文档与 `db/README-sql.md`。
