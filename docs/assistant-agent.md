# 排课 Agent

助手复用 FastAPI、OpenAI 兼容模型与现有排课规则引擎。老师描述要求，助手查询本校现状、补齐缺失信息、生成规则草稿；老师点击确认后，服务端保存并返回回执。通用意图由本地 BGE + pgvector 路由到对应 Harness；说明书正文仍来自 `app/ai/skill/book`，不检索源码或业务文档。

## 第一版能力

- 查询本校教师、排课准备情况和已有规则组，按需读取操作手册。
- 多轮澄清：简短补充如“周三”“高一规则组”保留此前对话。
- 生成白天、每周生效的科目禁排、具体教师禁排、学科连堂、具体教师每日上限草稿。每份最多 10 条规则。
- 按真实科目/教师名称解析目标；不存在或同名时要求澄清。规则组必须已存在且名称唯一。新增规则只追加，不覆盖已有规则、不切换启用组。
- 草稿卡片展示学年学期、规则组、完整对象名单、星期、节次、连堂数量或每日上限，以及硬约束/软偏好。
- 点击确认后保存；支持取消、到期拒绝、重复请求返回原回执，以及成功后刷新规则工作台。

晚课、单双周、角色范围、修改/删除规则仍通过说明书指导，不转换成这四类规则。生成课表继续由老师在排课页操作；保存规则不代表已经通过排课求解或无冲突。没有规则组时，先在规则工作台创建。

## 试用

使用具有 `scheduling:assign` 权限的本校账号，先配置当前学年学期、白天课位、科目与规则组，启用支持工具调用的对话服务商。打开右侧助手：

1. “帮我检查排课准备情况，还缺什么？”
2. “本校有哪些规则组？”
3. “在高一规则组新增硬约束：数学每周三白天第 6、7 节不能排课，先给我草稿。”（替换为本校准确组名。）
4. 核对卡片，点“确认保存规则”。规则工作台会刷新。

其他例子：“数学每周至少一天连续两节，作为硬约束”；“张老师每天最多四节白天课，硬约束”。助手会询问尚未明确的规则组或数量；教师姓名需使用本校准确名称。

## 调用链

`AssistantDock → POST /api/v1/assistant/runs → execute_run → AssistantGateway → handle_assistant_turn → Harness → ReActLoop`；前端通过 `GET /runs/{id}` 查看真实阶段和结果。

模型可调用：`lookup_teachers`、`lookup_schedule_setup`、`lookup_rules`、`lookup_playbook`、`lookup_generation_status`，有配置权限时额外提供 `propose_rules`。查询结果返回模型；成功生成草稿后停止循环，由服务端返回可信摘要和卡片，不再让模型改写草稿内容。

聊天最多保留最近 20 条消息，每条截取 4000 字符；模型循环最多 4 轮，后台助手任务总预算 100 秒。工具失败转成可读观察供模型澄清；不支持工具调用时退回说明书问答，明确本轮没有可执行草稿。

自由文本全部进入后端 AssistantGateway，由同一份 pgvector 语义路由结果选择 Harness。前端只对老师明确点击的任务按钮执行确定性动作，并保留跳转确认；不再维护关键词意图旁路。旧课时确认路径仍独立于规则草稿。

## HTTP 契约

`POST /api/v1/assistant/runs` 提交可恢复任务；`GET /api/v1/assistant/runs/{id}` 返回状态，并在完成时通过 `data.result.plan` 返回可空草稿：

```json
{
  "id": "服务端生成的草稿编号",
  "status": "pending",
  "summary": "老师可核对的完整规则摘要",
  "expires_at": "2026-09-05T10:20:00Z",
  "result": null
}
```

`POST /api/v1/assistant/actions/{id}` 请求为 `{"decision":"confirm"}` 或 `{"decision":"cancel"}`。客户端不能提交可执行规则载荷。响应返回更新后的 `plan`；成功时 `result` 包含 `text`、`path`、`count`。

草稿状态为 `pending`、`executed`、`cancelled`；20 分钟后未执行草稿返回 409。不存在/跨学校/跨发起人返回 404；确认时重新检查权限，权限不足返回 403；规则组、学期、课位或目标改变时返回 409，要求重新预览。

## 存储与并发

`AiAction` 保存发起人、学校、不可变载荷、快照指纹、过期时间和执行回执。确认时锁定草稿与规则配置行，比较组和课位快照，再追加结构化规则。规则配置、草稿状态与专用 `AuditLog` 在同一事务中提交；失败由请求会话回滚。并发重复确认返回同一回执，不重复添加。

本服务校验参数完整性和课位范围，不能替代求解器的整体可行性检查。规则保存后需要重新生成与核对冲突。

## 数据库与运行

新增迁移：`b9d2e3f4a5c6_assistant_actions.py`，父版本 `a8c1d2e3f4b5`；`c0e3f4a5b6d7_assistant_runs.py` 接在草稿迁移之后。生产按项目既有迁移流程执行 `alembic upgrade head`；开发 `init_db` 可自动建表，迁移兼容已建草稿表。

本机开发库在本次实现中仅补齐了 `ai_action`、`ai_run` 表，没有跳过或改写原有 Alembic 版本记录。本机原有版本落后于迁移头，不应为此直接 stamp head。

## 验证

- 助手相关后端测试：`python -m pytest tests/test_assistant_guide.py tests/test_intent_vector.py tests/test_assistant_runtime.py tests/test_assistant_runs.py tests/test_assistant_progress.py tests/test_assistant_gateway.py tests/test_assistant_agent.py tests/test_assistant_actions.py -q`。
- PostgreSQL 并发测试：设置 `ASSISTANT_POSTGRES_TEST=1`，运行 `python -m pytest tests/test_assistant_postgres.py -q`。仅允许本机数据库，使用随机临时 schema 并在结束时清理。
- 前端：`npm run build`。浏览器：Vite 运行于 5176、Node 可解析 Playwright 且安装 Chrome 后运行 `node tests/assistant-agent.browser.cjs`。
- 浏览器使用隔离上下文与模拟接口验证预览、确认、取消、冲突、连续对话和窄屏布局，不操作学校真实规则。
- 真实租户模型已用虚构规则组和科目跑通 `lookup_rules → lookup_schedule_setup → propose_rules`，未发出学校业务数据，未保存业务规则。

扩大规则引擎回归时，原有 `test_cpsat_subject_six_weekday_periods_use_four_plus_two_distribution` 返回 INFEASIBLE；该测试及求解器源码本次未修改，需单独处理。

## 真实进度与恢复

任务提交携带客户端生成的 32 位 request_id；同编号、同载荷重复提交返回已有任务，不重复请求模型。跨用户/学校不可读取或取消。`POST /runs/{id}/cancel` 取消助手任务，不取消课表生成任务。

后台每 5 秒更新心跳，实际执行到模型请求、查询工具和草稿阶段时更新事件；前端每 1.5 秒读取一次，展示总耗时、阶段耗时和执行记录。阶段超过 15 秒提示尚无新结果，不编造百分比。任务 100 秒超时；心跳超过 30 秒未更新时读取接口标记中断。

同一浏览器标签页刷新后，通过按学校和用户隔离的 sessionStorage 任务编号恢复查看；这里只保存编号，不持久保存聊天内容。网络异常重试读取原任务；仍失败时保留恢复入口。取消与完成竞争时以数据库锁定的终态为准，取消后不提交规则草稿。

执行器运行在 API 进程内，进程重启不会自动续跑模型调用，而是明确显示中断。历史对话跨设备同步、课表生成任务刷新恢复、助手直接发起求解尚未实现。当前生成状态查询使用排课页已知的任务编号，页面卸载后需重新取得编号。

本轮验证：38 项后端检查通过（含隔离 PostgreSQL 任务完成/取消竞争、规则重复确认测试），前端构建通过。浏览器覆盖真实阶段展示、慢阶段提示、刷新不重复提交、后台取消确认及既有规则草稿流程。模型响应在浏览器测试中使用模拟接口，数据库测试使用隔离测试数据。
