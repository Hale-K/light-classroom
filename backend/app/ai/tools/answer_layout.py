"""Recover explicit Markdown block boundaries without changing answer values."""
from __future__ import annotations

import re

_SEPARATOR = re.compile(r'\|[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|')


def _pipe_positions(text: str) -> list[int]:
    positions = []
    for index, character in enumerate(text):
        if character != '|':
            continue
        cursor = index - 1
        while cursor >= 0 and text[cursor] == '\\':
            cursor -= 1
        if (index - cursor - 1) % 2 == 0:
            positions.append(index)
    return positions


def normalize_answer_markdown(text: str) -> str:
    """Only repair headings and complete, explicitly delimited table rows.

    No course, number, title, or aggregate is inferred. Invalid row widths are
    left visible for output validation rather than silently dropping cells.
    """
    result = (text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if '```' in result:
        # Fenced examples are literal user-facing content, not answer blocks.
        return result
    result = re.sub(r'(?<=[^\n])[ \t]+(?=#{1,4}[ \t]+)', '\n\n', result)
    cursor = 0
    for _ in range(12):
        separator = _SEPARATOR.search(result, cursor)
        if separator is None:
            break
        width = len(_pipe_positions(separator[0])) - 1
        preceding = _pipe_positions(result[:separator.start()])
        if len(preceding) < width + 1:
            cursor = separator.end()
            continue
        start = preceding[-width - 1]
        header = result[start:separator.start()].strip()
        if '\n' in header or len(_pipe_positions(header)) != width + 1:
            cursor = separator.end()
            continue
        rows = [header, separator[0]]
        end = separator.end()
        while True:
            next_start = end
            while next_start < len(result) and result[next_start].isspace():
                next_start += 1
            if next_start >= len(result) or result[next_start] != '|':
                break
            positions = _pipe_positions(result[next_start:])
            if len(positions) < width + 1:
                break
            next_end = next_start + positions[width] + 1
            row = result[next_start:next_end]
            if '\n' in row or '####' in row:
                break
            # A closing pipe must end a row; do not guess away extra columns.
            after = result[next_end:next_end + 1]
            if after and not after.isspace() and after != '|':
                break
            tail_line = result[next_end:].split('\n', 1)[0].lstrip()
            if tail_line and not tail_line.startswith('|') and _pipe_positions(tail_line):
                break
            rows.append(row)
            end = next_end
        if len(rows) < 3:
            cursor = separator.end()
            continue
        prefix, suffix = result[:start].rstrip(), result[end:].lstrip()
        block = '\n'.join(rows)
        result = (prefix + '\n\n' if prefix else '') + block + ('\n\n' + suffix if suffix else '')
        cursor = (len(prefix) + 2 if prefix else 0) + len(block)
    return result


def answer_layout_error(text: str) -> str | None:
    """Reject remaining table markup that the renderer cannot treat as a table."""
    if '```' in text:
        return None
    for line in text.splitlines():
        if re.search(r'(?<!#)#{2,4}\s+', line) and not re.match(r'^\s*#{1,4}\s+', line):
            return '回答的标题与正文挤在同一行。请使用分段标题和独立表格，不输出成串Markdown符号。'
        if _SEPARATOR.search(line) and line.count('|') > len(_pipe_positions(_SEPARATOR.search(line)[0])):
            return '表格没有独立换行或列数不一致。请用规范表头、分隔行和逐行明细重新排版，保留原数字后再核对合计。'
    return None
