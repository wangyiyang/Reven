"""Excel parser — 包容人工不确定性的原始网格解析器。

核心设计原则：
- 不假设数据从 (A1) 开始
- 自动检测表头行、数据边界、列偏移
- 跳过空行、页脚合计、页码等非数据行
- 保留原始单元格坐标（血缘追踪的基础）
"""

import io
import re
from datetime import datetime

import openpyxl
from openpyxl.utils import get_column_letter


class ExcelSheetParseResult:
    """解析单个 sheet 的结果。"""

    def __init__(
        self,
        *,
        sheet_name: str,
        rows: list[dict[str, object]],
        coordinates: dict[str, object],
    ) -> None:
        self.sheet_name = sheet_name
        self.rows = rows
        self.coordinates = coordinates


# ── 启发式模式 ─────────────────────────────────────────────

# 用友导出常见的非数据行关键词（标题、筛选条件、页脚）
_NON_DATA_KEYWORDS: set[str] = {
    "销货单明细表",
    "现存量查询",
    "库存SKU",
    "品类库存",
    "格力空调",
    "第1页",
    "第 1 页",
    "合计",
    "小计",
    "单据日期",
    "打印日期",
    "导出日期",
    "价格以当天",
    "价格以",
    "量大价优",
}

# 行内容中检测是否"像表头"的指标
_HEADER_LIKE_THRESHOLD = 0.6  # 非空单元格比例超过此值视为表头行


def _is_footer_row(vals: list[object]) -> bool:
    """判断一行是否像页脚（合计、页码、空行）。"""
    text = " ".join(str(v) for v in vals if v is not None)
    if not text.strip():
        return True
    if re.search(r"(第\s*\d+\s*页)|(共\s*\d+\s*页)", text):
        return True
    if re.search(r"^(合计|总计|小计)", text.strip()):
        return True
    if any(kw in text for kw in ["量大价优", "价格以当天询价"]):
        return True
    return False


def _is_header_row(vals: list[object]) -> bool:
    """判断一行是否像列标题行。

    表头行特征：非空占比高 + 值类型以字符串为主。
    """
    non_empty = [v for v in vals if v is not None]
    if not non_empty:
        return False
    ratio = len(non_empty) / len(vals)
    if ratio < _HEADER_LIKE_THRESHOLD:
        return False
    # 表头行通常以文本为主，数值占比很低
    str_count = sum(1 for v in non_empty if isinstance(v, str))
    return str_count >= len(non_empty) * 0.5


def _detect_data_bounds(
    sheet: "openpyxl.worksheet.Worksheet",  # noqa: F821
) -> tuple[int, int, int, int]:
    """自动检测数据区域的起止行列。

    Args:
        sheet: Openpyxl worksheet object.

    Returns:
        (start_row, end_row, start_col, end_col)
    """
    max_row = sheet.max_row or 0
    max_col = sheet.max_column or 0

    if max_row == 0 or max_col == 0:
        return (1, 0, 1, 0)

    # ── 逐行扫描，找到数据开始行 ──
    start_row = 1
    for r in range(1, min(max_row + 1, 20)):  # 只看前 20 行
        vals = list(sheet.iter_rows(min_row=r, max_row=r, values_only=True))[0]
        non_empty = [v for v in vals if v is not None]

        if not non_empty:
            start_row = r + 1  # 跳过空行
            continue

        text = " ".join(str(v) for v in non_empty)

        # 跳过明显的非数据行
        if any(kw in text for kw in ["单据日期:", "价格以", "量大"]):
            start_row = r + 1
            continue

        # 如果这一行像表头，标记为数据开始
        if _is_header_row(list(vals)):
            start_row = r
            break

        # 如果这一行已经像数据行（以日期开头等）
        if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", str(non_empty[0])):
            start_row = r
            break

        start_row = r + 1

    # ── 从底部扫描，找到数据结束行 ──
    end_row = max_row
    for r in range(max_row, max(start_row, max_row - 5) - 1, -1):
        vals = list(sheet.iter_rows(min_row=r, max_row=r, values_only=True))[0]
        non_empty = [v for v in vals if v is not None]

        if not non_empty:
            if r == end_row:
                end_row = r - 1
            continue

        if _is_footer_row(list(vals)):
            end_row = r - 1
            continue

        break  # 找到最后一行数据

    # ── 检测列偏移 ──
    min_col = 1
    max_col = max_col
    if start_row <= end_row:
        # 检查第一列是否几乎全空，是则偏移到第二列
        first_col_vals = list(
            sheet.iter_rows(
                min_row=start_row,
                max_row=end_row,
                min_col=1,
                max_col=1,
                values_only=True,
            )
        )
        first_col_non_empty = sum(1 for v in first_col_vals if v[0] is not None)
        total_rows_checked = end_row - start_row + 1
        if total_rows_checked > 0 and first_col_non_empty / total_rows_checked < 0.1:
            min_col = 2

    return (start_row, end_row, min_col, max_col)


def _serialize_cell(value: object) -> object:
    """Convert openpyxl cell value to JSON-safe type."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def parse_sheet(
    workbook: openpyxl.Workbook,
    sheet_index: int = 0,
    *,
    auto_detect: bool = True,
) -> ExcelSheetParseResult:
    """Parse a single sheet into cell_data rows with coordinates.

    Args:
        workbook: Openpyxl workbook object.
        sheet_index: Index of the sheet to parse.
        auto_detect: If True, automatically detect header/data/footer boundaries.
    """
    sheet = workbook.worksheets[sheet_index]

    if auto_detect:
        start_row, end_row, min_col, max_col = _detect_data_bounds(sheet)
    else:
        start_row = sheet.min_row or 1
        end_row = sheet.max_row or 1
        min_col = sheet.min_column or 1
        max_col = sheet.max_column or 1

    rows: list[dict[str, object]] = []
    non_empty_count = 0

    if start_row <= end_row and min_col <= max_col:
        for row in sheet.iter_rows(
            min_row=start_row,
            max_row=end_row,
            min_col=min_col,
            max_col=max_col,
            values_only=False,
        ):
            row_values: dict[str, object] = {}
            has_data = False
            for cell in row:
                if cell.value is not None:
                    col_letter = get_column_letter(cell.column)
                    row_values[col_letter] = _serialize_cell(cell.value)
                    has_data = True
            if has_data:
                rows.append(row_values)
                non_empty_count += 1
            else:
                # 空行也保留（标记为空）以便行数对账
                rows.append({})

    # 收集合并单元格信息
    merged_info: list[dict[str, object]] = []
    for mr in sheet.merged_cells.ranges:
        merged_info.append(
            {
                "range": str(mr),
                "min_row": mr.min_row,
                "max_row": mr.max_row,
                "min_col": mr.min_col,
                "max_col": mr.max_col,
            }
        )

    coords: dict[str, object] = {
        "sheet_name": sheet.title,
        "data_start_row": start_row,
        "data_end_row": end_row,
        "data_start_col": min_col,
        "data_end_col": max_col,
        "total_rows_raw": end_row - start_row + 1,
        "non_empty_rows": non_empty_count,
        "parsed_rows": len(rows),
        "column_count": max_col - min_col + 1,
        "auto_detected": auto_detect,
        "merged_cells": merged_info,
    }
    return ExcelSheetParseResult(sheet_name=sheet.title, rows=rows, coordinates=coords)


def auto_select_sheet(
    workbook: openpyxl.Workbook,
) -> int:
    """自动选择最可能包含数据的 sheet（非空行最多者）。

    处理多 Sheet 工作簿（如"品类库存动销矩阵"有品类矩阵/库存明细/动销明细）。
    """
    best_idx = 0
    best_count = 0
    for i, ws in enumerate(workbook.worksheets):
        # 快速估算非空行数
        count = 0
        for row in ws.iter_rows(
            min_row=1, max_row=min(ws.max_row or 0, 100), values_only=True
        ):
            if any(v is not None for v in row):
                count += 1
        if count > best_count:
            best_count = count
            best_idx = i
    return best_idx


def parse_excel(
    data: bytes,
    sheet_index: int | None = None,
    *,
    auto_detect: bool = True,
    auto_sheet: bool = True,
) -> ExcelSheetParseResult:
    """Parse Excel bytes into raw grid data.

    包容人工不确定性：自动检测表头、数据边界、页脚、列偏移。
    支持多 Sheet 工作簿的智能选区。

    Args:
        data: Excel file content as bytes.
        sheet_index: Index of the sheet to parse (default: 0 or auto).
        auto_detect: Auto-detect data boundaries (headers, footers, offsets).
        auto_sheet: Auto-select the most data-rich sheet when sheet_index is None.

    Returns:
        ExcelSheetParseResult with row list and coordinate metadata.
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        idx: int
        if sheet_index is not None:
            idx = sheet_index
        elif auto_sheet:
            idx = auto_select_sheet(wb)
        else:
            idx = 0
        return parse_sheet(wb, idx, auto_detect=auto_detect)
    finally:
        wb.close()
