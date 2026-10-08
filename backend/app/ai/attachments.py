"""Bounded, ephemeral document parsing for the assistant composer."""
from __future__ import annotations

import hashlib
import io
from pathlib import PurePath
from zipfile import ZipFile

from app.ai.knowledge.ingest import parse_document

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 12000
MAX_CONTEXT_CHARS = 24000
MAX_ANALYSIS_CHARS = 3000
SUPPORTED_SUFFIXES = {'.txt', '.md', '.markdown', '.csv', '.json', '.pdf', '.docx', '.xlsx'}


def _number_or_none(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(',', '').replace('%', '').strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _column_stats(rows: list[list], *, max_columns: int = 30) -> list[str]:
    """对表格式内容做数值列统计（表头取首行；min/max/合计/均值），供模型直接分析。"""
    if len(rows) < 2:
        return []
    width = min(max(len(r) for r in rows[:50]), max_columns)
    headers = [str(rows[0][i])[:40] if i < len(rows[0]) and str(rows[0][i]).strip() else f'列{i + 1}' for i in range(width)]
    stats: list[dict] = []
    for column in range(width):
        numbers = []
        for row in rows[1:]:
            value = _number_or_none(row[column]) if column < len(row) else None
            if value is not None:
                numbers.append(value)
        if len(numbers) >= 2:
            stats.append({
                'header': headers[column] if column < len(headers) else f'列{column + 1}',
                'count': len(numbers),
                'min': min(numbers), 'max': max(numbers),
                'sum': sum(numbers),
            })
    lines = []
    for item in stats:
        lines.append(
            f"  列「{item['header']}」：数值 {item['count']} 个，最小 {item['min']:g}，"
            f"最大 {item['max']:g}，合计 {item['sum']:g}"
        )
    return lines


def _tabular_analysis(name: str, rows: list[list], *, scanned_note: str = '') -> str:
    lines = [f'结构：{max(len(r) for r in rows[:1]) if rows else 0} 列 × {len(rows)} 行（含表头）{scanned_note}']
    lines.extend(_column_stats(rows))
    return '\n'.join(lines[: MAX_ANALYSIS_CHARS // 40])


def _xlsx_analysis(workbook) -> str:
    lines = []
    for sheet in workbook:
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        if not rows:
            lines.append(f'工作表「{sheet.title}」：空表')
            continue
        lines.append(f'工作表「{sheet.title}」：')
        lines.append(_tabular_analysis(sheet.title, rows))
    return '\n'.join(lines)


def _csv_analysis(text: str) -> str:
    import csv as csv_module
    rows = list(csv_module.reader(io.StringIO(text)))
    if len(rows) > 400:
        rows = rows[:400]
        note = '（仅统计前 400 行）'
    else:
        note = ''
    return _tabular_analysis('csv', rows, scanned_note=note)


def parse_attachment(name: str, data: bytes) -> dict:
    # Never use a client filename as a filesystem path or extract an archive.
    if not name or len(name) > 200 or '/' in name or '\\' in name or any(ord(c) < 32 for c in name):
        raise ValueError('文件名无效')
    suffix = PurePath(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError('支持 TXT、Markdown、CSV、JSON、PDF、DOCX、XLSX；图片识别尚未接入')
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError('文件为空或超过 5 MB')
    if suffix in {'.docx', '.xlsx'}:
        with ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 1000 or sum(item.file_size for item in members) > 30 * 1024 * 1024:
                raise ValueError('文档解压体积过大')
    analysis = ''
    if suffix in {'.txt', '.md', '.markdown', '.csv', '.json'}:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('gb18030')
        if '\x00' in text:
            raise ValueError('不是可读取的文本文件')
        if suffix == '.csv':
            analysis = _csv_analysis(text)
    elif suffix == '.xlsx':
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts = []
        scanned_chars = 0
        stopped_early = False
        try:
            for sheet in workbook:
                heading = f'工作表：{sheet.title}\n'
                parts.append(heading)
                scanned_chars += len(heading)
                for row in sheet.iter_rows(values_only=True):
                    line = '\t'.join('' if value is None else str(value) for value in row) + '\n'
                    parts.append(line)
                    scanned_chars += len(line)
                    if scanned_chars > MAX_TEXT_CHARS:
                        stopped_early = True
                        break
                if stopped_early:
                    break
            text = ''.join(parts)
            analysis = _xlsx_analysis(workbook) + ('（正文因长度截断，统计覆盖可见部分）' if stopped_early else '')
        finally:
            workbook.close()
    elif suffix == '.docx':
        from docx import Document
        document = Document(io.BytesIO(data))
        parts = []
        tables = 0
        paragraphs = 0
        for block in document.iter_inner_content():
            if hasattr(block, 'rows'):
                tables += 1
                parts.extend('\t'.join(cell.text for cell in row.cells) for row in block.rows)
            else:
                paragraphs += 1
                parts.append(block.text)
        text = '\n'.join(parts)
        analysis = f'结构：段落 {paragraphs} 个，表格 {tables} 张'
    else:
        parsed = parse_document(name, data)
        text = parsed.text
        analysis = f'结构：PDF {len(parsed.pages)} 页，正文 {len(text)} 字'
    text = text.strip()
    if not text:
        raise ValueError('未读取到文字；扫描版 PDF 暂不支持，请使用含文字的文档')
    return {
        'id': hashlib.sha256(data).hexdigest(), 'name': name,
        'text': text[:MAX_TEXT_CHARS], 'truncated': len(text) > MAX_TEXT_CHARS,
        # A bounded spreadsheet scan cannot claim the full document's length.
        'original_chars': None if suffix == '.xlsx' and stopped_early else len(text),
        'analysis': analysis[:MAX_ANALYSIS_CHARS],
    }
