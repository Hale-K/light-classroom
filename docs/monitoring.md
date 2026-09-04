# 监控

当前是 **Prometheus + Grafana**，不是 APM（无 SkyWalking / Nacos）。

**Prometheus 干什么：** 定期拉取数字指标（QPS、延迟、5xx、CPU、内存），回答「这一小时整体正不正常」。单次失败看日志里的 `trace_id`。

可选栈在仓库 `monitoring/docker-compose.yml`：

| 服务 | 端口 | 作用 |
|------|------|------|
| Prometheus | 9090 | 存指标，配置里 TSDB 留 15 天 |
| Grafana | 3300 | 看板，默认 `admin` / `admin123` 必须改 |
| Node Exporter | 9100 | 机器 |
| cAdvisor | 8081 | 容器 |

API 已用 `prometheus-fastapi-instrumentator` 暴露 `/metrics`。Prometheus 示例目标是 `host.docker.internal:8001`，部署时改成真实 API。

Celery Worker **没有**单独看板，看机器 CPU 和 RabbitMQ 队列深度。

**要不要 Nacos：** 不要。配置用环境变量，扩容用副本 + `/health`。
