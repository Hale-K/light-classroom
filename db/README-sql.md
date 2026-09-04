# 数据库初始化

## 结构（开源部署通用）

```bash
cd backend
cp .env.example .env   # 改 DATABASE_URL、JWT_SECRET_KEY、ADMIN_PASSWORD
alembic upgrade head
```

会建表并写入**全局**权限点与菜单。`APP_ENV=dev` 时进程启动还会尝试自动建表和内置角色；生产请只用 Alembic，见 [docs/deploy.md](../docs/deploy.md)。

## 学校业务数据（不要放进公开仓库）

含学生名单、教师手机号、密码哈希的 SQL dump **不得随开源仓库分发**。各校在私有环境导入：

```bash
# 仅作示例：文件放在本机或内网，不要 git add
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /path/to/private_school.sql
```

学校端请求头 `X-School-Code` 对应 `tenant.code`。平台超管在 `/admin/login` 开通学校。
