"""Golden case regression tests — 对账恒等式验证。

每个黄金案例是一个真实 Excel 文件，验证：
- 解析器能正确读取全部网格行
- 对账恒等式：总行数 = raw（当前阶段）→ 后续将变为 passed + skipped + error
"""

from pathlib import Path

import pytest
from reven.importing.parser import parse_excel

GOLDEN_DIR = Path("workspace")

# (filename, expected_sheet, expected_data_rows, expected_non_empty)
GOLDEN_CASES: list[tuple[str, str, int, int]] = [
    ("动销后可用量≤0明细_20260528.xlsx", "汇总", 10, 10),
    ("销货单明细表_28.xlsx", "第一页", 62, 56),
    ("销货单明细表_27.xlsx", "第一页", 92, 86),
]


@pytest.mark.parametrize(
    "filename,sheet_name,expected_rows,expected_non_empty",
    GOLDEN_CASES,
)
def test_golden_parse_row_count(
    filename: str,
    sheet_name: str,
    expected_rows: int,
    expected_non_empty: int,
):
    """黄金案例：解析行数 = 预期值。"""
    path = GOLDEN_DIR / filename
    if not path.exists():
        pytest.skip(f"Golden case file not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)

    assert result.sheet_name == sheet_name
    actual = len(result.rows)
    assert actual == expected_rows, (
        f"{filename}: expected {expected_rows} rows, got {actual}"
    )
    non_empty = sum(1 for r in result.rows if any(v is not None for v in r.values()))
    assert non_empty == expected_non_empty, (
        f"{filename}: expected {expected_non_empty} non-empty, got {non_empty}"
    )


@pytest.mark.parametrize(
    "filename,sheet_name,expected_rows,expected_non_empty",
    GOLDEN_CASES,
)
def test_golden_reconciliation_invariant(
    filename: str,
    sheet_name: str,
    expected_rows: int,
    expected_non_empty: int,
):
    """对账恒等式：总行数 = passed + skipped + error（当前全部为 raw）。

    等标准化层就位后，所有 raw 行必须被分类到 passed/skipped/error 之一，
    此断言将从 total == raw_count 变为 total == passed + skipped + error。
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
