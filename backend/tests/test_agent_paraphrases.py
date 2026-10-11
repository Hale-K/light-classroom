"""Complexity routing must survive ordinary paraphrases without a classifier."""
import pytest

from app.ai.intent.gateway import IntentGateway, ExecutionMode


PLANNING_QUESTIONS = [
    '设计各科课时方案',
    '继续之前的任务，保留已明确的条件。接下来希望我帮你完成什么？：设计各科课时方案',
    '高一有1000名学生，每班45至55人，需要多少教室和老师？',
    '高一一千名学生，每班四十五到五十五人，师资和教室怎么配比较合适？',
    '1000个孩子，班额控制在45—55，帮我算算要开多少班、配多少教师和教室。',
    '高一1000人，每班45-55人，教室和师资够不够？',
    '按一千人、每班五十人估算高一的教学资源需求，心理音乐美术体育都要开。',
    '给1000名高一学生做两个师资配置方案，每班45至55人。',
    '高一开20个班，哪些学科缺老师？比较招聘和跨年级兼课两个方案。',
    '20个班的高一师资够用吗？缺口怎么补更好？',
    '周一到周五每天9节，前7节必须排满，后2节可选，体育2音乐美术心理各1，给三个方案。',
    '高一课时怎么分合理？语数英多一点，艺体心也要保证。',
    '这次排课为什么失败？查日志并给出最少改动的解决方案。',
    '课表一直排不出来，帮我找原因并想办法解决。',
    '数学老师下周三请假，找出受影响课程，比较代课和调课两个方案。',
    '下周三数学老师来不了，课程怎么协调？',
    '按高二选科组合和45至55人班额，规划教学班、教师和同时使用的教室。',
    '高二走班怎么分？各科人数不一样，老师和教室要怎么配？',
    '全面检查高一能否开始分班排课，列出缺项和补充顺序。',
    '高一高二共用音乐美术老师和专用教室，请检查资源是否够用并提出错峰方案。',
    '高一从20班改为21班，会增加多少教师课时和教室？列出受影响对象。',
    '在刚才方案上数学加1节，心理隔周上，教师工作量改14节，重新计算并列出差异。',
    '学生档案1000人，行政班只有980人，查清差异再判断需要几个班。',
    '完成全校资源检查，超时后继续已完成步骤，最后给报告。',
    '期中考试监考怎么安排？检查老师和考场冲突，再给调整方案。',
    '这次月考考场够不够，监考老师要怎么协调？',
]

QUERY_QUESTIONS = [
    '高一现在有多少学生？', '当前学校课表模式是什么？', '规划模式是什么意思？',
    '学校有多少教室和教师？', '高二走班是什么意思？',
    '心理隔周上课是什么意思？', '查看高一各科教师工作量',
    '查询这次排课失败日志', '数学老师下周三有没有课？',
    '查看期中考试日程', '列出本校考试',
]


@pytest.mark.asyncio
@pytest.mark.parametrize('question', PLANNING_QUESTIONS)
async def test_complex_paraphrases_remain_planning_when_classifiers_unavailable(question):
    turns = [{'role': 'user', 'content': '给高一做两个方案'},
             {'role': 'assistant', 'content': '方案一20班，方案二21班'},
             {'role': 'user', 'content': question}]
    decision = await IntentGateway().classify(None, question, recent_turns=turns)
    assert decision.effective_mode is ExecutionMode.PLANNING
    assert not decision.write_requested


@pytest.mark.asyncio
@pytest.mark.parametrize('question', QUERY_QUESTIONS)
async def test_focused_queries_are_not_promoted_by_planning_keywords(question):
    decision = await IntentGateway().classify(None, question)
    assert decision.effective_mode is ExecutionMode.QUERY


@pytest.mark.asyncio
@pytest.mark.parametrize('question', [q for q in QUERY_QUESTIONS
    if q.startswith(('查看', '查询', '列出')) or '有没有课' in q or '模式是什么' in q or '模式是什么意思' in q])
async def test_explicit_queries_override_a_semantic_planning_false_positive(question):
    from app.ai.intent.gateway import IntentDecision, AssistantIntent
    async def incorrect_classifier(*args):
        return IntentDecision(AssistantIntent.DIAGNOSIS, 0.95, 'semantic')
    decision = await IntentGateway(incorrect_classifier).classify(None, question)
    assert decision.effective_mode is ExecutionMode.QUERY
