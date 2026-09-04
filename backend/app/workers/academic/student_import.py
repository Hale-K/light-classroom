"""学生档案确认后的异步落库。

现状：API POST /org/students/import/confirm 在本进程 asyncio.create_task，
进度在 app.api.v1.student_import 的内存 _tasks。

接入 Celery 后：入队到 academic 队列，调用 services.academic.student_import / student_membership。
"""
