"""Golden case regression tests — 五步流水线验证。

每个黄金案例是真实 Excel 文件，验证：
- 指纹提取 → 模板匹配 → 配置解析 → 确定性提取 完整管道
- 对账恒等式：总行数 = passed + skipped + error（当前全部为 raw）
- 校验强度区分（strong: 有合计; weak: 无合计降级）
"""

from pathlib import Path

import pytest
from reven.importing.fingerprint import fingerprint
from reven.importing.parser import extract, parse_excel
from reven.importing.template import match

GOLDEN_DIR = Path("workspace")

# (filename, expected_template, expected_rows, validation_strength)
GOLDEN_CASES: list[tuple[str, str, int, str]] = [
    ("销货单明细表_28.xlsx", "sales_order_standard", 49, "strong"),
    ("销货单明细表-11.xlsx", "sales_order_wide", 964, "strong"),
    ("销货单明细表_5月零售.xlsx", "sales_order_narrow", 172, "strong"),
    ("动销后可用量≤0明细_20260528.xlsx", "simple_metrics", 9, "weak"),
    ("现存量查询_20.xlsx", "inventory_N", 1787, "weak"),
    ("现存量查询_612.xlsx", "inventory_AF", 1826, "weak"),
    ("格力空调价格单_20260608.xlsx", "price_list", 66, "weak"),
]


@pytest.mark.parametrize("filename,exp_template,exp_rows,exp_vstrength", GOLDEN_CASES)
def test_pipeline_fingerprint_match(
    filename: str,
    exp_template: str,
    exp_rows: int,
    exp_vstrength: str,
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
    assert cfg.template_id == exp_template
    assert cfg.confidence >= 0.7

    result = extract(data, cfg)
    assert result.total == exp_rows

    # 校验强度
    assert result.validation is not None
    assert result.validation.get("validation_strength") == exp_vstrength

    # 弱校验必须有填充检查
    if exp_vstrength == "weak":
        assert "weak_pass_rows_filled" in result.validation.get("checks", []) or result.validation.get("passed")


@pytest.mark.parametrize("filename,exp_template,exp_rows,exp_vstrength", GOLDEN_CASES)
def test_parse_excel_auto(
    filename: str,
    exp_template: str,
    exp_rows: int,
    exp_vstrength: str,
):
    """高层 API：parse_excel 自动管道。"""
    path = GOLDEN_DIR / filename
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)

    assert result.config is not None
    assert result.config.template_id == exp_template

    rows = len(result.rows)
    assert rows == exp_rows
    assert result.coordinates.get("auto_detected") is True

    # 校验层
    assert result.validation is not None
    assert result.validation.get("validation_strength") == exp_vstrength


# ── 校验层专项测试 ──


def test_validation_strong_has_amount_sum():
    """强校验在销货单上必须产出金额合计。"""
    path = GOLDEN_DIR / "销货单明细表_28.xlsx"
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)
    v = result.validation
    assert v is not None
    assert v["validation_strength"] == "strong"
    assert "amount_sum" in v
    assert v["amount_sum"] > 0
    assert v["amount_fill_rate"] > 0.5


def test_validation_weak_no_amount_sum():
    """弱校验（无合计文件）不应有 amount_sum。"""
    path = GOLDEN_DIR / "现存量查询_20.xlsx"
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)
    v = result.validation
    assert v is not None
    assert v["validation_strength"] == "weak"
    assert "amount_sum" not in v


def test_merge_expand_down():
    """合并单元格 expand_down 填充生效。"""
    path = GOLDEN_DIR / "格力空调价格单_20260608.xlsx"
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    result = parse_excel(data)
    # 价格单有 9 个合并单元格，提取不应报错
    assert len(result.rows) > 0


def test_multi_sheet_selection():
    """多 Sheet 工作簿自动选区（选数据最丰富的 sheet）。"""
    path = GOLDEN_DIR / "品类库存动销矩阵.xlsx"
    if not path.exists():
        pytest.skip(f"File not found: {path}")

    data = path.read_bytes()
    fp = fingerprint(data)
    cfg = match(fp)
    assert cfg is not None
    best = fp.sheets[fp.best_sheet_index]
    assert best.data_region["end_row"] > 100


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
    assert cfg.validate_total == restored.validate_total


def test_template_header_signature():
    """模板匹配使用表头列名签名而非列数。"""
    data = open(GOLDEN_DIR / "销货单明细表-11.xlsx", "rb").read()
    fp = fingerprint(data)
    best = fp.sheets[fp.best_sheet_index]
    assert len(best.header_signature) > 0


def test_all_files_discovered():
    """至少有三个黄金案例文件可用。"""
    found = [f for f in GOLDEN_DIR.glob("销货单明细表*.xlsx")]
    assert len(found) >= 3
