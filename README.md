# 轻课堂 / 智衡

面向普通高中的教务系统：组织与人员、班级学生、排课（规则工作台 + CP-SAT）、课表与文件中心等。

| 目录 | 说明 |
|------|------|
| `frontend-react/` | 管理端（Vite + React + Ant Design） |
| `backend/` | API（FastAPI）+ Celery Worker |
| `monitoring/` | Prometheus + Grafana（可选） |
| `docs/` | 业务说明与上线文档 |

**上线前请先读：[部署与上线准备](docs/deploy.md)、[生产库初始化 SQL](docs/sql/README.md)。**

其它文档：

- [核心 ER](docs/ER-diagram.md)
- [排课与座位规格](docs/specs/schedule-and-seating.md)
- [新高考走班规格](docs/specs/new-gaokao-walk-class.md)
- [后端开发说明](backend/README.md)
