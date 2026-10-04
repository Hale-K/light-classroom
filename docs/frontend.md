# 页面与接口入口

开发前端默认 `http://localhost:5176`。生产将 `frontend-react/dist` 交给 Nginx，API 反代 `/api/v1`。

## 学校端

| 路径 | 说明 |
|------|------|
| `/login` | 学校账号登录 |
| `/dashboard` | 工作台 |
| `/scheduling` | 排课 |
| `/teacher-profiles` | 教师档案 |
| `/settings` | 系统设置（学年学期） |
| `/ai-providers` | 模型服务商（老师自填 Key） |

全局停靠栏：猫头鹰助手（Agentic RAG，见 [教务助手](assistant-agent.md)）。

请求头 `X-School-Code` 为当前 `tenant.code`。前端登录后会带上学校代码。

## 平台超管

| 路径 | 说明 |
|------|------|
| `/admin/login` | 超管登录（开通学校，不是学校教务账号） |
| `/admin/schools` | 学校列表 / 创建 |

账号来自 `ADMIN_USERNAME` / `ADMIN_PASSWORD`（以及库表 `platformadmin`）。切勿使用文档里的开发默认口令上线。

## 学生端

| 路径 | 说明 |
|------|------|
| `/student/login` | 学生使用学校代码、学号和学生端密码登录 |
| `/student/choice` | 查看学校当前新高考方案，保存或提交个人选科 |

学生账号不复用教职工 `User`。教务人员在“学生档案 → 开通学生登录”中按年级批量开通账号；学生端只允许访问当前学生自己的选科记录。学生提交后进入班主任审核，班主任在新高考走班工作台的“班级选科审核”中逐条或批量通过并锁定，也可以驳回让学生重新提交。当前学生端重点支持 3+1+2，3+3 和传统模式的差异化表单仍需后续补齐。

## 后端

| 路径 | 说明 |
|------|------|
| `/docs` | Swagger UI |
| `/api/v1/openapi.json` | OpenAPI |
| `/health` | 探活 |
| `/metrics` | Prometheus |
