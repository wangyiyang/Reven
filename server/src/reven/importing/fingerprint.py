"""Structure fingerprint — 提取 Excel 结构元数据，不搬运全量数据。

输出是模板匹配的输入。只分析：
- 前 20 行（含标题、筛选条件、表头）
- 尾 5 行（含合计/页码）
- 合并单元格坐标
- 每列非空密度
- 数据行类型分布
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

import openpyxl

_NON_DATA_KEYWORDS: set[str] = {
    "销货单明细表",
    "现存量查询",
    "库存SKU",
    "品类库存",
    "格力空调",
    "单据日期",
    "价格以当天",
    "价格以",
    "量大价优",
}


@dataclass
class RowProfile:
    """单行样本分析。"""

    index: int
    """行号（1-based）。"""

    non_empty_count: int
    """非空单元格数。"""

    total_cells: int
    """总单元格数。"""

    cell_types: dict[str, int] = field(default_factory=dict)
    """值类型分布 {"string": 5, "number": 3, "date": 1, "empty": 10}。"""

    is_footer: bool = False
    """是否判定为页脚行。"""

    is_header_like: bool = False
    """是否判定为表头行。"""

    sample_values: list[str] = field(default_factory=list)
    """前 5 个非空值的字符串表示（长度≤30）。"""


@dataclass
class SheetFingerprint:
    """单个 sheet 的结构指纹。"""

    index: int
    name: str
    total_rows: int
    total_cols: int
    merged_cells: list[dict[str, Any]] = field(default_factory=list)
    header_candidates: list[RowProfile] = field(default_factory=list)
    footer_candidates: list[RowProfile] = field(default_factory=list)
    column_density: list[int] = field(default_factory=list)
    """/总行数 ×100，每列的非空百分比。"""
    data_region: dict[str, int] = field(default_factory=dict)
    """探测到的数据区域 {start_row, end_row, start_col, end_col}。"""
    header_signature: list[str] = field(default_factory=list)
    """表头行列名集合（从左到右，去空）。"""


@dataclass
class StructureFingerprint:
    """完整文件的结构指纹。"""

    filename: str
    file_size: int
    sheets: list[SheetFingerprint] = field(default_factory=list)
    best_sheet_index: int = 0
    """数据最丰富的 sheet 索引。"""


def _classify_cell_type(value: object) -> str:
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", value):
            return "date"
        if re.match(r"^-?\d+([.,]\d+)?$", value):
            return "number_str"
        return "string"
    return "other"


def _is_header_like(vals: list[object], total: int) -> bool:
    """一行是否像列标题：高填充率 + 主要类型为字符串。"""
    non_empty = [v for v in vals if v is not None]
    if not non_empty or total == 0:
        return False
    ratio = len(non_empty) / total
    if ratio < 0.4:
        return False
    str_count = sum(1 for v in non_empty if isinstance(v, str) and not re.match(r"^-?\d+(\.\d+)?$", str(v)))
    return str_count >= len(non_empty) * 0.5


def _is_footer_like(vals: list[object]) -> bool:
    """一行是否像页脚。

    排除高填充率的表头行：即使含有关键词，只要非空比例 >50% 且
    主要类型为字符串，就不判为页脚。
    """
    text = " ".join(str(v) for v in vals if v is not None)
    if not text.strip():
        return True
    if re.search(r"(第\s*\d+\s*页)|(共\s*\d+\s*页)", text):
        return True
    if re.match(r"^(合计|总计|小计)", text.strip()):
        return True
    # 只有在低填充率时才用关键词判断
    non_empty = [v for v in vals if v is not None]
    fill_ratio = len(non_empty) / len(vals) if vals else 0
    if fill_ratio < 0.4 and any(kw in text for kw in _NON_DATA_KEYWORDS):
        return True
    return False


def profile_rows(sheet: openpyxl.worksheet.Worksheet, start: int, end: int) -> list[RowProfile]:
    """分析指定行范围的样本。"""
    profiles: list[RowProfile] = []
    for r in range(start, end + 1):
        vals = list(sheet.iter_rows(min_row=r, max_row=r, values_only=True))[0]
        total = len(vals)
        non_empty = [v for v in vals if v is not None]

        types: dict[str, int] = {}
        for v in vals:
            t = _classify_cell_type(v)
            types[t] = types.get(t, 0) + 1

        samples = [str(v)[:30] for v in non_empty[:5]]

        profiles.append(
            RowProfile(
                index=r,
                non_empty_count=len(non_empty),
                total_cells=total,
                cell_types=types,
                is_footer=_is_footer_like(list(vals)),
                is_header_like=_is_header_like(list(vals), total),
                sample_values=samples,
            )
        )
    return profiles


def _compute_column_density(sheet: openpyxl.worksheet.Worksheet) -> list[int]:
    """计算每列的非空密度（百分比）。"""
    max_row = sheet.max_row or 0
    max_col = sheet.max_column or 0
    if max_row == 0 or max_col == 0:
        return []

    counts = [0] * max_col
    for row in sheet.iter_rows(min_row=1, max_row=max_row, values_only=True):
        for i, v in enumerate(row):
            if v is not None:
                counts[i] += 1
    return [int(c / max_row * 100) for c in counts]


def fingerprint_sheet(sheet: openpyxl.worksheet.Worksheet, index: int) -> SheetFingerprint:
    """提取单个 sheet 的结构指纹。"""
    max_row = sheet.max_row or 0
    max_col = sheet.max_column or 0

    # 分析前 20 行 + 尾 5 行
    header_profiles = profile_rows(sheet, 1, min(20, max_row))
    footer_profiles = profile_rows(sheet, max(1, max_row - 4), max_row) if max_row > 20 else []

    # 合并单元格信息
    merged = []
    for mr in sheet.merged_cells.ranges:
        merged.append(
            {
                "range": str(mr),
                "min_row": mr.min_row,
                "max_row": mr.max_row,
                "min_col": mr.min_col,
                "max_col": mr.max_col,
            }
        )

    # 列密度
    density = _compute_column_density(sheet)

    # 探测数据区域
    data_region: dict[str, int] = {}
    data_region["start_row"] = _detect_start_row(header_profiles)
    data_region["end_row"] = _detect_end_row(footer_profiles, max_row)
    data_region["start_col"] = _detect_start_col(sheet, data_region["start_row"], data_region["end_row"])
    data_region["end_col"] = max_col

    # 表头列名签名（从探测到的 header row 提取）
    hr = data_region["start_row"]
    header_names: list[str] = []
    if hr >= 1:
        for cell in list(sheet[hr]):
            v = str(cell.value).strip() if cell.value is not None else ""
            if v:
                header_names.append(v)
    header_names = header_names[data_region["start_col"] - 1 :] if data_region["start_col"] > 1 else header_names

    return SheetFingerprint(
        index=index,
        name=sheet.title,
        total_rows=max_row,
        total_cols=max_col,
        merged_cells=merged,
        header_candidates=header_profiles,
        footer_candidates=footer_profiles,
        column_density=density,
        data_region=data_region,
        header_signature=header_names,
    )


def _detect_start_row(profiles: list[RowProfile]) -> int:
    """从前 20 行样本中找到数据起始行。"""
    for i, p in enumerate(profiles):
        if p.is_footer:
            continue
        if p.is_header_like:
            return p.index
        # 以日期开头的行可能是数据第一行
        if p.sample_values and re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", p.sample_values[0]):
            return p.index
    # 兜底：第一条非空的表头
    for p in profiles:
        if p.non_empty_count > 0 and p.non_empty_count >= p.total_cells * 0.3:
            return p.index
    return 1


def _detect_end_row(footer_profiles: list[RowProfile], max_row: int) -> int:
    """从尾 5 行样本中找到数据结束行。"""
    if not footer_profiles:
        return max_row
    for p in reversed(footer_profiles):
        if p.is_footer:
            continue
        # 找到第一个非页脚行
        return p.index
    # 全是页脚或空
    first_footer = None
    for i, p in enumerate(footer_profiles):
        if p.is_footer:
            first_footer = p.index
            break
    return (first_footer - 1) if first_footer else max_row


def _detect_start_col(sheet: openpyxl.worksheet.Worksheet, start_row: int, end_row: int) -> int:
    """检测数据起始列（跳过全空左列）。"""
    if start_row > end_row:
        return 1
    max_col = sheet.max_column or 1
    for col in range(1, min(max_col + 1, 5)):
        non_empty = 0
        total = end_row - start_row + 1
        for row in sheet.iter_rows(min_row=start_row, max_row=end_row, min_col=col, max_col=col, values_only=True):
            if row[0] is not None:
                non_empty += 1
        if total > 0 and non_empty / total >= 0.1:
            return col
    return 1


def fingerprint(data: bytes, filename: str = "") -> StructureFingerprint:
    """提取 Excel 文件的结构指纹。

    Args:
        data: Excel 文件内容（bytes）。
        filename: 文件名（可选，仅用于标记）。

    Returns:
        完整结构指纹。
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        sheets: list[SheetFingerprint] = []
        best_idx = 0
        best_rows = 0

        for i, ws in enumerate(wb.worksheets):
            sf = fingerprint_sheet(ws, i)
            sheets.append(sf)

            # 选数据最丰富的 sheet
            if sf.data_region:
                region_rows = sf.data_region.get("end_row", 0) - sf.data_region.get("start_row", 0) + 1
                if region_rows > best_rows:
                    best_rows = region_rows
                    best_idx = i

        return StructureFingerprint(
            filename=filename,
            file_size=len(data),
            sheets=sheets,
            best_sheet_index=best_idx,
        )
    finally:
        wb.close()


def content_hash(data: bytes) -> str:
    """计算 Excel 文件的数据区内容哈希（用于重复检测）。

    只哈希前 100 行数据，忽略文件元数据差异（如导出时间）。
    """
    import hashlib

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        ws = wb.worksheets[0]
        rows_data: list[str] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 100:
                break
            row_str = "|".join(str(c) if c is not None else "" for c in row[:20])
            rows_data.append(row_str)
        content = "\n".join(rows_data)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    finally:
        wb.close()
