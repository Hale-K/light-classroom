"""MCP：对应 Spring AI MCP Client / Registry。

本助手不实现 MCP 协议（无 stdio/SSE、不把教务做成 MCP Server，也不连外部 MCP）。
Spring 里 MCP 的职责是「发现并调用远程 Tool」；本校远程能力是 REST + JWT + X-School-Code，
由已登录浏览器执行，见 frontend `assistant/run.ts`。
"""
