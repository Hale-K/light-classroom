# 页面与接口入口

开发前端默认 `http://localhost:5176`。生产将 `frontend-react/dist` 交给 Nginx，API 反代 `/api/v1`。

## 学校端

| 路径 | 说明 |
|------|------|
| `/login` | 学校账号登录 |
| `/dashboard` | 工作台 |
| `/scheduling` | 排课 |
| `/teacher-profiles` | 教师档案 |

请求头 `X-School-Code` 为当前 `tenant.code`。前端登录后会带上学校代码。

## 平台超管

| 路径 | 说明 |
|------|------|
| `/admin/login` | 超管登录（开通学校，不是学校教务账号） |
| `/admin/schools` | 学校列表 / 创建 |

账号来自 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（以及库表 `platformadmin`）。切勿使用文档里的开发默认口令上线。

## 后端

| 路径 | 说明 |
|------|------|
| `/docs` | Swagger UI |
| `/api/v1/openapi.json` | OpenAPI |
| `/health` | 探活 |
| `/metrics` | Prometheus |
