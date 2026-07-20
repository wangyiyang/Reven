"""Template matching — 先规则匹配，后 LLM 兜底。

核心流程：
  指纹 → 规则匹配器 → 命中? → ParsingConfig（source="rule"）
                       → 未命中 → LLM 插件口 → ParsingConfig（source="llm", confidence≤0.8）
                               → LLM 失败 → 人工确认队列

当前内置 6 类规则匹配器 + 1 个 LLM 兜底匹配器。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from reven.importing.config import ColumnMapping, ParsingConfig
from reven.importing.fingerprint import (
    RowProfile,
    SheetFingerprint,
    StructureFingerprint,
)
from reven.intelligence.llm_matcher import llm_matcher

# ── 匹配器类型签名 ─────────────────────────────────────────
MatcherFn = Callable[[SheetFingerprint], ParsingConfig | None]


# ── 已知模板注册表 ──────────────────────────────────────────


@dataclass
class TemplateRegistry:
    """模板匹配器注册表。先注册优先。"""

    matchers: list[tuple[str, MatcherFn]] = field(default_factory=list)

    def register(self, name: str, fn: MatcherFn) -> None:
        self.matchers.append((name, fn))

    def match(self, fp: SheetFingerprint) -> ParsingConfig | None:
        """按注册顺序依次尝试匹配，返回首个命中结果。"""
        for name, fn in self.matchers:
            result = fn(fp)
            if result is not None:
                return result
        return None


# ── 行样本检查工具 ─────────────────────────────────────────


def _has_keyword(profiles: list[RowProfile], keyword: str) -> bool:
    """检查行样本中是否包含指定关键词。"""
    for p in profiles:
        for s in p.sample_values:
            if keyword in s:
                return True
    return False


def _column_count(fp: SheetFingerprint, expected: int, tolerance: int = 2) -> bool:
    """检查列数是否在预期范围内。"""
    return abs(fp.total_cols - expected) <= tolerance


# ═══════════════════════════════════════════════════════════
# 规则匹配器实现
# ═══════════════════════════════════════════════════════════

# ── 🅰 销货单明细表 ─────────────────────────────────────


def _match_sales_order(fp: SheetFingerprint) -> ParsingConfig | None:
    """匹配销货单明细表（Q/R/S 列变体 + O 窄版）。

    特征：表头含"销货单明细表"。
    变体判别依据列名签名而非列数——因为 R/S 实际都可能是 18 列。

    header_signature 示例:
        Q:  单据日期, 单据编号, 客户, 业务员, 存货, 仓库, 数量, 单价, 金额
        R:  单据日期, 单据编号, 客户, 部门, 业务员, 存货, 仓库, 数量, 单价, 金额
        S:  单据日期, 单据编号, 客户, 部门, 业务员, 联系人, 联系电话, ...
        O:  单据日期, 单据编号, 客户, 存货, 数量, 单价, 金额 (窄版月报)
    """
    if not _has_keyword(fp.header_candidates, "销货单明细表"):
        return None
    if not (13 <= fp.total_cols <= 20):
        return None

    # 使用表头非空列数（header_signature 长度）判别变体
    # 实际数据揭示了 3 种宽度：
    #   narrow (O): ≤15 个表头列（5月零售 14列）
    #   standard (R): 16-17 个表头列（大多数标准导出）
    #   wide (S): ≥18 个表头列（含额外扩展字段）
    hdr_cols = len(fp.header_signature)
    if hdr_cols >= 17:
        template_id = "sales_order_wide"
    elif hdr_cols >= 15:
        template_id = "sales_order_standard"
    else:
        template_id = "sales_order_narrow"

    dr = fp.data_region
    header_row = dr.get("start_row", 5)
    start_col = dr.get("start_col", 2)

    return ParsingConfig(
        template_id=template_id,
        template_family="sales_order",
        confidence=0.95,
        sheet_index=fp.index,
        header_row=header_row,
        data_start_row=header_row + 1,
        data_start_col=start_col,
        skip_patterns=[r"合[计计]", r"第\s*\d+\s*页", r"制表人", r"打印日期"],
        merge_strategy="none",
        column_mappings=[
            ColumnMapping(target="date", source_name="单据日期", dtype="date"),
            ColumnMapping(target="doc_number", source_name="单据编号", dtype="string"),
            ColumnMapping(target="customer", source_name="客户", dtype="string"),
            ColumnMapping(target="department", source_name="部门", dtype="string"),
            ColumnMapping(target="salesperson", source_name="业务员", dtype="string"),
            ColumnMapping(target="product", source_name="存货", dtype="string"),
            ColumnMapping(target="warehouse", source_name="仓库", dtype="string"),
            ColumnMapping(target="quantity", source_name="数量", dtype="numeric"),
            ColumnMapping(target="unit_price", source_name="单价", dtype="amount"),
            ColumnMapping(target="amount", source_name="金额", dtype="amount"),
        ],
        validate_total=True,
    )


# ── 🅱 现存量查询 ─────────────────────────────────────────


def _match_inventory(fp: SheetFingerprint) -> ParsingConfig | None:
    """匹配现存量查询（N/AF 双模板+合并单元格）。

    特征：表头含"现存量查询"、列数 12~32、大量合并单元格。
    """
    if not _has_keyword(fp.header_candidates, "现存量查询"):
        return None
    if not (12 <= fp.total_cols <= 32):
        return None

    dr = fp.data_region
    start_col = dr.get("start_col", 2)
    header_row = dr.get("start_row", 4)

    # N vs AF 模板
    if fp.total_cols <= 14:
        template_id = "inventory_N"
        mappings = [
            ColumnMapping(target="warehouse", source_name="仓库", dtype="string"),
            ColumnMapping(target="product_code", source_name="存货编码", dtype="string"),
            ColumnMapping(target="product_name", source_name="存货", dtype="string"),
            ColumnMapping(target="spec", source_name="规格型号", dtype="string"),
            ColumnMapping(target="quantity_on_hand", source_name="现存量", dtype="numeric"),
            ColumnMapping(target="available_qty", source_name="可用量", dtype="numeric"),
        ]
    else:
        template_id = "inventory_AF"
        mappings = [
            ColumnMapping(target="warehouse_code", source_name="仓库编码", dtype="string"),
            ColumnMapping(target="warehouse", source_name="仓库", dtype="string"),
            ColumnMapping(target="product_code", source_name="存货编码", dtype="string"),
            ColumnMapping(target="product_name", source_name="存货", dtype="string"),
            ColumnMapping(target="spec", source_name="规格型号", dtype="string"),
            ColumnMapping(target="quantity_on_hand", source_name="现存量", dtype="numeric"),
            ColumnMapping(target="available_qty", source_name="可用量", dtype="numeric"),
        ]

    return ParsingConfig(
        template_id=template_id,
        template_family="inventory",
        confidence=0.9,
        sheet_index=fp.index,
        header_row=header_row,
        data_start_row=header_row + 1,
        data_start_col=start_col,
        skip_patterns=[r"合[计计]", r"制表人", r"打印日期", r"第\s*\d+\s*页"],
        merge_strategy="expand_down",
        column_mappings=mappings,
        validate_total=False,
    )


# ── 🅲 多 Sheet 工作簿: 品类/库存分析 ─────────────────────


def _match_category_analysis(fp: SheetFingerprint) -> ParsingConfig | None:
    """匹配品类库存动销矩阵等分析工作簿。

    特征：表头含"品类""动销""SKU"等分析关键词、列数 ≤14。
    """
    keywords = {"品类", "SKU", "动销", "库存量", "累计销量"}
    header_text = " ".join(s for p in fp.header_candidates for s in p.sample_values)
    matched = [kw for kw in keywords if kw in header_text]
    if len(matched) < 2:
        return None
    if fp.total_cols > 14:
        return None

    dr = fp.data_region
    header_row = dr.get("start_row", 1)

    return ParsingConfig(
        template_id="category_analysis",
        template_family="analysis",
        confidence=0.85,
        sheet_index=fp.index,
        header_row=header_row,
        data_start_row=header_row + 1,
        data_start_col=dr.get("start_col", 1),
        merge_strategy="none",
        column_mappings=[
            ColumnMapping(target="category", source_name="品类", dtype="string"),
            ColumnMapping(target="stock_qty", source_name="库存量", dtype="numeric"),
        ],
        validate_total=False,
    )


# ── 🅳 价格单 ─────────────────────────────────────────────


def _match_price_list(fp: SheetFingerprint) -> ParsingConfig | None:
    """匹配格力空调价格单等自由格式。

    特征：大量合并单元格、列数 ≤6、标题含"价格单""报价"等。
    """
    if not _has_keyword(fp.header_candidates, "价格单"):
        return None
    if fp.total_cols > 6:
        return None
    if len(fp.merged_cells) < 3:
        return None  # 自由格式一定有合并单元格

    dr = fp.data_region
    return ParsingConfig(
        template_id="price_list",
        template_family="free_form",
        confidence=0.7,
        sheet_index=fp.index,
        header_row=dr.get("start_row", 4),
        data_start_row=dr.get("start_row", 4) + 1,
        data_start_col=dr.get("start_col", 1),
        merge_strategy="expand_down",
        skip_patterns=[r"价格以", r"量大价优", r"^[Ww]arning"],
        column_mappings=[
            ColumnMapping(target="seq", source_name="序号", dtype="numeric"),
            ColumnMapping(target="model", source_name="型号", dtype="string"),
            ColumnMapping(target="unit_price", source_name="单价", dtype="amount"),
        ],
        validate_total=False,
    )


# ── 🅰+ 简单指标表（动销后可用量 汇总） ──────────────────


def _match_simple_metrics(fp: SheetFingerprint) -> ParsingConfig | None:
    """匹配动销后可用量≤0明细等简单指标键值对表。

    特征：列数 2、列名含"指标""数值"。
    """
    if fp.total_cols != 2:
        return None
    header_text = " ".join(s for p in fp.header_candidates for s in p.sample_values)
    if "指标" not in header_text or "数值" not in header_text:
        return None

    dr = fp.data_region
    return ParsingConfig(
        template_id="simple_metrics",
        template_family="metrics",
        confidence=0.95,
        sheet_index=fp.index,
        header_row=dr.get("start_row", 1),
        data_start_row=dr.get("start_row", 1) + 1,
        data_start_col=dr.get("start_col", 1),
        merge_strategy="none",
        column_mappings=[
            ColumnMapping(target="metric", source_name="指标", dtype="string"),
            ColumnMapping(target="value", source_name="数值", dtype="numeric"),
        ],
        validate_total=False,
    )


# ── 工厂函数 ──────────────────────────────────────────────


def default_registry() -> TemplateRegistry:
    """创建默认的模板匹配器注册表（按优先级排序）。

    注册顺序：
        1. 规则匹配器（高特异性优先）
        2. LLM 兜底匹配器（全部规则未命中时调用）
    """
    registry = TemplateRegistry()
    # 高特异性匹配器优先
    registry.register("sales_order", _match_sales_order)
    registry.register("inventory", _match_inventory)
    registry.register("price_list", _match_price_list)
    registry.register("simple_metrics", _match_simple_metrics)
    registry.register("category_analysis", _match_category_analysis)
    # LLM 兜底（全部规则未命中时才调用）
    registry.register("llm", llm_matcher)
    return registry


def match(
    fingerprint: StructureFingerprint,
    registry: TemplateRegistry | None = None,
    *,
    sheet_index: int | None = None,
) -> ParsingConfig | None:
    """对结构指纹执行模板匹配。

    Args:
        fingerprint: 结构指纹。
        registry: 匹配器注册表（默认使用内置规则）。
        sheet_index: 指定 sheet（None=自动选最佳）。

    Returns:
        若命中则返回 ParsingConfig，否则返回 None。
    """
    r = registry or default_registry()

    if sheet_index is not None:
        # 匹配指定 sheet — 将 sheet_index 回填到返回的配置中
        if 0 <= sheet_index < len(fingerprint.sheets):
            result = r.match(fingerprint.sheets[sheet_index])
            if result is not None:
                result.sheet_index = sheet_index
            return result
        return None

    # 优先匹配 best_sheet
    best_idx = fingerprint.best_sheet_index
    best_fp = fingerprint.sheets[best_idx]
    result = r.match(best_fp)
    if result is not None:
        result.sheet_index = best_idx
        return result

    # 兜底：逐 sheet 尝试
    for sf in fingerprint.sheets:
        if sf.index == best_idx:
            continue
        result = r.match(sf)
        if result is not None:
            result.sheet_index = sf.index
            return result
    return None
