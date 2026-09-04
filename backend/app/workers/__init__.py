"""后台任务入口（按领域分子包，与 app.services 对齐）。

Worker 负责任务线程、超时与投递；算法和落库仍在 app.services。
"""
