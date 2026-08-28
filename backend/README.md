# 轻课堂后端 (light-classroom-backend)

> toB 普通高中教务闭环系统 · FastAPI 模块化单体

## 技术栈

- **FastAPI** + Uvicorn（ASGI）
- **SQLModel**（Pydantic + SQLAlchemy 二合一）+ asyncpg
- **PostgreSQL** + **Redis** + **Kafka**（事件总线）
- **Celery**（异步任务）
- JWT 认证 · 多租户（学校代码路由）

## 目录结构

```
backend/
├── app/
│   ├── main.py            # FastAPI 入口 + 中间件链
│   ├── core/              # config / security
│   ├── db/                # session(多租户中间件) / base(CRUD 基类)
│   ├── api/v1/            # 路由层（待业务实现）
│   ├── models/            # SQLModel 实体（待实现）
│   ├── services/          # 业务逻辑层
│   ├── workers/           # Celery 异步任务
│   └── ai/                # LLM 编排 + 批改引擎 + 押题
├── tests/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## 快速启动

```bash
# 1. 复制配置
cp .env.example .env
# 编辑 .env（数据库/Redis/Kafka/LLM key/COS）

# 2. Docker Compose 一键起依赖 + API（推荐）
docker compose up -d

# 或本地开发（需先起 postgres/redis/kafka）
pip install -e ".[dev]"
uvicorn app.main:app --reload

# 3. 访问
# API 文档：http://localhost:8000/docs
# 健康检查：http://localhost:8000/health
```

## 对标 MyBatis-Plus 的设计

| MyBatis-Plus | 本项目对应 |
|--------------|-----------|
| BaseMapper（CRUD 自动生成） | `app/db/base.py` 的 `BaseRepo` 基类 |
| QueryWrapper（条件构造） | `BaseRepo.select_by_filter(**filters)` 链式 |
| 多租户插件 | `app/db/session.py` 的 `tenant_middleware` + `tenant_id_ctx` |
| 逻辑删除 | `SoftDeleteMixin`（is_deleted + 查询过滤） |
| 字段自动填充 | `TimestampMixin`（created_at/updated_at） |

## 待实现（按阶段 0 设计）

- [ ] 实体模型（34 张表，见《阶段0-数据模型设计》）
- [ ] RBAC 六表（role/permission/menu 等）
- [ ] 业务路由（10 个模块）
- [ ] JWT 中间件 + RBAC 权限点校验
- [ ] 多租户查询自动注入（with_loader_criteria）
- [ ] Celery 任务 + Kafka 事件
- [ ] AI 编排层（LLM 客户端 + 批改引擎）
- [ ] 七类 PDF 打印
