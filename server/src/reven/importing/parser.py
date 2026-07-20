"""Excel parser — openpyxl 读取原始网格，产出 raw_row 数据。"""

import io
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


def _serialize_cell(value: object) -> object:
    """Convert openpyxl cell value to JSON-safe type."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def parse_sheet(
    workbook: openpyxl.Workbook, sheet_index: int = 0
) -> ExcelSheetParseResult:
    """Parse a single sheet into cell_data rows with coordinates."""
    sheet = workbook.worksheets[sheet_index]
    rows: list[dict[str, object]] = []
    max_col = sheet.max_column or 0
    min_col = sheet.min_column or 1
    min_row = sheet.min_row or 1

    for row in sheet.iter_rows(min_row=min_row, values_only=False):
        row_values: dict[str, object] = {}
        for cell in row:
            if cell.value is not None:
                col_letter = get_column_letter(cell.column)
                row_values[col_letter] = _serialize_cell(cell.value)
        rows.append(row_values)

    coords: dict[str, object] = {
        "sheet_name": sheet.title,
        "min_row": min_row,
        "max_row": sheet.max_row,
        "min_col": min_col,
        "max_col": max_col,
        "column_count": max_col - min_col + 1 if max_col else 0,
    }
    return ExcelSheetParseResult(sheet_name=sheet.title, rows=rows, coordinates=coords)


def parse_excel(data: bytes, sheet_index: int = 0) -> ExcelSheetParseResult:
    """Parse Excel bytes into raw grid data.

    Args:
        data: Excel file content as bytes.
        sheet_index: Index of the sheet to parse (default: 0).

    Returns:
        ExcelSheetParseResult with row list and coordinate metadata.
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        return parse_sheet(wb, sheet_index)
    finally:
        wb.close()
