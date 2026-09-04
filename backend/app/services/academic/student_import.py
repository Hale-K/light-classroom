"""学生档案导入：模板解析、当前届别上下文和行级校验。"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class ImportContext:
    entry_year: int
    academic_year: str
    term: str
    cohort_label: str


def context_from_config(value: dict | None) -> ImportContext:
    value = value or {}
    entry_year = int(value.get("current_entry_year") or 0)
    academic_year = str(value.get("current_academic_year") or "")
    term = str(value.get("current_term") or "1")
    if entry_year < 2000 or "-" not in academic_year or term not in {"1", "2"}:
        raise ValueError("请先在系统设置中配置当前届别、学年和学期")
    return ImportContext(entry_year, academic_year, term, str(entry_year))


def _xlsx_rows(data: bytes) -> list[dict[str, str]]:
    """用标准库读取简单 Excel 模板，避免导入功能依赖本地 Office。"""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for item in root.findall("x:si", ns):
                shared.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
        sheet = workbook.find("x:sheets/x:sheet", ns)
        if sheet is None:
            return []
        target = rel_map[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
        sheet_path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        root = ET.fromstring(archive.read(sheet_path))
        rows: list[list[str]] = []
        for row in root.findall(".//x:sheetData/x:row", ns):
            values: list[str] = []
            for cell in row.findall("x:c", ns):
                value = cell.find("x:v", ns)
                text = value.text if value is not None and value.text else ""
                if cell.attrib.get("t") == "s" and text.isdigit():
                    text = shared[int(text)] if int(text) < len(shared) else ""
                values.append(text.strip())
            rows.append(values)
        if not rows:
            return []
        headers = [item.strip() for item in rows[0]]
        return [dict(zip(headers, row)) for row in rows[1:] if any(item.strip() for item in row)]


def parse_rows(filename: str, data: bytes) -> list[dict[str, str]]:
    lower = filename.lower()
    if lower.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            candidates = [name for name in archive.namelist() if name.lower().endswith((".xlsx", ".csv")) and not name.endswith("/")]
            if len(candidates) != 1:
                raise ValueError("ZIP 中必须包含且只能包含一个学生档案 Excel/CSV 文件")
            return parse_rows(candidates[0], archive.read(candidates[0]))
    if lower.endswith(".xlsx"):
        return _xlsx_rows(data)
    if lower.endswith(".csv"):
        return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    raise ValueError("仅支持 .xlsx 或 .csv 文件；ZIP 请上传包含 Excel 模板的压缩包")


def normalize_gender(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return {"男": "male", "男生": "male", "male": "male", "女": "female", "女生": "female", "female": "female"}.get(value)
