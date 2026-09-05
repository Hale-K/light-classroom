"""Graph 运行时：对应 Spring AI Alibaba Graph（StateGraph）的单节点工具循环。

`loop.py` 实现「模型 → 工具 → 观察 → 再答」的循环，步数封顶、末步强制收口。
教务查询由循环里的工具执行（见 `tools/school.py`）；页面跳转等 UI 动作
仍由前端执行（`assistant/run.ts`）。不引入 LangGraph / spring-ai-alibaba-graph；
需要多节点编排（如多步确认写入）时再在这里加节点。
"""
