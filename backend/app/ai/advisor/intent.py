"""规则意图：先让模型对照组件目录裂变候选，再按规定格式回答。"""
from __future__ import annotations

import json
import re

from app.ai.model.chat import ChatError, complete_chat
from app.ai.prompt.components import FAMILY, LABELS, catalog_text

_RULE_ASK = re.compile(
    r"规则|组件|禁排|不能排|不排|连堂|连着上|固定|空堂|班主任|对课|轮转|自习日|哪个组件|怎么加"
)

CLASSIFY_SYS = """你只做意图裂变，不要给操作步骤。
对照规则组件目录，根据用户原话和当前页，输出 JSON，不要解释。
格式：
{"candidates":[{"template":"教师课位禁排","why":"班主任+不能排+节次"},{"template":"课位教师角色","why":"也可能是必须班主任上"}],"pick":"教师课位禁排","ask":false,"family":"教师规则","target":"班主任","action":"禁止排课","weekday":"全周","periods":"第5节","avoid":"课位禁排（按学科）；课位教师角色（必须班主任上）"}
要求：
- candidates 2 或 3 个，template 必须是目录里的中文名
- pick 必须是 candidates 之一
- 两种都说得通时 ask=true；能唯一判定时 ask=false
- 用户已说「用组件某某」时 ask=false，pick 用他说的那个
- 班主任不能排某节 → 教师课位禁排，不是课位禁排，也不是课位教师角色
- 某科不能排某节 → 课位禁排
- 某晚必须班主任 → 课位教师角色
- 不要编人名
"""

ANSWER_SYS = """你是轻课堂教务助手。已完成意图裂变，只根据「已判定」写给老师看的步骤。
用简体中文短句。必须按下面结构，不要寒暄，不要说代保存、代点生成、已打开规则组。
当前已在规则组就不要叫他跳页。

组件：<pick>
不要选：<avoid，没有则写无>
操作：
1. 点「规则明细」右上角 +
2. 在「<family>」里选「<pick>」
3. 作用对象：<target>
4. 规则动作：<action>
5. 星期：<weekday>；节次：<periods>
6. 硬约束，点保存
"""


def looks_like_rule_ask(text: str, page_path: str | None = None) -> bool:
    t = (text or "").strip()
    if _RULE_ASK.search(t):
        return True
    path = page_path or ""
    return "tab=rules" in path and len(t) >= 4


def parse_intent_payload(raw: str) -> dict | None:
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    pick = str(data.get("pick") or "").strip()
    if pick not in LABELS:
        return None
    cands = data.get("candidates")
    if not isinstance(cands, list):
        cands = []
    cleaned = []
    for item in cands[:3]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("template") or "").strip()
        if name in LABELS:
            cleaned.append({"template": name, "why": str(item.get("why") or "")[:40]})
    if pick not in {c["template"] for c in cleaned}:
        cleaned.insert(0, {"template": pick, "why": "选定"})
    data["pick"] = pick
    data["candidates"] = cleaned[:3]
    data["family"] = str(data.get("family") or "").strip()
    data["target"] = str(data.get("target") or "按本校对象勾选").strip()
    data["action"] = str(data.get("action") or "").strip()
    data["weekday"] = str(data.get("weekday") or "按你要的星期勾").strip()
    data["periods"] = str(data.get("periods") or "按你要的节次勾").strip()
    data["avoid"] = str(data.get("avoid") or "无").strip()
    if not data.get("family"):
        data["family"] = FAMILY.get(pick, "")
    data["ask"] = bool(data.get("ask"))
    return data


def is_ambiguous(query: str, data: dict) -> bool:
    t = query or ""
    if "用组件" in t:
        return False
    if data.get("ask") is True:
        names = {c["template"] for c in data.get("candidates") or []}
        if "班主任" in t and "教师课位禁排" in names and "课位教师角色" in names:
            has_f = bool(re.search(r"不能排|不排|禁排", t))
            has_m = bool(re.search(r"必须|只能", t))
            if has_f and not has_m:
                return False
            if has_m and not has_f:
                return False
        return True
    names = {c["template"] for c in data.get("candidates") or []}
    if "班主任" in t and "教师课位禁排" in names and "课位教师角色" in names:
        has_f = bool(re.search(r"不能排|不排|禁排", t))
        has_m = bool(re.search(r"必须|只能", t))
        return not (has_f ^ has_m)
    return False


def choices_from_intent(data: dict) -> list[dict]:
    out = []
    for item in data.get("candidates") or []:
        name = item.get("template") or ""
        if name not in LABELS:
            continue
        why = (item.get("why") or "").strip()
        out.append({"label": name, "send": f"用组件{name}。{why}".strip("。")})
    return out[:3]


def clarify_reply(data: dict) -> str:
    names = "、".join(c["template"] for c in data.get("candidates") or [])
    return f"有两种理解，请点下面一个。候选：{names}。"


def think_from_intent(data: dict, *, ask: bool = False) -> list[str]:
    names = " / ".join(c["template"] for c in data.get("candidates") or [])
    lines = []
    if names:
        lines.append(f"裂变候选：{names}")
    if ask:
        lines.append("不能唯一判定，请老师选")
    else:
        lines.append(f"选定组件：{data.get('pick')}")
    return lines


def fallback_reply(data: dict, on_rules: bool) -> str:
    where = "当前就在规则工作台。" if on_rules else "先到排课「规则组」。"
    return "\n".join(
        [
            f"{where}用组件「{data['pick']}」。",
            f"组件：{data['pick']}",
            f"不要选：{data.get('avoid') or '无'}",
            "操作：",
            "1. 点「规则明细」右上角 +",
            f"2. 在「{data.get('family') or '对应分类'}」里选「{data['pick']}」",
            f"3. 作用对象：{data.get('target')}",
            f"4. 规则动作：{data.get('action') or '按组件填写'}",
            f"5. 星期：{data.get('weekday')}；节次：{data.get('periods')}",
            "6. 硬约束，点保存",
        ]
    )


async def classify_rule_intent(
    *,
    query: str,
    page_title: str | None,
    page_path: str | None,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
) -> dict | None:
    raw = await complete_chat(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=min(timeout, 45),
        temperature=0,
        max_tokens=400,
        messages=[
            {
                "role": "system",
                "content": CLASSIFY_SYS + "\n\n" + catalog_text() + f"\n\n当前页：{page_title or ''} {page_path or ''}",
            },
            {"role": "user", "content": query},
        ],
    )
    return parse_intent_payload(raw)


async def answer_rule_intent(
    *,
    query: str,
    data: dict,
    page_title: str | None,
    page_path: str | None,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
) -> str:
    on_rules = "tab=rules" in (page_path or "")
    judged = json.dumps(data, ensure_ascii=False)
    try:
        text = await complete_chat(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            temperature=0.2,
            max_tokens=500,
            messages=[
                {
                    "role": "system",
                    "content": ANSWER_SYS + f"\n\n已判定：{judged}\n当前页：{page_title or ''} {page_path or ''}",
                },
                {"role": "user", "content": query},
            ],
        )
        if "组件：" in text:
            return text
    except ChatError:
        pass
    return fallback_reply(data, on_rules)
