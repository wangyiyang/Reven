"""ParsingConfig — 解析配置 schema，连接「格式理解」与「数据提取」。

包含：
- dataclass ParsingConfig / ColumnMapping（现有接口兼容）
- Pydantic Schema 层（LLM 输出校验 + 缓存反序列化校验）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ═══════════════════════════════════════════════════════════
# 现有 dataclass（向后兼容，不做破坏性修改）
# ═══════════════════════════════════════════════════════════


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

    source: str = "rule"
    """配置来源: rule（规则匹配器）, llm（LLM 生成）, cache（模板配置缓存）。"""

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
            "source": self.source,
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
            source=d.get("source", "rule"),
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


# ═══════════════════════════════════════════════════════════
# Pydantic Schema（LLM 输出校验 + 缓存校验）
# ═══════════════════════════════════════════════════════════


class ColumnMappingSchema(BaseModel):
    """Pydantic schema for ColumnMapping (LLM output validation)."""

    target: str = Field(..., description="标准字段名")
    source_column: str | None = Field(None, description="列字母（可选）")
    source_name: str | None = Field(None, description="Excel 表头中文名")
    dtype: str = Field("string", description="数据类型: string, numeric, amount, date, boolean")

    @field_validator("target")
    @classmethod
    def target_must_be_identifier(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("target must be non-empty")
        return v.strip()


VALID_MERGE_STRATEGIES = {"none", "expand_down", "fill_group"}
VALID_DTYPES = {"string", "numeric", "amount", "date", "boolean"}


class ParsingConfigSchema(BaseModel):
    """Pydantic schema for ParsingConfig (LLM output validation)."""

    template_id: str = Field(..., description="模板标识")
    template_family: str = Field("unknown", description="模板簇")
    confidence: float = Field(0.8, description="置信度 0-1")
    header_row: int = Field(..., ge=1, description="表头所在行号（1-based）")
    data_start_row: int | None = Field(None, ge=1, description="数据起始行")
    data_end_row: int | None = Field(None, ge=1, description="数据结束行")
    data_start_col: int = Field(1, ge=1, description="数据起始列（1-based）")
    column_mappings: list[ColumnMappingSchema] = Field(default_factory=list, description="列映射列表")
    skip_patterns: list[str] = Field(default_factory=list, description="行跳过正则模式")
    merge_strategy: str = Field("none", description="合并单元格策略: none, expand_down, fill_group")
    validate_total: bool = Field(False, description="是否用页脚合计行校验金额列")

    @field_validator("merge_strategy")
    @classmethod
    def merge_strategy_must_be_valid(cls, v: str) -> str:
        if v not in VALID_MERGE_STRATEGIES:
            raise ValueError(f"merge_strategy must be one of {VALID_MERGE_STRATEGIES}, got {v!r}")
        return v

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    def to_parsing_config(self) -> ParsingConfig:
        """转换为兼容的 dataclass ParsingConfig。"""
        return ParsingConfig(
            template_id=self.template_id,
            template_family=self.template_family,
            confidence=self.confidence,
            source="llm",
            sheet_index=0,
            header_row=self.header_row,
            data_start_row=self.data_start_row,
            data_end_row=self.data_end_row,
            data_start_col=self.data_start_col,
            column_mappings=[
                ColumnMapping(
                    target=cm.target,
                    source_column=cm.source_column,
                    source_name=cm.source_name,
                    dtype=cm.dtype,
                )
                for cm in self.column_mappings
            ],
            skip_patterns=self.skip_patterns,
            merge_strategy=self.merge_strategy,
            validate_total=self.validate_total,
        )
