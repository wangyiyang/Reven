"""飞书 /model 会话模型切换指令：解析与回复文案（纯函数，不触网、不触库）。

语义对齐 OpenClaw：用户显式指定的模型锁定用于当前会话；只允许切到已配置且
启用的模型（白名单校验）；指令回复直接返回，不进入 LLM、不计入会话历史。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from reven.integrations.credentials import AgentModelEntry

COMMAND_PREFIX = "/model"

USAGE_TEXT = (
    "用法：\n/model list — 查看可用模型\n/model use provider/model — 切换本会话模型\n/model current — 查看当前会话模型"
)
NO_MODELS_TEXT = "尚未配置可用模型。"

CommandAction = Literal["list", "use", "current", "help"]


@dataclass(frozen=True)
class ModelCommand:
    """一条 /model 指令的解析结论；action="help" 表示形态非法（回复用法）。"""

    action: CommandAction
    model_ref: str | None = None


def parse_model_command(text: str) -> ModelCommand | None:
    """识别以 /model 开头的指令文本；普通消息返回 None。

    - `/model`、`/model list` → list；`/model current` → current
    - `/model use <ref>` → use（ref 缺失或形态非法 → help）
    - 未识别子指令（如 `/model foo`）→ help
    - `/model` 后紧跟非空白字符（如 `/modelx`）→ None（按普通消息处理）
    """
    if not text.startswith(COMMAND_PREFIX):
        return None
    rest = text[len(COMMAND_PREFIX) :]
    if rest and not rest[0].isspace():
        return None
    parts = rest.split()
    if not parts or parts[0] == "list":
        return ModelCommand("list")
    if parts[0] == "current":
        return ModelCommand("current")
    if parts[0] == "use":
        if len(parts) != 2 or not is_valid_model_ref(parts[1]):
            return ModelCommand("help")
        return ModelCommand("use", model_ref=parts[1])
    return ModelCommand("help")


def is_valid_model_ref(ref: str) -> bool:
    """provider/model 形态：以第一个 / 分段，两侧均非空（model 段允许继续含 /）。"""
    provider, sep, model = ref.partition("/")
    return bool(sep) and bool(provider.strip()) and bool(model.strip())


def render_model_list(entries: Sequence[AgentModelEntry], current_ref: str | None) -> str:
    """可用模型清单：标注默认与当前会话所用；空注册表返回提示。"""
    if not entries:
        return NO_MODELS_TEXT
    lines = ["可用模型："]
    for index, entry in enumerate(entries, start=1):
        marks = ""
        if entry.is_default:
            marks += "（默认）"
        if entry.ref == current_ref:
            marks += "（当前会话）"
        lines.append(f"{index}. {entry.ref}{marks}")
    lines.append("切换：/model use provider/model")
    return "\n".join(lines)


def render_current(current_ref: str | None, *, is_override: bool) -> str:
    """当前会话模型：override 标注「会话指定」，否则标注「默认」；无配置返回提示。"""
    if current_ref is None:
        return NO_MODELS_TEXT
    suffix = "（会话指定）" if is_override else "（默认）"
    return f"当前会话模型：{current_ref}{suffix}"


def render_use_switched(ref: str) -> str:
    return f"已切换：本会话后续回答使用 {ref}。"


def render_use_reset_to_default(ref: str) -> str:
    return f"已恢复默认模型：{ref}。"


def render_use_rejected(ref: str, entries: Sequence[AgentModelEntry]) -> str:
    """拒绝切换：明确原因并列出可选项（白名单语义）。"""
    return f"无法切换到 {ref}：未配置或未启用。\n\n{render_model_list(entries, None)}"


def render_model_unavailable(ref: str) -> str:
    """override 模型调用失败的明确报错：不静默降级，保留 override 并给出恢复路径。"""
    return (
        f"模型 {ref} 当前不可用（未配置、未启用或调用失败），本次回答未切换到其他模型。\n"
        "可发 /model list 查看可选项，或 /model use <默认模型> 恢复默认。"
    )


def render_answer_with_model(answer: str, ref: str) -> str:
    """override 激活时的回答落款：末尾附一行当前模型标记。"""
    return f"{answer}\n\n—— 当前模型：{ref}"
