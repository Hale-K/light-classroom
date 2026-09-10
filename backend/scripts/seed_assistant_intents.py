"""Generate BGE vectors for reviewed assistant intent examples."""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from app.ai.intent.models import AiIntentExample
from app.ai.intent.vector import SentenceTransformerEmbedding
from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine


EXAMPLES = {
    "guide": [
        "这个页面怎么使用", "下一步应该做什么", "给我介绍一下这里的功能",
        "帮我切到对应页面", "这个菜单是做什么的", "教务老师应该怎么操作",
    ],
    "readiness": [
        "检查本校排课准备情况", "看看高一年级还缺哪些数据", "任教关系是否完整",
        "课时方案和课位结构配置好了吗", "核对排课前置条件", "现在可以开始排课了吗",
    ],
    "diagnosis": [
        "为什么这次排课失败了", "课表生成一直卡住", "重新生成后任务没有继续",
        "帮我诊断排课冲突", "查看排课任务当前进度", "求解进程中断后如何恢复",
    ],
    "configuration": [
        "创建高一数学晚课禁排规则", "帮我配置教师连堂规则", "生成一份规则草稿",
        "修改当前排课约束", "为这个班设置禁排时段", "新增一条教室分配规则",
        "替老师安排不能上课的时间", "设置某位老师不能上课的节次",
    ],
}


async def main() -> None:
    encoder = SentenceTransformerEmbedding(settings.assistant_embedding_model_path)
    pairs = [(intent, utterance) for intent, values in EXAMPLES.items() for utterance in values]
    vectors = await encoder.embed([utterance for _, utterance in pairs])
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        for (intent, utterance), vector in zip(pairs, vectors, strict=True):
            statement = insert(AiIntentExample).values(
                intent=intent,
                utterance=utterance,
                embedding=vector,
                embedding_model="bge-base-zh-v1.5",
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            statement = statement.on_conflict_do_update(
                constraint="uq_ai_intent_example_intent_utterance",
                set_={
                    "embedding": vector,
                    "embedding_model": "bge-base-zh-v1.5",
                    "enabled": True,
                    "updated_at": now,
                },
            )
            await session.execute(statement)
        await session.commit()
    await engine.dispose()
    print(f"Seeded {len(pairs)} assistant intent vectors")


if __name__ == "__main__":
    asyncio.run(main())
