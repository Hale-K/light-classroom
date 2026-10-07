# 数据库

表结构以 `backend/app/models` 为唯一真相：应用**启动时自动建表**（幂等，含 pgvector 扩展、
内置角色/菜单/超管账号种子），无需手工执行 SQL 或迁移工具。

本目录提供两个参考文件：

| 文件 | 用途 |
| --- | --- |
| `baseline_schema.sql` | 全量表结构（62 张表）。用于不启动应用、先手工建库的场景 |
| `seed_tummi_data.sql` | 兔咪学校演示数据（含平台超管、菜单/权限/科目目录与全部业务数据）。TRUNCATE 前置，可重复执行 |

## 全新部署

1. 建库（PostgreSQL 16+，需已安装 pgvector 扩展包）：
   `CREATE DATABASE zhiheng;`
2. 配置 `backend/.env` 的 `DATABASE_URL`，直接启动应用——表与基础种子自动创建。
3. （可选）导入演示数据：`psql -f db/seed_tummi_data.sql`

## Docker 启动

`docker compose -f docker/docker-compose.deploy.yml up -d --build`——编排只含基础设施与
应用容器；表结构与基础种子由 API 容器启动时自动创建，无需额外的建表步骤。
导入演示数据：`docker compose -f docker/docker-compose.deploy.yml exec -T postgres psql -U zhiheng -d zhiheng < db/seed_tummi_data.sql`

## 数据安全

不要提交包含学生信息、密码哈希、Token 的 SQL 文件；演示数据统一走 `seed_tummi_data.sql`。
