# 部署与上线准备

本文按当前仓库真实结构整理：能怎么跑、生产必须改什么、上线当天怎么验收、出事怎么回退。开发期 `docker compose` 与生产不要混用同一套默认密码。

## 1. 系统构成

```
浏览器 ──► 静态站点（frontend-react 构建产物）
              │
              │  /api/v1  （生产用 Nginx 反代，开发用 Vite 代理）
              ▼
         FastAPI :8000
              │
              ├── PostgreSQL
              ├── Redis（缓存 / Celery 结果）
              ├── RabbitMQ（Celery broker，队列 scheduling、academic）
              ├── MinIO 或腾讯云 COS（文件中心）
              ├── Celery Worker（排课生成；求解可能数分钟）
              └── （可选）Kafka、Prometheus/Grafana
```

关键入口：

| 用途 | 路径 |
|------|------|
| 健康检查 | `GET /health` |
| Prometheus | `GET /metrics` |
| OpenAPI | `/docs`、`/api/v1/openapi.json` |
| 前端开发 | Vite `5176`，默认把 `/api/v1` 代理到 `127.0.0.1:8001` |

排课生成走 Celery 任务 `scheduling.generate`。白天求解约 150s、晚课约 100s，最多 5 组 seed；反代和负载均衡必须允许长连接 / SSE，不要 60s 掐断。

## 2. 文档地图

| 文档 | 用途 |
|------|------|
| [文档目录](README.md) | 总索引 |
| 本文 | 上线清单、环境、回滚 |
| [db/README-sql.md](../db/README-sql.md) | 建库 + 导入兔咪数据 |
| [backend/.env.example](../backend/.env.example) | 环境变量模板 |
| [backend/docker-compose.yml](../backend/docker-compose.yml) | 开发编排（含 `--reload`，不要当生产镜像） |
| [monitoring/docker-compose.yml](../monitoring/docker-compose.yml) | 指标栈；默认刮取宿主机 `:8001` |
| [ER-diagram.md](ER-diagram.md) | 表关系 |
| [specs/](specs/) | 排课 / 走班规格 |

## 3. 上线前必须改的配置

从 `backend/.env.example` 复制为生产 `.env`（或密钥管理系统），至少改这些：

| 变量 | 要求 |
|------|------|
| `APP_ENV` | `prod`。仅 `dev` 会在启动时 `init_db` 自动建表；生产必须走 Alembic |
| `APP_DEBUG` | `false` |
| `JWT_SECRET_KEY` | 足够长的随机串，禁止沿用 example |
| `ADMIN_PASSWORD` | 改掉代码默认 `admin123`（`app/core/config.py`） |
| `DATABASE_URL` | 生产库账号，最小权限；不要用 compose 里的 `zhiheng/zhiheng` |
| `REDIS_URL` / `CELERY_*` | 生产 Redis、RabbitMQ 账号密码 |
| `MINIO_*` 或 `COS_*` | 生产对象存储；`MINIO_SECURE=true` 并配公网/内网可达的 `MINIO_PUBLIC_BASE_URL` |
| `DEFAULT_SCHOOL_CODE` | 私有化单校可固定；SaaS 靠请求头 `X-School-Code` |
| `LLM_API_KEY` | 若本期不用 AI，可留空，但不要把测试 key 带上生产 |

前端构建：

```bash
cd frontend-react
# 若 API 与静态站点不同源，构建时指定完整前缀，例如 https://api.example.com/api/v1
# 同源反代则可省略，运行时默认请求 /api/v1
pnpm install
pnpm build
```

产物在 `frontend-react/dist/`，交给 Nginx（或对象存储 + CDN）。

## 4. 上线前代码债（已知，不要假装没有）

这些会直接挡生产或留下安全洞，应在第一次对外服务前处理或明确接受风险：

1. **CORS 全开**：`backend/app/main.py` 里 `allow_origins=["*"]` 且 `allow_credentials=True`。生产改为具体前端域名。
2. **Dockerfile 是开发镜像**：`pip install -e ".[dev]"`、`CMD` 带 `--reload`。生产应多阶段构建、只装运行依赖、无 reload、非 root。
3. **`ortools` 未写入 `pyproject.toml`**，但排课 CP-SAT 依赖它。镜像/服务器必须显式安装 `ortools`，否则 Worker 一排课就崩。
4. **生产不要自动建表**：`APP_ENV=prod` 后执行 `alembic upgrade head`（在 `backend/`，`alembic.ini` 的 `script_location=migrations`）。
5. **默认超管口令、MinIO 示例账号、Grafana `admin123`** 全部更换；`/docs` 是否对公网开放要单独决定。
6. **compose 里 Kafka advertised 是 `localhost`**，容器互访会有问题。若本期排课/文件中心不依赖 Kafka，生产可先不部署 Kafka。
7. **限流**是进程内内存窗口（`RATE_LIMIT_*`）。多副本 API 时各算各的，报到高峰按需调大或改为 Redis。
8. **学生导入**注释写明进度曾在 API 进程内存；确认生产路径是否已切到 Celery `academic` 队列，Worker 必须同时消费 `scheduling,academic`。

## 5. 推荐生产拓扑（最小可用）

不必把开发 compose 原样搬上去。建议拆开：

- **PostgreSQL / Redis / RabbitMQ / MinIO**：云厂商托管或独立 compose，数据盘持久化与备份。
- **API**：若干副本，反向代理到 `/health` 做探活。
- **Worker**：至少 1 个；排课吃 CPU，与 API 分机更好。命令示例：

  ```text
  celery -A app.workers.celery_app worker -Q scheduling,academic --concurrency=2 --loglevel=info
  ```

  `concurrency` 按 CPU 核数；CP-SAT 内部还会开多线程，不要把并发开太大把机器打满。
- **Nginx**：静态资源 + `/api/v1` 反代；SSE / 长请求关闭缓冲，例如 `proxy_buffering off;`、`X-Accel-Buffering: no`（开发代理已按此处理）。
- **监控（可选）**：`monitoring/docker-compose.yml`。把 `prometheus.yml` 里的 `host.docker.internal:8001` 改成生产 API 地址；改 Grafana 密码。

数据库：当前 Docker 部署用 `docker/docker-compose.deploy.yml`。`migrate` 服务在 API 和 Worker 之前执行 `alembic upgrade head`；已执行的迁移会自动跳过，迁移失败则阻止应用启动。随后 `schema-init` 再灌 `db/schema/*.sql`。API 使用 `APP_ENV=prod`，启动不再 `create_all`。

学生端选科功能依赖 `studentcredential` 表。发布包含学生端功能的版本时，不要手工建表，只需让发布流程完成 `alembic upgrade head`；当前迁移会自动创建学生登录凭证表及租户范围内的唯一约束。迁移成功后，再启动 API 和 Worker。

本机不经过 Compose 时：

```bash
cd backend
alembic upgrade head
```

或：

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/schema/ai_provider.sql
```

内置角色与菜单权限：开发环境在 `lifespan` 里自动 `ensure_builtin_roles` / `ensure_menu_permissions`。生产由 `migrate` 容器在 Alembic 之后执行 `python -m app.bootstrap_deploy`。

## 6. 上线当天检查清单

### 发布前

- [ ] 生产密钥不在 git 里；`.env` / 云密钥已轮换
- [ ] `APP_ENV=prod`，`APP_DEBUG=false`
- [ ] CORS 白名单 = 实际前端 origin
- [ ] `ortools` 已装进 Worker 镜像
- [ ] `alembic upgrade head` 成功；抽查关键表存在
- [ ] RBAC 目录 / 超管账号可登录
- [ ] MinIO/COS 桶可写，下载 URL 浏览器能打开
- [ ] RabbitMQ 队列 `scheduling`、`academic` 有消费者
- [ ] 前端 `pnpm build` 指向正确 API
- [ ] Nginx 超时 ≥ 排课任务（建议 5–10 分钟级）且 SSE 不缓冲
- [ ] `/health`、`/metrics` 从探活网可达；`/metrics` 是否对公网暴露已决定
- [ ] 备份：空库或最新库快照已做一份

### 发布后 1 小时

- [ ] 登录、切学校代码（若多租户）、打开课表页
- [ ] 保存一条规则组（确认「保存规则」后刷新仍在）
- [ ] 触发一次小规模排课，Worker 日志有进度，前端能等到结果或明确失败原因
- [ ] 文件中心导出/上传一条（若本期启用）
- [ ] 错误日志无新增 500；Prometheus 有流量则看 5xx 与延迟

### 回滚

- **前端**：切回上一版 `dist` 或 CDN 目录。
- **API / Worker**：部署上一版镜像；**先停 Worker 再切 API**，避免新任务打到旧代码或相反。
- **数据库**：Alembic 迁移没有统一「一键 downgrade」保证。上线前记下 `alembic current`；有破坏性迁移时准备好备份恢复，而不是盲目 `downgrade`。
- **对象存储**：不要清桶；回滚应用即可。

触发回滚的经验阈值：登录失败、排课任务全部立刻失败、5xx 相对基线翻倍、出现数据串租户。

## 7. 本机开发（对照，非生产）

后端：

```bash
cd backend
cp .env.example .env
docker compose up -d   # postgres / redis / rabbitmq / kafka / minio / api / worker
# 或只起依赖，本机：uvicorn app.main:app --reload
```

注意：仓库 compose 里 API 映射 `8000`，前端 Vite 默认代理 `8001`。本机若 API 不在 8001，设 `VITE_DEV_PROXY`。

前端：

```bash
cd frontend-react
pnpm install
pnpm dev
```

测试：`backend` 下 `pytest`（需本机依赖与库）。排课相关用例较重，上线前至少跑与认证、RBAC、排课生成相关的子集。

## 8. 容量与排课说明（给运维）

- 一次完整课表生成可能占用 Worker 数分钟 CPU；高峰不要和数据库备份抢同一台 4 核机器。
- 任务 `task_time_limit` 为 30 分钟（`celery_app.py`），软限制 28 分钟。
- 不要用开发 `--reload` 跑生产：改文件会丢正在求解的进程。

## 9. 建议的发布顺序

1. 基础设施（库、Redis、MQ、对象存储）+ 备份  
2. `migrate` 自动执行迁移 + RBAC 种子
3. Worker（先起来，避免 API 入队无人消费）  
4. API + 探活  
5. 前端静态资源  
6. 冒烟（登录 → 规则保存 → 小规模生成）  
7. 再开给业务用户  
