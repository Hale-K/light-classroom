# 贡献指南

感谢你愿意改这个项目。请先读 [docs/README.md](docs/README.md) 和根目录 [README.md](README.md)。

## 环境

- Python 3.11+
- Node.js 20+ 与 pnpm
- Docker（Postgres / Redis / RabbitMQ / MinIO）
- `ortools`：排课 Worker 必需，目前未写入 `pyproject.toml`，需额外安装

不要提交 `.env`、日志、数据库 dump、学生/教师真实数据。

## 开发习惯

- 后端：改 API 或规则时尽量补 `backend/tests/` 里对应测试
- 前端：管理端 UI 变更后，用浏览器把相关流程点一遍（不只截一张图）
- 排课求解很重，本地不要默认跑完整生成当单元测试
- 提交信息用中文或英文完整句子，说明「为什么」而不是只列文件名

## Pull Request

1. 从默认分支拉出功能分支
2. `cd backend && pytest` 能过的子集至少跑完
3. `cd frontend-react && pnpm typecheck`（以及你改过的页面自测）
4. PR 里写清行为变化、如何验证、是否需要迁移

安全问题请按 [SECURITY.md](SECURITY.md) 私下披露，不要开 Issue 贴利用步骤。
