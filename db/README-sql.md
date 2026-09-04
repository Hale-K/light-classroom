# 数据库初始化

## 结构（开源部署通用）

优先用 Alembic（与代码版本对齐）：

```bash
cd backend
cp .env.example .env   # 改 DATABASE_URL、JWT_SECRET_KEY、ADMIN_PASSWORD
alembic upgrade head
```

会建表并写入**全局**权限点与菜单。`APP_ENV=dev` 时进程启动还会尝试自动建表和内置角色；生产请只用 Alembic，见 [docs/deploy.md](../docs/deploy.md)。

结构 SQL 也放在 `db/schema/`，给不跑迁移、只灌库的上线步骤用。文件可重复执行。

### Docker 部署（`docker/docker-compose.deploy.yml`）

编排里有 `schema-init`：等 `api` 健康（基础表已在）后，把 `db/schema/*.sql` 灌进容器里的 Postgres。

```bash
# 仓库根目录
docker compose -f docker/docker-compose.deploy.yml up -d --build
docker compose -f docker/docker-compose.deploy.yml logs schema-init
```

日志里应有 `apply /schema/ai_provider.sql` 和 `schema-init done`。已有库再执行一遍不会破坏数据。

手动进库检查：

```bash
docker compose -f docker/docker-compose.deploy.yml exec postgres \
  psql -U zhiheng -d zhiheng -c '\d ai_provider'
```

### 不用 Compose、直接 psql

```bash
# 在仓库根目录；DATABASE_URL 换成生产连接串
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/schema/ai_provider.sql
```

| 文件 | 内容 |
|------|------|
| [schema/ai_provider.sql](schema/ai_provider.sql) | 大模型服务商表 `ai_provider` + 菜单/权限 |

不要把 API Key 写进这些 SQL。学校在系统里「服务商管理」页面配置。

## 学校业务数据（不要放进公开仓库）

含学生名单、教师手机号、密码哈希的 SQL dump **不得随开源仓库分发**。各校在私有环境导入：

```bash
# 仅作示例：文件放在本机或内网，不要 git add
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /path/to/private_school.sql
```

学校端请求头 `X-School-Code` 对应 `tenant.code`。平台超管在 `/admin/login` 开通学校。
