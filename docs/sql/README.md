# 生产库初始化

分两步：**结构**用 Alembic，**兔咪学校数据**用 SQL。

## 1. 建库并升级结构

```bash
createdb zhiheng   # 库名按生产改
cd backend
cp .env.example .env   # 改 DATABASE_URL、JWT、ADMIN 密码
alembic upgrade head
```

`alembic upgrade head` 会建表，并写入权限点 / 菜单目录（全局，不含学校业务数据）。

## 2. 导入南思兔咪（nstmy）

文件：[nstmy_tumi.sql](nstmy_tumi.sql)

从当前开发库导出，包含：

- 学校 `tenant.code = nstmy`（库内校名：奶思兔咪鱿）
- 校长 **兔咪**，登录手机号 `13710617058`（密码哈希从开发库导出，**上线后立刻改密**）
- 高一班级、教师、任教、课时、组织任命、课表、课位/规则配置等

```bash
psql "$DATABASE_URL_SYNC" -v ON_ERROR_STOP=1 -f docs/sql/nstmy_tumi.sql
```

学校端请求头：`X-School-Code: nstmy`

## 3. 平台超管

页面：`/admin/login`（登录后进入 `/admin/schools`）。

生产不要用代码默认账号 `admin` / `admin123`。在 `.env` 里改 `ADMIN_USERNAME` / `ADMIN_PASSWORD`，或直接改 `platformadmin` 表。
