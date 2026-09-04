# 轻课堂

[English](README.en.md)

面向普通高中的教务系统：组织与人员、班级学生、规则化排课（OR-Tools CP-SAT）、课表与文件中心。

完整说明从 [docs/README.md](docs/README.md) 读起。

## 功能

- 多租户学校：请求头 `X-School-Code` 隔离数据
- 平台超管开通学校；学校端独立登录
- 排课规则工作台、课表生成（Celery 异步）、调课
- 教师档案、课时与任教关系
- 文件中心（MinIO / 腾讯云 COS）
- 可选 Prometheus 指标（`GET /metrics`）

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 19 · Vite · Ant Design · TypeScript |
| 后端 | Python 3.11+ · FastAPI · SQLModel · Alembic |
| 数据 | PostgreSQL · Redis · RabbitMQ · MinIO |
| 排课 | OR-Tools CP-SAT（需自行 `pip install ortools`） |

## 仓库结构

```
frontend-react/   学校端 + 平台超管 UI
backend/          API、迁移、Worker、测试
monitoring/       Prometheus / Grafana（可选）
docs/             架构、配置、部署、运维、规格
```

含学生名单、密码哈希的学校 SQL **不要提交、不要随开源包分发**。见 [db/README-sql.md](db/README-sql.md)。

## 快速开始（开发）

**后端**

```bash
cd backend
cp .env.example .env   # 至少改 JWT_SECRET_KEY
pip install -e ".[dev]"
pip install ortools
docker compose up -d postgres redis rabbitmq minio
uvicorn app.main:app --reload --port 8001
# 另开终端：
celery -A app.workers.celery_app worker -Q scheduling,academic --loglevel=info
```

- API 文档：http://localhost:8001/docs
- 探活：http://localhost:8001/health

`APP_ENV=dev` 时启动会建表并写入内置角色。生产必须执行 `alembic upgrade head`，见 [docs/deploy.md](docs/deploy.md)。

**前端**

```bash
cd frontend-react
pnpm install
pnpm dev
```

浏览器打开 http://localhost:5176 。开发代理默认把 `/api/v1` 转到 `127.0.0.1:8001`（可用 `VITE_DEV_PROXY` 修改）。

| 入口 | 路径 |
|------|------|
| 学校登录 | `/login` |
| 平台超管 | `/admin/login` |

开发超管账号见 `.env` 的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（示例为 `admin` / `admin123`，部署必须改掉）。

## 配置

没有 Spring `application.yml`。优先级为：**进程环境变量 > `backend/.env` > 代码默认值**。见 [docs/config.md](docs/config.md)。

## 测试

```bash
cd backend
pytest
```

排课相关用例较重，可先跑认证、RBAC、规则引擎子集。

## 文档

- [架构](docs/architecture.md) · [配置](docs/config.md) · [部署](docs/deploy.md) · [运维](docs/ops.md) · [监控](docs/monitoring.md)
- [页面入口](docs/frontend.md) · [ER](docs/ER-diagram.md) · [排课规格](docs/specs/schedule-and-seating.md)
- [贡献](CONTRIBUTING.md) · [安全披露](SECURITY.md) · [许可证](LICENSE)

## 许可

[MIT](LICENSE)。
