"""FastAPI 入口 - 中间件链 + 路由挂载

中间件链（对标后端架构接入层）：
  JWT 认证 → 学校代码解析(X-School-Code) → RBAC 权限点+数据范围 → 限流 → 审计日志
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.trace import TRACE_HEADER, current_trace_id, trace_middleware
from app.db.session import tenant_middleware, init_db

# B9: loguru 日志接入（幂等，含滚动文件）
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    logger.info(f"🚀 {settings.app_name} 启动中 (env={settings.app_env})")
    if settings.app_env == "dev":
        # 开发期自动建表；生产走 Alembic 迁移
        await init_db()
        # 同步权限点目录 + 内置角色与默认权限
        from app.db.session import AsyncSessionLocal
        from app.services.rbac import ensure_builtin_roles, ensure_menu_permissions
        async with AsyncSessionLocal() as session:
            await ensure_builtin_roles(session)
            await ensure_menu_permissions(session)  # 菜单结构 + 菜单权限映射
            await session.commit()
    try:
        from app.workers.scheduling.generate import recover_incomplete_jobs

        recovered = await recover_incomplete_jobs()
        if recovered:
            logger.bind(event="scheduling_recovery_completed", recovered=recovered).warning(
                f"已恢复 {recovered} 个排课任务"
            )
    except Exception as exc:
        # 首次部署可能由 schema-init 随后建表；恢复失败不能阻止 API 提供服务。
        logger.bind(event="scheduling_recovery_unavailable").warning(f"排课任务恢复暂不可用: {exc}")
    yield
    # 关闭
    logger.info("👋 关闭中")


app = FastAPI(
    title=settings.app_name,
    description="轻课堂 toB 普通高中教务闭环系统",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
)

# ---------- 中间件链 ----------
# 1. CORS：生产必须使用明确的前端来源白名单，禁止通配符。
_cors_origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
if not _cors_origins and settings.app_env == "dev":
    _cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-School-Code", "X-Trace-Id"],
    expose_headers=[TRACE_HEADER],
)

# 2. 学校代码解析（多租户路由锚点）
app.middleware("http")(tenant_middleware)

# 3. A5: 限流（内存滑动窗口），放在最外层，先于一切业务处理
from app.middleware.rate_limit import rate_limit_middleware
app.middleware("http")(rate_limit_middleware)

# 4. A5: 审计日志（写操作留痕）
from app.middleware.audit import audit_middleware
app.middleware("http")(audit_middleware)

# 请求级 trace_id：最后注册，进站最先执行，后续日志都能带上
app.middleware("http")(trace_middleware)

# 5. TODO: JWT 认证中间件 / RBAC 权限点校验
# （权限点由接口级 require_permission 依赖校验；中间件全链路鉴权待接入）

# 6. Prometheus 指标埋点：/metrics 暴露 QPS、延迟分位、状态码分布
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/metrics", "/health", "/docs*", "/openapi*"],
).instrument(app).expose(app, include_in_schema=False)


# ---------- 统一响应与异常 ----------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = current_trace_id()
    logger.opt(exception=exc).error(
        f"未捕获异常 {request.method} {request.url.path}: {exc}"
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": "服务器内部错误",
            "data": None,
            "trace_id": trace_id,
        },
        headers={TRACE_HEADER: trace_id},
    )


# ---------- 健康检查 ----------
@app.get("/health", tags=["system"])
async def health():
    """健康检查"""
    return {"code": 0, "message": "ok", "data": {"status": "healthy", "env": settings.app_env}}


# ---------- 路由挂载（按模块陆续加） ----------
from app.api.v1 import admin, auth, org, exam, scan, grading, stats, scheduling, seating, exam_scheduling, gaokao, student_auth, staff, dashboard, organization, facilities, rbac, teacher_profiles, student_import, file_center, ai_provider, assistant, onboarding, knowledge
app.include_router(admin.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(org.router, prefix="/api/v1")
app.include_router(exam.router, prefix="/api/v1")
app.include_router(scan.router, prefix="/api/v1")
app.include_router(grading.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(scheduling.router, prefix="/api/v1")
app.include_router(seating.router, prefix="/api/v1")
app.include_router(exam_scheduling.router, prefix="/api/v1")
app.include_router(gaokao.router, prefix="/api/v1")
app.include_router(student_auth.router, prefix="/api/v1")
app.include_router(staff.router, prefix="/api/v1")
app.include_router(organization.router, prefix="/api/v1")
app.include_router(facilities.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(rbac.router, prefix="/api/v1")
app.include_router(teacher_profiles.router, prefix="/api/v1")
app.include_router(student_import.router, prefix="/api/v1")
app.include_router(file_center.router, prefix="/api/v1")
app.include_router(ai_provider.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(onboarding.router, prefix="/api/v1")
# from app.api.v1 import exam, grading, ...
# 待业务实现后陆续挂载：权限/组织学籍/考试试卷/扫描进卷/打分/画像诊断/巩固卷/押题/AI编排/打印


@app.get("/", tags=["system"])
async def root():
    return {"code": 0, "message": f"欢迎来到{settings.app_name}", "data": None}
