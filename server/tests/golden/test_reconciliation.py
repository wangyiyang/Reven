"""Golden case regression tests — 五步流水线验证。

每个黄金案例是真实 Excel 文件，验证：
- 指纹提取 → 模板匹配 → 配置解析 → 确定性提取 完整管道
- 对账恒等式：总行数 = passed + skipped + error（当前全部为 raw）
"""

from pathlib import Path

import pytest
from reven.importing.fingerprint import fingerprint
from reven.importing.parser import extract, parse_excel
from reven.importing.template import match

GOLDEN_DIR = Path("workspace")

# (filename, expected_template, expected_rows, expected_skipped, min_key_fields)
# key_fields: 非空必填字段数，用于验证列映射正确
GOLDEN_CASES: list[tuple[str, str, int, int, int]] = [
    ("销货单明细表_28.xlsx", "sales_order_R", 49, 3, 3),
    ("销货单明细表-11.xlsx", "sales_order_S", 964, 3, 3),
    ("动销后可用量≤0明细_20260528.xlsx", "simple_metrics", 9, 0, 2),
    ("现存量查询_20.xlsx", "inventory_N", 1786, 4, 2),
    ("现存量查询_612.xlsx", "inventory_AF", 1826, 1, 2),
    ("格力空调价格单_20260608.xlsx", "price_list", 66, 0, 1),
]


# ── 分步管道测试 ─────────────────────────────────────────


@pytest.mark.parametrize("filename,exp_template,exp_rows,exp_skipped,min_keys", GOLDEN_CASES)
def test_pipeline_fingerprint_match(
    filename: str,
    exp_template: str,
    exp_rows: int,
    exp_skipped: int,
    min_keys: int,
):
    """分步管道：指纹 → 匹配 → 提取，验证模板识别与行数。"""
    path = GOLDEN_DIR / filename
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    fp = fingerprint(data)
    assert len(fp.sheets) >= 1

    cfg = match(fp)
    assert cfg is not None, f"No template matched for {filename}"
    assert cfg.template_id == exp_template, f"{filename}: expected template '{exp_template}', got '{cfg.template_id}'"
    assert cfg.confidence >= 0.7

    result = extract(data, cfg)
    assert result.total == exp_rows, f"{filename}: expected {exp_rows} rows, got {result.total}"

    # 验证关键字段非空率（列映射正确性）
    if result.rows:
        first = result.rows[0]
        non_null = sum(1 for v in first.values.values() if v is not None and v != "")
        assert non_null >= min_keys, (
            f"{filename}: first row has {non_null} non-null keys, expected ≥{min_keys}. Row: {first.values}"
        )


# ── 高层 API 测试 ─────────────────────────────────────────


@pytest.mark.parametrize("filename,exp_template,exp_rows,exp_skipped,min_keys", GOLDEN_CASES)
def test_parse_excel_auto(
    filename: str,
    exp_template: str,
    exp_rows: int,
    exp_skipped: int,
    min_keys: int,
):
    """高层 API：parse_excel 自动管道。"""
    path = GOLDEN_DIR / filename
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)

    assert result.config is not None, f"No config generated for {filename}"
    assert result.config.template_id == exp_template

    rows = len(result.rows)
    assert rows == exp_rows, f"{filename}: parse_excel returned {rows}, expected {exp_rows}"
    assert result.coordinates.get("auto_detected") is True


# ── 校验层测试 ────────────────────────────────────────────


def test_validation_amount_sum():
    """amount_sum 校验在销货单上正确执行。"""
    path = GOLDEN_DIR / "销货单明细表_28.xlsx"
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)
    assert result.validation is not None
    assert "amount_sum" in result.validation
    assert result.validation["amount_sum"] > 0
    assert result.validation["amount_fill_rate"] > 0.5


def test_multi_sheet_selection():
    """多 Sheet 工作簿自动选区。"""
    path = GOLDEN_DIR / "品类库存动销矩阵.xlsx"
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    fp = fingerprint(data)
    cfg = match(fp)
    # 应命中 category_analysis 或回到 sales_order
    assert cfg is not None
    # 自动选择数据最丰富 sheet
    best = fp.sheets[fp.best_sheet_index]
    assert best.data_region["end_row"] > 100, "Should pick large sheet"


def test_config_serialize_roundtrip():
    """ParsingConfig 序列化/反序列化不变性。"""
    data = open(GOLDEN_DIR / "销货单明细表_28.xlsx", "rb").read()
    fp = fingerprint(data)
    cfg = match(fp)
    assert cfg is not None

    d = cfg.to_dict()
    restored = type(cfg).from_dict(d)
    assert cfg.template_id == restored.template_id
    assert cfg.header_row == restored.header_row
    assert len(cfg.column_mappings) == len(restored.column_mappings)
    for a, b in zip(cfg.column_mappings, restored.column_mappings):
        assert a.target == b.target
        assert a.dtype == b.dtype


def test_all_files_discovered():
    """至少有三个黄金案例文件可用。"""
    found = [f for f in GOLDEN_DIR.glob("销货单明细表*.xlsx")]
    assert len(found) >= 3, f"Only {len(found)} sales order files found"
