"""Tool Gateway: per-turn authorization, dispatch, proposal state, and audit."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from decimal import Decimal
import json
import re

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.actions import PROPOSE_RULES_TOOL, RulesProposal, action_view, propose_rules
from app.ai.runs.events import TraceCallback
from app.ai.tools.school import SCHOOL_TOOLS, _term, execute_school_tool
from app.ai.tools.school import evidence
from app.ai.tools.school.common import _tool_response
from app.ai.tools.markdown import FORMAT_MARKDOWN_TOOL, format_markdown, hour_columns, hour_tables, hour_value
from app.ai.tools.task_plan import TASK_PLAN_TOOLS, execute_task_plan


def _explicit_fixed_hours(query: str) -> dict[str, float]:
    """Recognize explicit course-hour declarations; do not infer unknown prose.

    This intentionally covers bounded, reviewable declarations rather than
    claiming arbitrary language understanding. Conflicting numbers stay unset.
    """
    names = '心理健康|思想政治|语文|数学|英语|物理|化学|生物|政治|历史|地理|体育|音乐|心理|美术'
    numerals = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    pattern = re.compile(rf'(?P<subject>{names})(?:课)?\s*'
        r'(?:(?:设置|设|固定|安排)?为|[:：=+＋]|每周|各|加)?\s*'
        r'(?P<hours>\d+(?:\.\d+)?|[零一二两三四五六七八九十])'
        r'(?:\s*节|(?=\s*(?:[,，、;；。+\n]|$)))')
    seen: dict[str, set[float]] = {}
    for match in pattern.finditer(query):
        # Optional alternatives and explicit extra increments are not a fixed
        # final value. Such wording requires the normal model clarification.
        if re.match(r'\s*(?:或|到|至|[-~～])', query[match.end():]):
            continue
        prefix = query[max(0, match.start() - 3):match.start()]
        if re.search(r'(?:减少|不排|取消|去掉|不加|别加)$', prefix):
            continue
        number = match['hours']
        value = float(numerals[number]) if number in numerals else float(number)
        seen.setdefault(match['subject'], set()).add(value)
    return {subject: next(iter(values)) for subject, values in seen.items() if len(values) == 1}


def _fixed_rows_error(text: str, fixed: dict[str, float]) -> str | None:
    """Check declared subject rows across every proposed numeric table column."""
    tables = re.findall(r'(?:^[ \t]*\|.*\|[ \t]*(?:\n|$))+', text, re.M)
    checked = 0
    for table in tables:
        rows = [[cell.strip().replace('**', '') for cell in line.strip().strip('|').split('|')]
                for line in table.strip().splitlines()]
        if len(rows) < 3 or not re.search(r'科目|课程|学科', rows[0][0]):
            continue
        columns = [index for index, label in enumerate(rows[0][1:], 1)
            if re.search(r'方案|建议|课时|节数|周课|单周|双周', label)
            and not re.search(r'当前|现状|原有|已配', label)]
        if not columns:
            continue
        checked += 1
        for subject, expected in fixed.items():
            matches = [row for row in rows[2:] if row and (re.sub(r'\s*[（(].*', '', row[0]).strip()
                in (subject, subject + '课', '心理健康' if subject == '心理' else subject))]
            if len(matches) != 1:
                return f'用户指定的{subject}{expected:g}节缺失或重复。每个建议方案须保留该科目，不可替换为其他课程。'
            for index in columns:
                cell = matches[0][index] if index < len(matches[0]) else ''
                value = re.match(r'^(\d+(?:\.\d+)?)\s*(?:节)?(?=$|\s|[（(])', cell)
                if value is None or Decimal(value[1]) != Decimal(str(expected)):
                    return f'用户指定{subject}{expected:g}节，表格「{rows[0][index]}」却是{cell or "空值"}。请保留原要求再验算。'
    if not checked:
        return '请将用户指定固定课程逐科写入方案课时表并保留原数量，不可只在段落中承诺已保留。'
    return None


def _scenario_rank(label: str) -> int | None:
    match = re.search(r'方案\s*([一二三123ABCabc])|第\s*([一二三123])\s*套', label)
    if match:
        return {'一': 1, '二': 2, '三': 3, '1': 1, '2': 2, '3': 3,
                'a': 1, 'b': 2, 'c': 3}[next(value for value in match.groups() if value).lower()]
    return None


def _validated_rows_error(text: str, validation: dict) -> str | None:
    """Final quantities must be the exact scenarios that the server checked."""
    scenarios = validation.get('scenarios', [])
    covered: dict[int, set[str]] = {}

    def matching(label: str) -> list[int]:
        clean = re.sub(r'\s|\*|[（(].*?[）)]', '', label).lower()
        exact = [index for index, scenario in enumerate(scenarios)
            if (name := re.sub(r'\s|\*|[（(].*?[）)]', '', scenario['name']).lower()) and name in clean]
        if exact:
            return exact
        rank = _scenario_rank(label)
        if rank is not None:
            by_rank = [index for index, scenario in enumerate(scenarios)
                       if _scenario_rank(scenario['name']) == rank]
            return by_rank or ([rank - 1] if rank <= len(scenarios) else [])
        return []

    for heading, rows in hour_tables(text):
        for column in hour_columns(rows[0], proposed_only=True):
            header = rows[0][column]
            candidates = matching(header) or matching(heading)
            if not candidates and len(scenarios) == 1:
                candidates = [0]
            if len(candidates) != 1:
                return f'课时表「{header}」无法唯一对应最后验算的方案。请明确方案名称，按各方案原结果列示，不能靠列顺序猜测。'
            scenario_index = candidates[0]
            scenario = scenarios[scenario_index]
            expected: dict[str, dict[str, Decimal]] = {}
            for item in scenario.get('subjects', []):
                hours = Decimal(str(item['periods']))
                legs = ('odd', 'even') if item.get('week_parity', 'all') == 'all' else (item['week_parity'],)
                subject = expected.setdefault(item['subject'], {'odd': Decimal(0), 'even': Decimal(0)})
                for leg in legs:
                    subject[leg] += hours
            leg = 'odd' if '单周' in header and '双周' not in header else (
                'even' if '双周' in header and '单周' not in header else None)
            shown: set[str] = set()
            for row in rows[2:]:
                subject = re.sub(r'\s*[（(].*', '', row[0]).strip()
                if re.search(r'小计|剩余|课位|选修合计', subject):
                    continue
                total = subject in {'合计', '总计'}
                if subject not in expected and subject.endswith('课') and subject[:-1] in expected:
                    subject = subject[:-1]
                if not total and subject not in expected:
                    return f'最终方案新增或替换了未验算科目「{subject}」。请重新验算，不能直接交付另一组数字。'
                if not total and subject in shown:
                    return f'课时表「{header}」重复列出{subject}，无法对应最后验算结果。'
                values = ({parity: sum((item[parity] for item in expected.values()), Decimal(0))
                           for parity in ('odd', 'even')} if total else expected[subject])
                if leg is None and values['odd'] != values['even']:
                    return f'课时表「{header}」{subject}的单双周课时不同，须分列单周{values["odd"]}节、双周{values["even"]}节，不可用单一数字替代。'
                wanted = values[leg or 'odd']
                cell = row[column] if column < len(row) else ''
                value = hour_value(cell)
                if value is None or value != wanted:
                    return f'课时表「{header}」{subject}写成{cell or "空值"}，最后验算的「{scenario["name"]}」为{wanted}节。请按验算结果输出或重新验算。'
                if not total:
                    shown.add(subject)
            missing = expected.keys() - shown
            if missing:
                return f'课时表「{header}」缺少最后验算的科目：{"、".join(sorted(missing))}。须逐科完整列出，不能漏项改变方案。'
            covered.setdefault(scenario_index, set()).add(leg or 'all')
    if not covered:
        return '最终课时方案缺少可核对的科目表。请将验算结果逐科列出，并明确各方案与单双周。'
    missing_scenarios = [scenario['name'] for index, scenario in enumerate(scenarios) if index not in covered]
    if missing_scenarios:
        return f'最终课时表缺少已验算方案：{"、".join(missing_scenarios)}。请完整列示各方案或明确哪些方案因校验失败无法交付。'
    for index, legs in covered.items():
        if 'all' not in legs and legs != {'odd', 'even'}:
            return f'课时表「{scenarios[index]["name"]}」只列出一个周次，须同时列出单周与双周，保留完整验算范围。'
    return None


def _negative_claim(text: str, start: int) -> bool:
    prefix = re.split(r'[。；;,，\n]', text[max(0, start - 25):start])[-1]
    return bool(re.search(r'(?:尚未|并非|不能|不可|无法|不代表|未能|未|不|不得).{0,15}$', prefix))


def _validation_claim_error(text: str, validation: dict, numeric_table: bool) -> str | None:
    if not validation.get('all_valid'):
        for claim in re.finditer(
            r'all[_ ]?valid\s*(?:[:=：]\s*)?(?:true|真)|(?:全部|均|都|三[个套案]).{0,12}(?:通过|可执行|可直接实施)|(?:校验|验证).{0,8}(?:全部|均|都).{0,5}通过', text, re.I):
            if _negative_claim(text, claim.start()):
                continue
            clause = re.split(r'[。；;\n]', text[max(0, claim.start() - 35):claim.end() + 20])
            numeric_claim = any(claim[0] in item and re.search(r'数值|数字|课量|容量|课时验算|课时合计|课时约束|固定科目', item)
                and not re.search(r'all[_ ]?valid|可执行|实施', item, re.I) for item in clause)
            if numeric_claim and validation.get('all_numeric_constraints_valid'):
                continue
            return ('程序验算未全部通过，不可声称all_valid或三案均可执行。'
                    '保留已核对的局部结果，区分数字约束与科目配置缺失，明确阻塞项后交付；无需反复重查。')
    coverage = validation.get('coverage')
    required = ('teacher_conflicts_verified', 'room_conflicts_verified',
                'mandatory_slot_placement_verified', 'all_rules_verified')
    if coverage and not all(coverage.get(key) for key in required):
        claims = re.finditer(r'可直接(?:实施|执行|排课)|(?:全部|所有|完整|全).{0,6}(?:约束|排课|排满).{0,10}(?:通过|满足|完成|可行)|(?:已|完成|保证|确保).{0,8}(?:完整排课|实际排满)|(?:教师|教室).{0,12}(?:无冲突|均已通过|都已通过)', text)
        if any(not _negative_claim(text, claim.start()) for claim in claims):
            return ('课量聚合验算不能证明完整排课可实施。保留已经验算的课时表，'
                    '明确教师与教室冲突、实际排满待验证，作为方案建议交付；不要虚称全约束通过，也无需重复同一验算。')
        if numeric_table:
            unverified = (r'待验证|待核查|待核对|未验证|未检查|未核实|尚未|尚待|无法验证|没有验证|不保证|不能保证|未做'
                          r'|(?<!不)需[^。\n]{0,40}(?:验证|核查|核对|确认|校验)')
            for aspect in ('教师', '教室', '实际排满|排满|排课落位|落位|实际课表|必排位置'):
                if not re.search(rf'(?:{aspect})[^。\n]{{0,70}}(?:{unverified})|(?:{unverified})[^。\n]{{0,70}}(?:{aspect})', text):
                    return ('课时表可作为已核对的局部成果交付，须明确教师与教室冲突、实际排满待验证。'
                            '补充这一范围说明即可结束，不要反复尝试没有证据的完整排课结论。')
    return None


@dataclass
class ToolScope:
    """A single Turn's immutable authority plus mutable proposal result."""

    session: AsyncSession
    tenant_id: int
    user_id: int | None
    can_manage_rules: bool
    page_context: dict | None
    allowed_tools: frozenset[str] | None = None
    on_trace: TraceCallback | None = None
    plan: dict | None = None
    task_plan: dict | None = None
    _checked_hour_scenarios: bool = False
    _user_fixed_subject_hours: dict[str, float] = field(init=False, default_factory=dict)
    _last_hour_validation: dict | None = field(init=False, default=None)
    _last_hour_scope: dict | None = field(init=False, default=None)
    _required_evidence: set[str] = field(init=False, default_factory=set)
    _attempted_evidence: set[str] = field(init=False, default_factory=set)
    _successful_evidence: set[str] = field(init=False, default_factory=set)
    _permission_denied: bool = field(init=False, default=False)
    _plan_mode: bool = field(init=False, default=False)

    @property
    def permission_denied(self) -> bool:
        """Only set after the actual account authorization rejects an evidence tool."""
        return self._permission_denied

    def __post_init__(self):
        # Snapshot request mode once: neither later page metadata nor model output can unlock it.
        self._plan_mode = (self.page_context or {}).get('assistant_mode') == 'plan'

    def configure_request(self, query: str) -> None:
        """Called only by the server with the actual user turn, never tool args."""
        self._user_fixed_subject_hours = _explicit_fixed_hours(query)
        if re.search(r'查|查询|查看|核对|有哪些|多少|几条', query):
            if re.search(r'个人(?:保存)?课表|(?:已保存|保存的)课表', query):
                self._required_evidence.add('lookup_timetable')
            if re.search(r'学生选科|选科状态|入班情况', query):
                self._required_evidence.add('lookup_student_choices')

    @property
    def user_fixed_subject_hours(self) -> dict[str, float]:
        return dict(self._user_fixed_subject_hours)

    @property
    def checked_hour_evidence(self) -> dict | None:
        """Only the last authorized, server-checked result; never a model draft."""
        if not self._checked_hour_scenarios or self._last_hour_validation is None:
            return None
        return deepcopy({'scope': self._last_hour_scope, 'data': self._last_hour_validation})

    async def environment(self) -> dict:
        """在模型答复前核对学校环境；不依赖模型是否记得调用工具。"""
        unverified = {'ok': False, 'code': 'ENVIRONMENT_UNVERIFIED',
                      'message': '学校环境未能核实；先澄清或查询，不能猜测模式、学年学期与现状。'}
        if self.session is None:
            return unverified
        try:
            result = json.loads(await execute_school_tool('lookup_school_context', '{}',
                session=self.session, tenant_id=self.tenant_id))
            if result.get('ok') and result.get('code') == 'OK':
                self._successful_evidence.add('lookup_school_context')
                return result
        except Exception:
            pass
        return unverified

    @property
    def definitions(self) -> list[dict]:
        tools = [*SCHOOL_TOOLS, FORMAT_MARKDOWN_TOOL, *TASK_PLAN_TOOLS, *([PROPOSE_RULES_TOOL] if self.can_manage_rules else [])]
        if self._plan_mode:
            tools = [item for item in tools if item['function']['name'] != 'propose_rules']
        if self.allowed_tools is None:
            return tools
        return [item for item in tools if item["function"]["name"] in self.allowed_tools]

    async def final_guard(self, text: str) -> str | None:
        if self._permission_denied and re.search(r'菜单|页面入口|账号管理|页面操作|页面上.*筛选|页面.*查看明细', text):
            return ('内部执行检查：本轮查询已被实际账号权限拒绝。只说明缺少权限，建议联系本校管理员核对账号。'
                    '删除未经核实的菜单入口和页面操作建议，不能暗示通过页面绕过权限；不要沿用历史回复中的入口。')
        for tool in self._required_evidence - self._successful_evidence:
            if (tool in self._attempted_evidence
                    and re.search(r'无权限|权限|查询失败|无法查询|未能查询|未匹配|请提供|请补充|未唯一匹配', text)
                    and not re.search(r'已查询|已核对|查得|已确认', text)):
                continue
            return (f'内部执行检查：本轮现状查询尚无{tool}成功返回。先查询用户指定对象与学期；'
                    '历史回复不能当成本轮已查询结果。查询失败或无权限时明确说明缺项，不要编造记录。')
        if self.allowed_tools and 'plan_task' in self.allowed_tools and not self.task_plan:
            return ('内部执行检查：复杂任务尚未建立执行计划。先调用plan_task记录步骤，'
                    '再按真实进展更新；缺少范围时可标blocked并询问，不可跳过规划直接结束。')
        if self.task_plan and any(item.get('status') in {'pending', 'running'}
                                 for item in self.task_plan.get('steps', [])):
            return ('内部执行检查：计划仍有未结束步骤。先按真实证据更新状态；'
                    '完成用completed，缺数据用blocked，失败用failed。不得把未验证项虚标完成，再交付完整答复。')
        subject_tables = list(hour_tables(text))
        numeric_scenarios = ((not subject_tables and '方案' in text and bool(re.search(r'\|\s*(?:\*\*)?\d', text)))
            or any(hour_columns(rows[0], proposed_only=True)
                   and any(re.match(r'^\d', cell) for row in rows[2:] for cell in row[1:])
                   for _, rows in subject_tables))
        if self._user_fixed_subject_hours and numeric_scenarios:
            error = _fixed_rows_error(text, self._user_fixed_subject_hours)
            if error:
                return '内部执行检查：' + error
        if self._last_hour_validation and numeric_scenarios:
            validation = self._last_hour_validation
            if error := _validated_rows_error(text, validation):
                return '内部执行检查：' + error
            unknown = {issue.get('subject') for scenario in validation.get('scenarios', [])
                for issue in scenario.get('errors', []) if issue.get('code') == 'UNKNOWN_SUBJECT'}
            for subject in unknown - {None}:
                missing = r'未建|未建立|不存在|未配置|待建|缺少|缺失|尚未.{0,4}(?:建立|配置)'
                if not re.search(rf'{re.escape(subject)}.{{0,35}}(?:{missing})|(?:{missing}).{{0,35}}{re.escape(subject)}', text, re.S):
                    return f'内部执行检查：科目「{subject}」未在科目库匹配。可以保留其课时提供临时建议，必须明确待建科目，不能声称已可执行或用另一科替代。'
        if self._last_hour_validation:
            if error := _validation_claim_error(text, self._last_hour_validation, numeric_scenarios):
                return '内部执行检查：' + error
        # A numeric multi-scenario answer needs programmatic evidence. A question
        # or a missing-scope clarification can end without inventing a scenario.
        if (self.allowed_tools and 'plan_task' in self.allowed_tools
                and '课时' in text and re.search(r'方案[一二三123]|方案\s*[ABC]|第[一二三123]套', text)
                and re.search(r'\|\s*\d', text) and not self._checked_hour_scenarios):
            return ('内部执行检查：多方案课时数字尚无程序验算。先调用validate_hour_scenarios，'
                    '根据真实课位和固定课程检查；失败则修正或明确无法实施原因，不能假称校验通过。')
        return None

    async def execute(self, name: str, arguments: str) -> str:
        allowed = {item["function"]["name"] for item in self.definitions}
        if name not in allowed:
            if self.on_trace:
                await self.on_trace("tool.denied", {"tool": name, "reason": "not_allowed"})
            return "工具未被授权，已拒绝执行。"
        if name == "format_markdown":
            return format_markdown(arguments)
        if name in {'plan_task', 'update_plan_task'}:
            result, self.task_plan = execute_task_plan(name, arguments, self.task_plan)
            return result
        if name in evidence.DESCRIPTIONS or name in {'lookup_planning_basis', 'validate_hour_scenarios', 'lookup_walk_classes'}:
            self._attempted_evidence.add(name)
            try:
                permitted = await evidence.authorized(self.session, self.tenant_id, self.user_id)
            except Exception:
                return _tool_response(name, ok=False, code='TOOL_UNAVAILABLE', retryable=True,
                    message='暂时无法核对查询权限，请稍后重试。')
            if not permitted:
                self._permission_denied = True
                if self.on_trace:
                    await self.on_trace('tool.denied', {'tool': name, 'reason': 'management_required'})
                return _tool_response(name, ok=False, code='FORBIDDEN',
                    message='该查询包含学校级任课、课表或学生名单，需要教务管理人员权限。')
        if name != "propose_rules":
            if name == 'validate_hour_scenarios':
                self._checked_hour_scenarios = False
                self._last_hour_validation = None
                self._last_hour_scope = None
                try:
                    values = json.loads(arguments or '{}')
                    if isinstance(values, dict) and self._user_fixed_subject_hours:
                        supplied = values.get('fixed_subject_hours') or {}
                        if isinstance(supplied, dict):
                            values['fixed_subject_hours'] = {**supplied, **self._user_fixed_subject_hours}
                            arguments = json.dumps(values, ensure_ascii=False)
                except ValueError:
                    pass
            result = await execute_school_tool(
                name,
                arguments,
                session=self.session,
                tenant_id=self.tenant_id,
                page_context=self.page_context,
            )
            try:
                if json.loads(result).get('ok') is True:
                    self._successful_evidence.add(name)
            except (ValueError, AttributeError):
                pass
            if name == 'validate_hour_scenarios':
                try:
                    payload = json.loads(result)
                    self._checked_hour_scenarios = payload.get('ok') is True and isinstance(
                        (payload.get('data') or {}).get('scenarios'), list)
                    if self._checked_hour_scenarios:
                        self._last_hour_validation = payload['data']
                        self._last_hour_scope = payload.get('scope')
                except (ValueError, AttributeError):
                    pass
            return result
        return await self._propose_rules(arguments)

    async def _propose_rules(self, arguments: str) -> str:
        if self._plan_mode:
            return '计划模式仅提供方案，已拒绝生成规则草稿。'
        if not self.can_manage_rules or self.user_id is None:
            return "当前账号没有排课配置权限，请由教务管理员确认配置。"
        if self.plan is not None:
            return "本轮已经生成草稿，请先让老师核对，下一轮再修改。"
        try:
            year, term = await _term(self.session, self.tenant_id) if self.page_context else (None, None)
            context = self.page_context or {}
            if (
                (context.get("academic_year") and context["academic_year"] != year)
                or (context.get("term") and context["term"] != term)
            ):
                return (
                    "当前页面与学校当前学期不同。规则草稿暂只支持学校当前学期，"
                    "请先切换页面或到规则工作台手动配置，不能改到另一个学期。"
                )
            proposal = RulesProposal.model_validate_json(arguments)
            action = await propose_rules(self.session, self.tenant_id, self.user_id, proposal)
            self.plan = action_view(action)
            return "草稿已准备，尚未保存规则：\n" + self.plan["summary"]
        except ValueError as exc:
            return "草稿未生成，请澄清：" + str(exc)[:700]


class ToolGateway:
    """Creates a fresh, tenant-scoped tool boundary for each Agent Turn."""

    def open_scope(
        self,
        *,
        session: AsyncSession,
        tenant_id: int,
        user_id: int | None,
        can_manage_rules: bool,
        page_context: dict | None,
        allowed_tools: frozenset[str] | None = None,
        on_trace: TraceCallback | None = None,
    ) -> ToolScope:
        return ToolScope(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            can_manage_rules=can_manage_rules,
            page_context=page_context,
            allowed_tools=allowed_tools,
            on_trace=on_trace,
        )
