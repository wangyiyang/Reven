"""Prompt template — 为 LLM 匹配器构建结构化 prompt。

核心原则：只发结构样本，不发真实业务数据。
发给 LLM 的内容严格限定为：
- 表头区前 N 行的单元格文本 + 坐标
- 列数、Sheet 名、合并单元格区域等结构指纹字段
- 数据区仅 2-3 行脱敏样例（数值替换为占位符）
"""

from __future__ import annotations

from reven.importing.fingerprint import SheetFingerprint
from reven.importing.config import ParsingConfigSchema

# ═══════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════

_PROMPT_TEMPLATE = """你是一个 Excel 表格结构分析专家。你的任务是分析下面提供的 Excel 表格结构样本，输出一个 JSON 格式的解析配置（ParsingConfig）。

## 分析目标
根据结构样本，识别出：
1. 表头所在行号（header_row）
2. 数据起始行号（data_start_row）
3. 数据起始列号（data_start_col）
4. 每一列的表头名称（source_name）和对应的标准字段名（target）
5. 可能的跳过行模式（skip_patterns），如合计行、页码行
6. 是否有金额合计行可用于校验（validate_total）
7. 合并单元格策略（merge_strategy）

## 标准字段名说明
- date: 日期
- doc_number: 单据编号
- customer: 客户
- department: 部门
- salesperson: 业务员
- product: 存货/商品名
- product_code: 存货编码
- warehouse: 仓库
- warehouse_code: 仓库编码
- quantity: 数量
- unit_price: 单价
- amount: 金额
- spec: 规格型号
- quantity_on_hand: 现存量
- available_qty: 可用量
- category: 品类
- stock_qty: 库存量
- metric: 指标名
- value: 数值
- seq: 序号
- model: 型号
- contact: 联系人
- phone: 联系电话

## 列映射规则
- source_name 必须是在表头样例中实际出现的列名（精确匹配）
- dtype 取值: string, numeric, amount, date, boolean
- 金额列标记为 amount，数量列标记为 numeric
- 日期列标记为 date

## 结构样本
文件名: {filename}
Sheet 名: {sheet_name}
Sheet 索引: {sheet_index}
总列数: {total_cols}
总行数: {total_rows}
合并单元格数: {merged_count}

### 表头区行样本（前 20 行）
{header_samples}

### 页脚区行样本（尾 5 行）
{footer_samples}

### 表头列名签名（从左到右）
{header_signature}

### 列非空密度（%）
{column_density}

### 数据区探测结果
{data_region}

### 数据区样例（脱敏，仅 3 行）
{data_samples}

## 输出要求
输出必须是纯 JSON 对象，不包含 ```json 标记或其他说明文字。
JSON 必须符合以下 schema：
{{
  "template_id": "用户自定义模板名称，如 order_detail",
  "template_family": "模板簇分类",
  "confidence": 0.8,
  "header_row": 整数,
  "data_start_row": 整数或null,
  "data_end_row": 整数或null,
  "data_start_col": 整数,
  "column_mappings": [
    {{"target": "标准字段名", "source_name": "Excel列名", "dtype": "类型"}}
  ],
  "skip_patterns": ["正则表达式列表"],
  "merge_strategy": "none" 或 "expand_down",
  "validate_total": true 或 false
}}

请只输出 JSON。"""


# ═══════════════════════════════════════════════════════════
# Prompt 构建函数
# ═══════════════════════════════════════════════════════════


def _format_header_samples(fp: SheetFingerprint) -> str:
    """格式化表头区行样本。"""
    lines: list[str] = []
    for p in fp.header_candidates:
        vals = " | ".join(s for s in p.sample_values[:8])
        non_empty_pct = round(p.non_empty_count / max(p.total_cells, 1) * 100)
        lines.append(f"  行{p.index:>3} | 填充率{non_empty_pct:>2}% | {'页脚' if p.is_footer else '表头' if p.is_header_like else '数据' if p.non_empty_count > 0 else '空'} | {vals}")
    return "\n".join(lines)


def _format_footer_samples(fp: SheetFingerprint) -> str:
    """格式化页脚区行样本。"""
    lines: list[str] = []
    for p in fp.footer_candidates:
        vals = " | ".join(s for s in p.sample_values[:8])
        lines.append(f"  行{p.index:>3} | {vals}")
    return "\n".join(lines) if lines else "  （无）"


def _format_header_signature(fp: SheetFingerprint) -> str:
    """格式化表头列名签名。"""
    sig = fp.header_signature
    if not sig:
        return "  （未探测到列名）"
    cols = "\n  ".join(f"第{i+1}列: {name}" for i, name in enumerate(sig))
    return f"  共{len(sig)}列:\n  {cols}"


def _format_column_density(fp: SheetFingerprint) -> str:
    """格式化列非空密度。"""
    if not fp.column_density:
        return "  （无数据）"
    densities = " | ".join(f"{d}%" for d in fp.column_density[:15])
    if len(fp.column_density) > 15:
        densities += f" | …（共{len(fp.column_density)}列）"
    return f"  {densities}"


def _format_data_region(fp: SheetFingerprint) -> str:
    """格式化数据区探测结果。"""
    dr = fp.data_region
    if not dr:
        return "  （未探测到数据区）"
    lines = []
    for key, val in dr.items():
        lines.append(f"  {key}: {val}")
    return "\n".join(lines)


def _format_data_samples(fp: SheetFingerprint) -> str:
    """格式化的数据样例（脱敏，仅数据区前几行）。"""
    # 从 header_candidates 中提取数据行样本
    data_rows = [p for p in fp.header_candidates if not p.is_header_like and not p.is_footer and p.non_empty_count > 0]
    if not data_rows:
        return "  （无数据行样本）"
    lines: list[str] = []
    for p in data_rows[:3]:
        vals = " | ".join(s if not s.replace(".", "").replace("-", "").isdigit() else "[数值]" for s in p.sample_values[:8])
        lines.append(f"  行{p.index:>3}: {vals}")
    return "\n".join(lines)


def build_prompt(fp: SheetFingerprint) -> str:
    """根据 SheetFingerprint 构建 LLM prompt。

    Args:
        fp: 单个 sheet 的结构指纹。

    Returns:
        填充好的 prompt 字符串（含 "json" 关键字）。
    """
    return _PROMPT_TEMPLATE.format(
        filename=fp.name,
        sheet_name=fp.name,
        sheet_index=fp.index,
        total_cols=fp.total_cols,
        total_rows=fp.total_rows,
        merged_count=len(fp.merged_cells),
        header_samples=_format_header_samples(fp),
        footer_samples=_format_footer_samples(fp),
        header_signature=_format_header_signature(fp),
        column_density=_format_column_density(fp),
        data_region=_format_data_region(fp),
        data_samples=_format_data_samples(fp),
    )
