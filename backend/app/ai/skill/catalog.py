"""Skill：目录常驻，正文由对话模型选出编号后取回。无向量库、无关键词打分。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "book"
_KEY_RE = re.compile(r"\d{2}-[a-z]+(?:-[a-z]+)*")


@dataclass(frozen=True)
class SkillDoc:
    key: str
    title: str
    when: str
    body: str

    @property
    def always(self) -> bool:
        return self.key.startswith("00") or self.key.startswith("09")


def _parse(path: Path) -> SkillDoc:
    text = path.read_text(encoding="utf-8").strip()
    title = path.stem
    when = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        if line.startswith("何时："):
            when = line.replace("何时：", "", 1).strip()
            break
    return SkillDoc(key=path.stem, title=title, when=when, body=text)


def load_skills() -> list[SkillDoc]:
    files = sorted(p for p in _DIR.glob("*.md") if p.name[:1].isdigit())
    if not files:
        raise RuntimeError(f"助手说明书缺失：{_DIR}")
    return [_parse(p) for p in files]


SKILLS = load_skills()
CORE = [s for s in SKILLS if s.always]
OPTIONAL = [s for s in SKILLS if not s.always]
OPTIONAL_BY_KEY = {s.key: s for s in OPTIONAL}


def catalog_text() -> str:
    lines = ["说明书目录（需要细节时按编号取正文，不要编造目录里没有的流程）："]
    for s in OPTIONAL:
        hint = s.when or s.title
        lines.append(f"- {s.key} {s.title}：{hint}")
    return "\n".join(lines)


def parse_picked_keys(raw: str, *, limit: int = 2) -> list[str]:
    """从模型输出里取出可选说明书编号。核心册 00/09 始终在 system，这里丢掉。"""
    text = (raw or "").strip()
    found: list[str] = []
    start, end = text.find("["), text.rfind("]")
    if 0 <= start < end:
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            found = [str(item).strip() for item in data]
    if not found:
        found = _KEY_RE.findall(text)
    out: list[str] = []
    seen: set[str] = set()
    for key in found:
        if key not in OPTIONAL_BY_KEY or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= limit:
            break
    return out


def skills_for_keys(keys: list[str]) -> list[SkillDoc]:
    return [OPTIONAL_BY_KEY[k] for k in keys if k in OPTIONAL_BY_KEY]


def retrieved_text(keys: list[str]) -> str:
    docs = skills_for_keys(keys)
    if not docs:
        return ""
    return "已取回的说明书：\n\n" + "\n\n".join(s.body for s in docs)


def core_text() -> str:
    return "\n\n".join(s.body for s in CORE)
