# 轻课堂文档

开源仓库的说明从这里导航。

- 项目简介（中文）：[README.zh.md](../README.zh.md)
- 项目简介（英文）：[README.en.md](../README.en.md)
- 英文文档目录：[README.en.md](README.en.md)

## 使用与部署

| 文档 | 内容 |
|------|------|
| [架构](architecture.md) | 单体、租户、Worker、请求路径 |
| [配置](config.md) | 环境变量覆盖 `.env`，没有 Spring yaml 分层 |
| [部署上线](deploy.md) | 密钥、Alembic、检查清单、回滚 |
| [数据库](../db/README-sql.md) | 迁移；学校数据请私有导入，不要开源 dump |
| [运维](ops.md) | 探活、上下线、扩容、日志 7 天、JWT |
| [监控](monitoring.md) | Prometheus / Grafana；不需要 Nacos |
| [页面与 API](frontend.md) | `/login`、`/admin/login`、`/docs` |

## 产品与数据模型

| 文档 | 内容 |
|------|------|
| [核心 ER](ER-diagram.md) | 表关系 |
| [ER 图集](diagrams/index.html) | 分域图（浏览器打开） |
| [排课与座位](specs/schedule-and-seating.md) | 规格 |
| [新高考走班](specs/new-gaokao-walk-class.md) | 规格 |
| [教务助手](assistant-agent.md) | 猫头鹰 Agentic RAG：取说明书 / 查教务 API，不是向量搜文档 |
| [助手健壮性架构](assistant-resilience.md) | Agent 的故障识别、恢复、隔离、降级与后续演进边界 |

## 参与项目

[贡献指南](../CONTRIBUTING.md) · [安全披露](../SECURITY.md) · [MIT 许可](../LICENSE)

后端目录说明：[backend/README.md](../backend/README.md)
