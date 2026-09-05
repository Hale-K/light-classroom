"""问不清时只落到教务对象。不枚举其它行业。"""
from __future__ import annotations

import re
from dataclasses import dataclass

_LOW = re.compile(r"快用完|用完了|快没了|不够排|不够了|快满了|用尽")
_STUCK = re.compile(r"卡住|卡死|出不来|一直转|转圈|排不出来")
_TEACHER_HINT = re.compile(r"老师|教师|完成度|课时满|周课时")
_GRID_HINT = re.compile(r"格子|网格|课位|容量")
_GEN_HINT = re.compile(r"生成|红格|标红|求解")
_EVENING = re.compile(r"^晚上$|晚上怎么|晚上的课|晚上排")
_IN_DOMAIN = re.compile(
    r"课|排|班|年级|高[一二三]|老师|教师|档案|网格|格子|课位|规则|生成|学年|科目|"
    r"晚自习|晚课|调课|任教|完成度|节|系统怎么用|教务|连堂|禁排|固定|空堂|"
    r"导入|导出|学生|排座|名单|备课|对课|校区|楼宇|场室|教室|空间|资源|组织|"
    r"人员|账号|角色|权限|考试|考场|监考|试卷|阅卷|成绩|会议"
)

Q_LOW = "你是说一周格子快排满，还是某科课时还没填够，还是某位老师周课时快满了？"
Q_STUCK = "是点了「生成课表」还在转，还是格子已经标红？"
Q_EVENING = "网格里晚自习是第几节？课时里晚课填 0、0.5 或 1，必须先对上课位结构。"
Q_SCOPE = "我主要协助本校教务工作。请告诉我你正在处理的页面或对象，例如学生、教师、空间资源、排课或考试。"


@dataclass(frozen=True)
class ClarifyResult:
    ask: bool
    text: str
    code: str


def clarify(text: str) -> ClarifyResult | None:
    q = (text or "").strip()
    if not q or len(q) > 200:
        return None

    if _LOW.search(q):
        if _TEACHER_HINT.search(q) and not _GRID_HINT.search(q):
            return ClarifyResult(
                False,
                "按教师档案看：完成度接近 100% 表示按网格课时已排满；某位老师周课时是否超上限要到档案或任教里点开看。说姓名或科目我才能查本校人数。",
                "teacher_load",
            )
        if _GRID_HINT.search(q) and not _TEACHER_HINT.search(q):
            return ClarifyResult(
                False,
                "一周能排几节由课位结构决定。总额超过天数×节次就排不下。去排课「课位结构」核对，我不会改网格。",
                "grid_cap",
            )
        return ClarifyResult(True, Q_LOW, "low_ambiguous")

    if _STUCK.search(q) and not re.search(r"导入|登录|验证码", q):
        if _GEN_HINT.search(q) and re.search(r"红|标红", q):
            return ClarifyResult(
                False,
                "红格是冲突或规则不满足。看诊断：课时超额、缺任教、规则互斥。",
                "red_cell",
            )
        return ClarifyResult(True, Q_STUCK, "stuck_ambiguous")

    if _EVENING.search(q) and not re.search(r"0\.5|晚自习|课位", q):
        return ClarifyResult(True, Q_EVENING, "evening_ambiguous")

    if not _IN_DOMAIN.search(q) and not re.search(r"怎么用|第一次", q):
        return ClarifyResult(True, Q_SCOPE, "out_of_scope")

    return None
