# `app/ai` 分层（对齐 Spring AI Alibaba）

[Spring AI Alibaba](https://java2ai.com/) 把能力拆成 **ChatModel、Prompt、Advisor、Agent、Graph、Skill、Tool、MCP**。本仓库是 FastAPI，**不引入** `spring-ai-alibaba`、LangChain、LangGraph、MCP SDK。

| Spring AI Alibaba | 本仓库 | 做什么 |
|-------------------|--------|--------|
| ChatModel / ChatClient | `model/` | OpenAI 兼容对话（含 tools 参数）、服务商探测 |
| PromptTemplate | `prompt/` | 拼本轮 system |
| Advisor | `advisor/` | 澄清守卫（**无向量 RAG**） |
| Agent Framework | `agent/` | 教务一轮：首轮本地回复 → 带完整上下文的工具循环 |
| Graph Core | `graph/` | 工具循环：模型 → 教务只读工具 → 观察 → 再答，步数封顶 |
| Agent Skills | `skill/` | `skill/book/` 说明书；循环里模型用 `lookup_playbook` 取正文 |
| Tool / FunctionCallback | `tools/` | `retrieve_skill`（降级路径）；`school.py` 教务只读查询 |
| 确认执行 | `actions/` | `proposal.py` 草稿生成与校验、`confirm.py` 确认后原子追加与审计、`models.py` 草稿表 |
| 运行任务 | `runs/` | `service.py` 提交/取消/恢复、`progress.py` 阶段与心跳、`models.py` 运行表 |
| MCP Client / Registry | `mcp/` | **不接协议**；远程 Tool = 本校 REST |
| 表模型 | 分域存放 | `AiProvider` 在 `model/store.py`，`AiAction` 在 `actions/models.py`，`AiRun` 在 `runs/models.py` |

入口：`POST /assistant/chat` → `agent.teacher.handle_teacher_turn`。
模型不支持工具调用时自动降级为「目录路由 + 直接补全」旧路径。
同一问题短时间重复提问走回答缓存（`app/utils/answer_cache.py`）：只取说明书的问题缓存 6 小时，
查过本校实时数据的问题缓存 2 分钟；草稿与降级回答不缓存。

确认：`POST /assistant/actions/{id}`，body 为 `{"decision":"confirm"}` 或 `{"decision":"cancel"}`。
模型没有执行工具。草稿绑定学校、发起人，20 分钟有效；确认需 `scheduling:assign`，规则组/课位/学期改变后重新预览。追加规则与审计回执在同一事务提交，重复确认返回原回执。

首版支持白天、每周的科目禁排、具体教师禁排、学科连堂、具体教师每日上限。只向名称唯一的现有规则组追加，不切换启用组；其他规则仍通过手册指导。详见 `docs/assistant-agent.md`。
