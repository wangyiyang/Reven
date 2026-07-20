"""Golden case regression tests — 对账恒等式验证。

每个黄金案例是一个真实 Excel 文件，验证：
- 解析器能自适应表格结构（自动检测表头、页脚、列偏移）
- 对账恒等式：原始行数 = raw → 后续将变为 passed + skipped + error
"""

from pathlib import Path

import pytest
from reven.importing.parser import parse_excel

GOLDEN_DIR = Path("workspace")

# (filename, expected_sheet, expected_row_count, expected_non_empty, expected_merged)
# 所有预期值均基于 auto_detect=True 的解析结果
GOLDEN_CASES: list[tuple[str, str, int, int, int]] = [
    ("动销后可用量≤0明细_20260528.xlsx", "明细", 37, 37, 0),
    ("销货单明细表_28.xlsx", "第一页", 53, 52, 1),
    ("销货单明细表_27.xlsx", "第一页", 83, 82, 1),
    ("销货单明细表-11.xlsx", "第一页", 968, 967, 1),
    ("现存量查询_20.xlsx", "第一页", 1791, 1790, 12),
    ("格力空调价格单_20260608.xlsx", "格力空调价格单", 70, 67, 9),
]


@pytest.mark.parametrize(
    "filename,sheet_name,expected_rows,expected_non_empty,expected_merged",
    GOLDEN_CASES,
)
def test_golden_parse_row_count(
    filename: str,
    sheet_name: str,
    expected_rows: int,
    expected_non_empty: int,
    expected_merged: int,
):
    """黄金案例：解析行数与结构特征 = 预期值。"""
    path = GOLDEN_DIR / filename
    if not path.exists():
        pytest.skip(f"Golden case file not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)

    # Sheet 选区验证
    assert result.sheet_name == sheet_name, (
        f"{filename}: auto selected '{result.sheet_name}', expected '{sheet_name}'"
    )

    # 行数验证
    actual = len(result.rows)
    assert actual == expected_rows, (
        f"{filename}: expected {expected_rows} rows, got {actual}"
    )
    non_empty = sum(1 for r in result.rows if any(v is not None for v in r.values()))
    assert non_empty == expected_non_empty, (
        f"{filename}: expected {expected_non_empty} non-empty, got {non_empty}"
    )

    # 合并单元格数量验证
    merged_count = len(result.coordinates.get("merged_cells", []))
    assert merged_count == expected_merged, (
        f"{filename}: expected {expected_merged} merged cells, got {merged_count}"
    )

    # 自动检测起止坐标合理性
    c = result.coordinates
    assert c["data_start_row"] >= 1
    assert c["data_end_row"] >= c["data_start_row"]
    assert c["data_start_col"] >= 1
    assert c["data_end_col"] >= c["data_start_col"]
    assert c["auto_detected"] is True


@pytest.mark.parametrize(
    "filename,sheet_name,expected_rows,expected_non_empty,expected_merged",
    GOLDEN_CASES,
)
def test_golden_reconciliation_invariant(
    filename: str,
    sheet_name: str,
    expected_rows: int,
    expected_non_empty: int,
    expected_merged: int,
):
    """对账恒等式：总行数 = passed + skipped + error。

    当前全部为 raw。等标准化层就位后，所有 raw 行必须被分类到
    passed/skipped/error 之一，此断言将从 total > 0 演变为
    total == passed + skipped + error。
    """
    path = GOLDEN_DIR / filename
    if not path.exists():
        pytest.skip(f"Golden case file not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)
    total = len(result.rows)

    # 当前阶段：所有行均为 raw，尚未进入处理流水线
    assert total > 0, f"{filename}: no rows extracted"

    # 后续标准化层就位后将改为：
    # passed = sum(1 for r in ... if r.status == 'passed')
    # skipped = sum(1 for r in ... if r.status == 'skipped')
    # error = sum(1 for r in ... if r.status == 'error')
    # assert total == passed + skipped + error


def test_golden_all_files_discovered():
    """至少有一个黄金案例文件可用。"""
    found = [f for f in GOLDEN_DIR.glob("销货单明细表*.xlsx")]
    assert len(found) >= 1, f"No golden case files found in {GOLDEN_DIR}"


def test_golden_auto_detect_vs_raw():
    """自动检测模式比原始全量模式产生更少的行（去除了标题/页脚/空行）。"""
    path = GOLDEN_DIR / "销货单明细表-11.xlsx"
    if not path.exists():
        pytest.skip("Golden case file not found")

    data = path.read_bytes()
    auto = parse_excel(data, auto_detect=True)
    raw = parse_excel(data, auto_detect=False)

    assert len(auto.rows) < len(raw.rows), (
        f"auto_detect should reduce rows: {len(auto.rows)} >= {len(raw.rows)}"
    )


def test_golden_multi_sheet_selection():
    """多 Sheet 工作簿自动选择数据最丰富的 sheet。"""
    path = GOLDEN_DIR / "品类库存动销矩阵.xlsx"
    if not path.exists():
        pytest.skip("Golden case file not found")

    data = path.read_bytes()
    result = parse_excel(data)

    # 应该选择动销明细或库存明细（大表），而非品类矩阵（仅12行）
    assert result.coordinates["parsed_rows"] > 100, (
        f"auto-select picked a small sheet ({result.sheet_name}): "
        f"{result.coordinates['parsed_rows']} rows"
    )
