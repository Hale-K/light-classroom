"""模型统一出口
导入全部表模型使其注册到 SQLModel.metadata（供 init_db / Alembic autogenerate）。
"""
from app.models.enums import *  # noqa: F401,F403
from app.models.rbac import *  # noqa: F401,F403
from app.models.admin import *  # noqa: F401,F403
from app.models.org import *  # noqa: F401,F403
from app.models.facility import *  # noqa: F401,F403
from app.models.exam import *  # noqa: F401,F403
from app.models.gaokao import *  # noqa: F401,F403
from app.models.scan import *  # noqa: F401,F403
from app.models.analysis import *  # noqa: F401,F403
from app.models.practice import *  # noqa: F401,F403
from app.models.prediction import *  # noqa: F401,F403
from app.models.audit import *  # noqa: F401,F403
from app.models.transfer import *  # noqa: F401,F403
from app.models.scheduling import *  # noqa: F401,F403
# AI 表模型注册：actions/proposal 会反向导入 scheduling（循环），此处延迟保护——
# API 进程正常导入注册表结构；排课 worker 初始化时跳过（其不需要 AI 表，表由 Alembic 管理）
try:
    from app.ai.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeChunk  # noqa: F401
    from app.ai.model.store import AiProvider  # noqa: F401
    from app.ai.actions.models import AiAction  # noqa: F401
    from app.ai.runs.models import AiRun  # noqa: F401
    from app.ai.conversations.models import AiConversation  # noqa: F401
    from app.ai.intent.models import AiIntentExample  # noqa: F401
except ImportError:
    pass
