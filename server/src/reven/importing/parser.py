"""Excel parser — 五步流水线：指纹→匹配→配置→提取→校验。

使用方式：
    # 快速解析（自动匹配模板）
    result = parse_excel(data)

    # 分步控制
    fp = fingerprint(data)
    config = match(fp)
    result = extract(data, config)
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, cast

import openpyxl
from openpyxl.utils import get_column_letter

from reven.importing.config import ColumnMapping, ParsingConfig
from reven.importing.fingerprint import (
    StructureFingerprint,
)
from reven.importing.fingerprint import (
    fingerprint as fp_extract,
)
from reven.importing.template import match as tm_match

# ── 解析结果 ─────────────────────────────────────────────


@dataclass
class ParsedRow:
    """解析后的单行数据。"""

    row_number: int
    """Excel 中的原始行号。"""

    values: dict[str, object]
    """按 target 字段名索引的值。"""

    raw_cells: dict[str, object] | None = None
    """原始单元格值（按列字母），可选保留。"""

    skipped: bool = False
    """是否被跳过（匹配到 skip_pattern）。"""


@dataclass
class ExtractResult:
    """提取结果。"""

    rows: list[ParsedRow]
    total: int
    skipped: int
    config: ParsingConfig
    fingerprint: StructureFingerprint | None = None
    validation: dict[str, Any] | None = None


# ═══════════════════════════════════════════════════════════
# 确定性提取引擎
# ═══════════════════════════════════════════════════════════


def _find_column_index(
    sheet: openpyxl.worksheet.Worksheet,
    mapping: ColumnMapping,
    header_row: int,
) -> int | None:
    """在表头行中找到映射对应的列索引（1-based）。

    优先精确匹配，其次子串匹配。
    """
    # 列字母直指定
    if mapping.source_column:
        col = ord(mapping.source_column.upper()) - ord("A") + 1
        return col

    if not mapping.source_name:
        return None

    header_cells = list(sheet[header_row])

    # 第一遍：精确匹配
    for cell in header_cells:
        if cell.value is not None and mapping.source_name is not None:
            if str(cell.value).strip() == mapping.source_name:
                return cast(int, cell.column)

    # 第二遍：子串匹配（排除歧义：长名优先于短名）
    candidates: list[tuple[int, str]] = []
    for cell in header_cells:
        if cell.value is not None and mapping.source_name is not None and mapping.source_name in str(cell.value):
            candidates.append((cast(int, cell.column), str(cell.value).strip()))
    if len(candidates) == 1:
        return candidates[0][0]
    if len(candidates) > 1:
        # 取列名长度最接近的
        candidates.sort(key=lambda x: abs(len(x[1]) - len(mapping.source_name)))  # type: ignore[arg-type]
        return candidates[0][0]

    return None


def _should_skip(
    row_values: list[object],
    patterns: list[str],
) -> bool:
    """检查一行是否匹配跳过规则。"""
    text = " ".join(str(v) for v in row_values if v is not None)
    if not text.strip():
        return True
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    return False


def extract(
    data: bytes,
    config: ParsingConfig,
    *,
    keep_raw: bool = False,
    fingerprint: StructureFingerprint | None = None,
) -> ExtractResult:
    """按解析配置确定性提取数据。

    Args:
        data: Excel 文件内容。
        config: 解析配置（来自模板匹配或 LLM）。
        keep_raw: 是否保留原始单元格值。
        fingerprint: 结构指纹（可选，用于覆盖 data_end_row）。

    Returns:
        提取结果（行列表 + 统计）。
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        sheet = wb.worksheets[config.sheet_index]
        max_row = sheet.max_row or 0

        header_row = config.header_row
        start_row = config.data_start_row or (header_row + 1)

        # 优先使用 fingerprint 探测的 end_row，其次是 config，最后全量
        fp_end_row: int | None = None
        if fingerprint and config.sheet_index < len(fingerprint.sheets):
            fp_end_row = fingerprint.sheets[config.sheet_index].data_region.get("end_row")
        end_row = config.data_end_row or fp_end_row or max_row

        # 构建（列索引 → 映射）查找表
        col_mappings: dict[int, ColumnMapping] = {}
        for mapping in config.column_mappings:
            idx = _find_column_index(sheet, mapping, header_row)
            if idx is not None:
                col_mappings[idx] = mapping
                # 回填列字母，供后续校验使用
                mapping.source_column = get_column_letter(idx)

        rows: list[ParsedRow] = []
        skipped = 0

        for r in range(start_row, end_row + 1):
            vals = list(sheet.iter_rows(min_row=r, max_row=r, values_only=True))[0]

            # 跳过规则
            if _should_skip(list(vals), config.skip_patterns):
                skipped += 1
                continue

            # 空行跳过
            non_empty = {i: v for i, v in enumerate(vals) if v is not None}
            if not non_empty:
                skipped += 1
                continue

            # 按映射提取
            extracted: dict[str, object] = {}
            raw_cells: dict[str, object] = {}
            for col_idx, mapping in col_mappings.items():
                cell_val = vals[col_idx - 1] if col_idx <= len(vals) else None
                col_letter = get_column_letter(col_idx)
                raw_cells[col_letter] = cell_val

                if cell_val is not None:
                    extracted[mapping.target] = _coerce(cell_val, mapping.dtype)

            # 跳过无映射行（如子表头行）
            if not extracted:
                skipped += 1
                continue

            rows.append(
                ParsedRow(
                    row_number=r,
                    values=extracted,
                    raw_cells=raw_cells if keep_raw else None,
                )
            )

        # 校验
        validation = _validate(rows, config)

        return ExtractResult(
            rows=rows,
            total=len(rows),
            skipped=skipped,
            config=config,
            validation=validation,
        )
    finally:
        wb.close()


def _coerce(value: object, dtype: str) -> object:
    """按目标类型转换单元格值。

    金额字段（amount）保留原始 numeric 类型，不做四舍五入。
    """
    if value is None:
        return None
    if dtype == "string":
        return str(value)
    if dtype in ("numeric", "amount"):
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace(" ", "")
            try:
                return float(cleaned)
            except ValueError:
                return value
        return value
    if dtype == "date":
        if isinstance(value, str):
            # 尝试解析常见日期格式
            for fmt in (r"^\d{4}[-/]\d{2}[-/]\d{2}", r"^\d{4}\.\d{2}\.\d{2}"):
                if re.match(fmt, value):
                    return value  # 保留 ISO 格式
        return value
    return value


def _validate(
    rows: list[ParsedRow],
    config: ParsingConfig,
) -> dict[str, Any]:
    """提取后的校验。"""
    result: dict[str, Any] = {"passed": True, "checks": []}

    # 行数检查
    if not rows:
        result["passed"] = False
        result["checks"].append("no_rows")
        return result

    result["row_count"] = len(rows)

    # 金额列合计校验（如果页脚有合计）
    if config.validate_total:
        amount_col = config.column_for_target("amount")
        if amount_col:
            total_amount = 0.0
            for row in rows:
                v = row.values.get("amount")
                if isinstance(v, (int, float)):
                    total_amount += v
            result["amount_sum"] = round(total_amount, 2)
            result["checks"].append("amount_sum_calculated")

    # 必填字段非空
    total_rows = len(rows)
    for target in ["amount", "quantity", "date"]:
        col = config.column_for_target(target)
        if col:
            filled = sum(1 for row in rows if row.values.get(target) is not None)
            result[f"{target}_fill_rate"] = round(filled / total_rows, 2)

    return result


# ═══════════════════════════════════════════════════════════
# 高层 API（兼容旧接口）
# ═══════════════════════════════════════════════════════════


@dataclass
class ExcelSheetParseResult:
    """解析结果（兼容旧接口）。"""

    sheet_name: str
    rows: list[dict[str, object]]
    coordinates: dict[str, object]
    config: ParsingConfig | None = None
    validation: dict[str, Any] | None = None


def parse_excel(
    data: bytes,
    sheet_index: int | None = None,
    *,
    auto_detect: bool = True,
    auto_sheet: bool = True,
    keep_raw: bool = False,
    config: ParsingConfig | None = None,
) -> ExcelSheetParseResult:
    """解析 Excel 文件。

    全自动管道：fingerprint → match → extract。
    也可传入现成 config 跳过匹配步骤。

    Args:
        data: Excel 文件内容。
        sheet_index: 指定 sheet 索引（None=自动）。
        auto_detect: 是否启用自动探测（仅当无 config 时有效）。
        auto_sheet: 是否自动选区（仅当无 config 时有效）。
        keep_raw: 是否保留原始单元格值。
        config: 直接使用现成配置，跳过模板匹配。

    Returns:
        兼容旧接口的 ExcelSheetParseResult。
    """
    if config is not None:
        # 直接用传入配置提取
        result = extract(data, config, keep_raw=keep_raw)
        sheet_name = _get_sheet_name(data, config.sheet_index)
        return _to_legacy_result(result, sheet_name, fingerprint=None)

    if not auto_detect:
        # 关闭自动探测 = 原始暴力解析（全量）
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        try:
            idx = sheet_index if sheet_index is not None else 0
            ws = wb.worksheets[idx]
            simple_rows: list[dict[str, object]] = []
            for row in ws.iter_rows(values_only=False):
                row_values: dict[str, object] = {}
                for cell in row:
                    if cell.value is not None:
                        col_letter = get_column_letter(cell.column)
                        row_values[col_letter] = cell.value
                simple_rows.append(row_values)

            return ExcelSheetParseResult(
                sheet_name=ws.title,
                rows=simple_rows,
                coordinates={
                    "data_start_row": ws.min_row,
                    "data_end_row": ws.max_row,
                    "data_start_col": ws.min_column,
                    "data_end_col": ws.max_column,
                    "auto_detected": False,
                },
            )
        finally:
            wb.close()

    # 全自动管道
    fp = fp_extract(data)
    cfg = tm_match(fp) if config is None else config

    if cfg is None:
        # 无匹配模板，返回原始指纹（不走 LLM）
        sheet = fp.sheets[sheet_index if sheet_index is not None else fp.best_sheet_index]
        return ExcelSheetParseResult(
            sheet_name=sheet.name,
            rows=[],
            coordinates={
                "error": "no_template_match",
                "total_rows": sheet.total_rows,
                "total_cols": sheet.total_cols,
                "detected_region": sheet.data_region,
                "merged_cells": sheet.merged_cells,
            },
        )

    # 覆盖 sheet_index（如果调用方指定）
    if sheet_index is not None:
        cfg.sheet_index = sheet_index

    result = extract(data, cfg, keep_raw=keep_raw, fingerprint=fp)
    sheet_name = _get_sheet_name(data, cfg.sheet_index)

    return _to_legacy_result(result, sheet_name, fingerprint=fp)


def _get_sheet_name(data: bytes, idx: int) -> str:
    """快速读取 sheet 名。"""
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        return cast(str, wb.worksheets[idx].title)
    finally:
        wb.close()


def _to_legacy_result(
    result: ExtractResult,
    sheet_name: str,
    fingerprint: StructureFingerprint | None,
) -> ExcelSheetParseResult:
    """将新式 ExtractResult 转换为旧式 ExcelSheetParseResult。"""
    legacy_rows: list[dict[str, object]] = []
    for pr in result.rows:
        legacy_rows.append(pr.values)

    # coordinates 兼容旧接口
    dr = fingerprint.sheets[result.config.sheet_index].data_region if fingerprint else {}
    coords: dict[str, object] = {
        "template_id": result.config.template_id,
        "template_family": result.config.template_family,
        "sheet_name": sheet_name,
        "auto_detected": True,
        "header_row": result.config.header_row,
        "data_start_row": dr.get("start_row", result.config.data_start_row),
        "data_end_row": dr.get("end_row"),
        "data_start_col": dr.get("start_col", result.config.data_start_col),
        "total_extracted": result.total,
        "skipped": result.skipped,
        "validation": result.validation,
    }

    return ExcelSheetParseResult(
        sheet_name=sheet_name,
        rows=legacy_rows,
        coordinates=coords,
        config=result.config,
        validation=result.validation,
    )
