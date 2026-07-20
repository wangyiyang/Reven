"""ParsingConfig — 解析配置 schema，连接「格式理解」与「数据提取」。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnMapping:
    """单列映射：Excel 原始列 → 标准字段。"""

    target: str
    """标准字段名（如 quantity, amount, date, customer）。"""

    source_column: str | None = None
    """列字母（如 B, C, D），None 表示按 source_name 匹配。"""

    source_name: str | None = None
    """Excel 表头中文名（如"数量""金额"），None 表示按 column 匹配。"""

    dtype: str = "string"
    """数据类型: string, numeric, amount, date, boolean。"""


@dataclass
class ParsingConfig:
    """完整解析配置。由模板匹配引擎产出，被确定性引擎消费。"""

    template_id: str
    """模板标识（如 sales_order_Q, inventory_AF）。"""

    template_family: str
    """模板簇（如 sales_order, inventory, price_list）。"""

    confidence: float = 1.0
    """置信度 0-1，低于阈值需人工确认。"""

    sheet_index: int = 0
    """目标 sheet 索引。"""

    header_row: int = 1
    """表头所在行号（1-based）。"""

    data_start_row: int | None = None
    """数据起始行（None=表头行+1）。"""

    data_end_row: int | None = None
    """数据结束行（None=自动探测）。"""

    data_start_col: int = 1
    """数据起始列（1-based）。"""

    column_mappings: list[ColumnMapping] = field(default_factory=list)
    """列映射列表，顺序无关——按 source_name 或 source_column 匹配。"""

    skip_patterns: list[str] = field(default_factory=list)
    """行跳过正则模式（如合计行、页码行）。"""

    merge_strategy: str = "none"
    """合并单元格策略: none, expand_down, fill_group。"""

    validate_total: bool = False
    """是否用页脚合计行校验金额列。"""

    def column_for_target(self, target: str) -> str | None:
        """按目标字段名查找对应的列字母。"""
        for m in self.column_mappings:
            if m.target == target:
                if m.source_column:
                    return m.source_column
                return None
        return None

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON-safe dict（供 LLM 输出 / 缓存使用）。"""
        return {
            "template_id": self.template_id,
            "template_family": self.template_family,
            "confidence": self.confidence,
            "sheet_index": self.sheet_index,
            "header_row": self.header_row,
            "data_start_row": self.data_start_row,
            "data_end_row": self.data_end_row,
            "data_start_col": self.data_start_col,
            "column_mappings": [
                {
                    "target": m.target,
                    "source_column": m.source_column,
                    "source_name": m.source_name,
                    "dtype": m.dtype,
                }
                for m in self.column_mappings
            ],
            "skip_patterns": self.skip_patterns,
            "merge_strategy": self.merge_strategy,
            "validate_total": self.validate_total,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ParsingConfig:
        """从 dict / JSON 反序列化。"""
        return cls(
            template_id=d["template_id"],
            template_family=d.get("template_family", "unknown"),
            confidence=d.get("confidence", 1.0),
            sheet_index=d.get("sheet_index", 0),
            header_row=d["header_row"],
            data_start_row=d.get("data_start_row"),
            data_end_row=d.get("data_end_row"),
            data_start_col=d.get("data_start_col", 1),
            column_mappings=[ColumnMapping(**cm) for cm in d.get("column_mappings", [])],
            skip_patterns=d.get("skip_patterns", []),
            merge_strategy=d.get("merge_strategy", "none"),
            validate_total=d.get("validate_total", False),
        )
