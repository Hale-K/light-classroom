"""Local, deterministic presentation tool. No model requests or business writes."""
from __future__ import annotations

import html
import json
import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _text(value):
    if not isinstance(value, str):
        raise ValueError("内容必须是文本")
    if re.search(r"</?(?:think|analysis)\b", value, re.I):
        raise ValueError("只能整理正式答案，不能包含分析块")
    return value.strip()


Text = Annotated[str, BeforeValidator(_text), Field(min_length=1, max_length=2000)]


def _prose(value):
    value = _text(value)
    if re.search(r'\|\s*:?-{3,}:?\s*\|', value) or re.search(r'^\s*\|[^\n]+\|\s*$', value, re.M):
        raise ValueError('正文中的表格必须使用table内容块，不可把Markdown表格塞入summary或paragraph')
    return value


Prose = Annotated[str, BeforeValidator(_prose), Field(min_length=1, max_length=2000)]


class Paragraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["paragraph"]
    title: Text | None = None
    text: Prose


class Items(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["list", "steps"]
    title: Text | None = None
    items: list[Text] = Field(min_length=1, max_length=20)


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["table"]
    title: Text | None = None
    columns: list[Text] = Field(min_length=1, max_length=5)
    rows: list[list[Text]] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def check_width(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("表格每行的单元格数量必须与表头一致")
        return self


class MarkdownAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: Prose
    sections: list[Annotated[Paragraph | Items | Table, Field(discriminator="type")]] = Field(
        default_factory=list, max_length=8)


FORMAT_MARKDOWN_TOOL = {
    "type": "function",
    "function": {
        "name": "format_markdown",
        "description": (
            "将已经确定的正式答案整理为 Markdown 并直接作为最终回复。"
            "summary 为简短结论；sections 按需使用段落、列表、步骤或最多5列表格，可并列三套方案。"
            "summary和paragraph只放正文，Markdown表格必须使用table结构。"
            "多科课时、人数、容量和当前/建议对比使用table，逐对象一行，列明单位及合计；"
            "不把多项数字挤进paragraph或list，已查询现状和未执行建议分别标明。"
            "只整理已有证据，不查询、不验证事实、不修改数据、不输出推理。"
            "须在查询全部完成后单独调用，不与其他工具并行；简单问答无需调用。"
        ),
        "parameters": MarkdownAnswer.model_json_schema(),
    },
}


def _inline(value: str) -> str:
    return html.escape(" ".join(value.split()), quote=False)


def render_markdown(answer: MarkdownAnswer) -> str:
    blocks = [html.escape(answer.summary, quote=False)]
    for section in answer.sections:
        if section.title:
            blocks.append("#### " + _inline(section.title))
        if isinstance(section, Paragraph):
            blocks.append(html.escape(section.text, quote=False))
        elif isinstance(section, Items):
            blocks.append("\n".join(
                (f"{index}. " if section.type == "steps" else "- ") + _inline(item)
                for index, item in enumerate(section.items, 1)))
        else:
            def row(cells):
                return "| " + " | ".join(_inline(cell).replace("|", r"\|") for cell in cells) + " |"
            blocks.append("\n".join([
                row(section.columns), row(["---"] * len(section.columns)),
                *(row(cells) for cells in section.rows),
            ]))
    markdown = "\n\n".join(blocks)
    if len(markdown) > 12000:
        raise ValueError("答案过长，请减少表格行数或拆分内容")
    error = hour_table_error(markdown)
    if error:
        raise ValueError(error)
    return markdown


def hour_tables(markdown: str):
    """Read explicit subject tables together with their closest section heading."""
    for match in re.finditer(r'(?:^[ \t]*\|.*\|[ \t]*(?:\n|$))+', markdown, re.M):
        rows = [[cell.strip().replace('**', '') for cell in line.strip().strip('|').split('|')]
                for line in match[0].strip().splitlines()]
        if len(rows) < 3 or not re.search(r'科目|课程|学科', rows[0][0]):
            continue
        headings = list(re.finditer(r'^\s*#{1,6}\s+([^\n]+)', markdown[:match.start()], re.M))
        yield (headings[-1][1].strip() if headings else ''), rows


def hour_columns(headers: list[str], *, proposed_only=False) -> list[int]:
    return [index for index, label in enumerate(headers[1:], 1)
        if re.search(r'方案|建议|课时|节数|周课|周节|节/周|课量|单周|双周', label)
        and not (proposed_only and re.search(r'当前|现状|原有|已配', label))]


def hour_value(cell: str) -> Decimal | None:
    """A simple quantity may carry nonnumeric notes such as '待建科目'."""
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(?:节)?(?:\s*[（(]([^()（）\d]*)[）)])?', cell)
    if not match or (match[2] and re.search(r'单周|双周|平均|比例', match[2])):
        return None
    return Decimal(match[1])


def _heading_hours(heading: str) -> Decimal | None:
    if '方案' not in heading:
        return None
    amounts = re.findall(r'(?<!第)(\d+(?:\.\d+)?)\s*节', heading)
    if len(amounts) == 1 and not re.search(r'第\s*\d|\d\s*[-至到]\s*\d\s*节', heading):
        return Decimal(amounts[0])
    return None


def hour_table_error(markdown: str) -> str | None:
    """Check additive subject quantities and declared scenario totals."""
    for heading, rows in hour_tables(markdown):
        body = rows[2:]
        if any(row[0] in ('小计', '文化课小计', '术科小计') for row in body):
            continue
        totals = [row for row in body if row[0] in ('合计', '总计')]
        if len(totals) != 1:
            continue
        parts = [row for row in body if row[0] not in ('合计', '总计')]
        proposed = hour_columns(rows[0], proposed_only=True)
        for index in hour_columns(rows[0]):
            header = rows[0][index]
            values = []
            for row in [*parts, totals[0]]:
                cell = row[index] if len(row) > index else ''
                value = hour_value(cell)
                if value is None:
                    break
                values.append(value)
            else:
                actual = sum(values[:-1], Decimal(0))
                if actual != values[-1]:
                    return f'课时表「{header}」分项合计为{actual}节，合计行写成{values[-1]}节。请重新分配并核对总课位，保留用户指定课时；不要只改合计掩盖超量。'
                expected = _heading_hours(header)
                label = header
                if expected is None and index in proposed and len(proposed) == 1:
                    expected, label = _heading_hours(heading), heading
                if expected is not None and expected != actual:
                    return f'课时表标题「{label}」声明{expected}节，但表内分项和合计为{actual}节。须统一方案标题、逐科分配与程序验算结果。'
    return None


def format_markdown(arguments: str) -> str:
    try:
        if len(arguments) > 30000:
            raise ValueError("输入过长")
        markdown = render_markdown(MarkdownAnswer.model_validate_json(arguments))
    except ValueError as exc:
        return json.dumps({"ok": False, "code": "INVALID_ARGUMENT", "message":
            str(exc) if str(exc).startswith('课时表') else
            "整理失败：请提供正式结论和有效内容块，表格行与表头需一致；不要包含分析字段或分析块。"}, ensure_ascii=False)
    return json.dumps({"ok": True, "data": {"markdown": markdown}}, ensure_ascii=False)
