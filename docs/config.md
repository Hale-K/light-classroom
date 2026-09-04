# 配置

后端没有 `application.yml`。配置在 `backend/app/core/config.py`（pydantic-settings），加载顺序 **后者覆盖前者无效：环境变量优先**：

1. 代码里的字段默认值  
2. 项目目录 `backend/.env`（本机个性化，不进 git）  
3. **进程环境变量**（Docker / systemd / 测试机 export）覆盖 `.env`

模板：`backend/.env.example`。测试机复制为 `.env` 后改密钥和库地址即可。

学校差异（课表、教师）不在 `.env`，在数据库租户数据 + `X-School-Code`。

必改项见 [deploy.md](deploy.md)。JWT 示例：

```
JWT_SECRET_KEY=<用 secrets.token_urlsafe(48) 生成>
```

测试和生产不要共用同一把 JWT。换密钥后所有登录态失效。

前端构建期变量（Vite）：`VITE_API_BASE_URL`、开发代理 `VITE_DEV_PROXY`。
