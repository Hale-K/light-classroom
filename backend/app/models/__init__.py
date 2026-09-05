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
from app.ai.model.store import AiProvider  # noqa: F401
from app.ai.actions.models import AiAction  # noqa: F401
from app.ai.runs.models import AiRun  # noqa: F401
from app.ai.conversations.models import AiConversation  # noqa: F401
