"""Display-only guided questions. Answers remain ordinary user messages."""
import re
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=40, pattern=r'^[a-zA-Z0-9_]+$')
    title: str = Field(min_length=1, max_length=160)
    options: list[str] = Field(min_length=2, max_length=5)

    @model_validator(mode='after')
    def bounded_options(self):
        if any(not value.strip() or len(value) > 120 for value in self.options) or len(set(self.options)) != len(self.options):
            raise ValueError('选项不能为空、重复或超过120字')
        return self


class Clarification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=160)
    known_conditions: list[str] = Field(default_factory=list, max_length=8)
    next_step: str = Field(min_length=1, max_length=300)
    questions: list[Question] = Field(min_length=1, max_length=4)

    @model_validator(mode='after')
    def unique_questions(self):
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError('问题编号不能重复')
        if any(len(value) > 500 for value in self.known_conditions):
            raise ValueError('已知条件过长')
        return self


CLARIFICATION_TOOL = {'type': 'function', 'function': {
    'name': 'request_clarification',
    'description': '关键目标或约束缺失时，展示最多4个逐题选择的引导卡并结束本轮等待。保留用户已明确的信息，只问缺项；学校模式、学年学期优先查询，不让用户重复。每题允许其他补充或暂不确定。不能用此工具确认写入权限。',
    'parameters': Clarification.model_json_schema(),
}}


def is_slot_constraint_statement(query: str) -> bool:
    return bool(re.search(r'课位|节.*(?:排满|必排)', query)
        and re.search(r'必|排满|可.*排', query)
        and not re.search(r'请|帮我|方案|核对|查询|检查|怎么|如何|多少|调整|配置|设置|生成', query))


def restore_clarification(value):
    try:
        return Clarification.model_validate(value).model_dump()
    except (ValidationError, TypeError, ValueError):
        return None


def clarification_text(card: dict) -> str:
    known = '\n'.join('- ' + value for value in card['known_conditions'])
    questions = '\n'.join(f"{i}. {q['title']}" for i, q in enumerate(card['questions'], 1))
    return ('先补充具体的关键决策，我会保留已明确的条件继续处理。\n\n'
        + ('你已说明：\n' + known + '\n\n' if known else '')
        + '待确认计划：' + card['next_step'] + '\n\n' + questions
        + '\n\n等待补充；也可以直接在消息框回答。')


def local_clarification(query: str, page_path: str | None = None) -> dict:
    """Fallback keeps explicit user wording, without claiming verified school data."""
    slots = bool(re.search(r'课位|课时|课节|必.*排|排满', query))
    exam = not slots and bool(re.search(r'排考|考试|监考|考场', query))
    conditions = [part.strip()[:480] + ('（长文本见原消息）' if len(part.strip()) > 480 else '')
        for part in re.split(r'[，,；;\n]', query) if part.strip()] if slots else []
    questions = [dict(id='goal', title='接下来希望我帮你完成什么？', options=(
        ['设计各科课时方案', '核对现有课时是否满足条件', '准备课位规则调整建议'] if slots else
        ['检查排考准备情况', '估算考场与监考需求', '分析已有排考冲突'] if exam else
        ['查询当前情况', '设计或比较方案', '检查问题与冲突']))]
    selected = re.search(r'接下来希望我帮你完成什么[？?]?\s*[:：]\s*([^\n]+)', query)
    if selected and selected[1].strip() == '查询当前情况':
        return Clarification(title='已明确查询目标，请补充查询对象',
            known_conditions=['已明确目标：查询当前情况'],
            next_step='明确对象后查询当前状态，缺少查询能力时说明限制，不再次追问已选择的目标。',
            questions=[dict(id='object', title='需要查询哪个对象或范围？',
                options=['当前页面的配置与状态', '全校排课准备情况', '指定年级的课时与资源'])]).model_dump()
    if slots and not re.search(r'高[一二三123]|初[一二三123]|年级|全校', query):
        questions.append(dict(id='scope', title='这次方案针对哪个年级或范围？', options=['高一', '高二', '高三', '全校']))
    if exam and not re.search(r'期中|期末|月考|考试名称|考试ID', query):
        questions.append(dict(id='exam', title='要处理哪次考试？可在“其他补充”填写名称。', options=['期中考试', '期末考试', '月考']))
    return Clarification(title='补充关键决策后继续', known_conditions=conditions[:8],
        next_step='补充后核对学校环境与相关数据，验算约束，再用表格交付方案。', questions=questions).model_dump()
