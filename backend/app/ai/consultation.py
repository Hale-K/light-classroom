"""Reviewed replies that need neither school data nor model inference."""
import re

_GENERIC_PROBLEM = re.compile(
    r"(?:你好[，,！!\s]*)?(?:(?:我)?(?:现在)?(?:有|遇到)(?:一些|点|个)?排课问题|排课(?:方面)?(?:有(?:点)?问题|出问题了)|(?:我)?想咨询(?:一下)?排课)[。！!？?\s]*"
)
_FAQ = {
    '联合排课预览会保存吗': '不会。预览只生成候选方案，点击“确认保存”后才会保存课表。',
    '联合排课会排行政课吗': '会。联合排课同时安排行政课和走班课，预览中可以分别查看。',
    '教学班生成会把学生放进去吗': '不会。先生成教学班、设置任课关系，再由联合排课确定学生入班和完整课表。',
}


def consultation_reply(query: str) -> str | None:
    text = query.strip()
    if _GENERIC_PROBLEM.fullmatch(text):
        return '具体遇到了什么问题？可以发报错截图，或说明哪个年级、在哪一步出现异常。'
    # Exact reviewed questions only; never bypass a specific school-data query.
    return _FAQ.get(text.rstrip('。！？?!'))
