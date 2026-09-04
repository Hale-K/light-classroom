# 运维：探活、上下线、扩容、日志

## 探活

- `GET /health`：进程活着即可，给 Nginx / 负载均衡用  
- `GET /metrics`：Prometheus 指标，不要对公网裸奔  

下线：先从上游摘掉实例，等请求结束再停进程。  
**排课 Worker** 先停止消费队列，再杀进程，避免 CP-SAT 做到一半被掐。  
上线：进程起来且 `/health` 为 200，再挂进上游。

## 扩容（无 Nacos）

不需要服务注册中心。多开进程/容器，靠探活摘除坏节点。

| 组件 | 怎么加 | 说明 |
|------|--------|------|
| 前端 | 多份 `dist` / CDN | 无状态 |
| API | 多 Uvicorn + Nginx `upstream` | JWT 无 Session；限流目前每进程一份内存 |
| Worker | 多 Celery，抢 RabbitMQ | 排课吃 CPU，优先扩这里 |
| Postgres / Redis / MQ / MinIO | 先加配再托管 | 测试环境单实例通常够 |

发布顺序：库与备份 → `alembic upgrade head` → Worker → API → 前端。

## 日志

loguru：控制台 + `logs/{环境}_{日期}.log`。

- 一行一条，时间在最前  
- 带 `trace_id`（请求头 `X-Trace-Id`，500 响应体也有）  
- 异常打完整栈  
- **文件保留 7 天**（按天切割）  

前端 Axios 会带 `X-Trace-Id`，对日志即可。

## JWT

`JWT_SECRET_KEY` 必须足够随机。测试、生产分开。不要提交进仓库。
