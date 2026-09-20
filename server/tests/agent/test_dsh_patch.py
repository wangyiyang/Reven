"""dsh.patch.yml 结构校验与 dsh --dump-config 组合有效性测试。"""

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

PATCH_FILE = Path(__file__).parents[2] / "src" / "reven" / "agent" / "dsh.patch.yml"

DISABLED_CODING_TOOLS = {
    "tool-bash",
    "tool-pwsh",
    "tool-fs",
    "tool-fs-search",
    "tool-skill",
    "tool-subagent-control",
    "tool-subagent-list-agents",
    "tool-jobs",
}


def _load_patch() -> list[dict[str, Any]]:
    yaml.add_multi_constructor(
        "tag:yaml.org,2002:js",
        lambda loader, _suffix, node: loader.construct_scalar(node),
        Loader=yaml.SafeLoader,
    )
    loaded = yaml.safe_load(PATCH_FILE.read_text(encoding="utf-8"))
    assert isinstance(loaded, list)
    return loaded


def _inserted_mcp_reven() -> dict[str, Any]:
    inserted = [entry for item in _load_patch() if "insert" in item for entry in item["insert"]]
    (mcp_reven,) = [entry for entry in inserted if entry["id"] == "mcp-reven"]
    return mcp_reven


def test_patch_inserts_reven_mcp_client() -> None:
    mcp_reven = _inserted_mcp_reven()
    config = mcp_reven["config"]
    assert mcp_reven["name"] == "@deepseek-ai/dsh-mcp-client"
    assert config["serverName"] == "reven"
    assert config["transport"] == "streamable-http"
    assert config["url"] == "process.env.REVEN_AGENT_MCP_URL"


def test_patch_reads_credentials_from_env_not_literals() -> None:
    authorization = _inserted_mcp_reven()["config"]["headers"]["Authorization"]
    assert authorization == '"Bearer " + process.env.REVEN_AGENT_MCP_TOKEN'
    # 禁止把真实凭证以字面量落盘（如随机 hex token）
    assert not re.search(r"\b[0-9a-f]{32,}\b", PATCH_FILE.read_text(encoding="utf-8"))


def test_patch_disables_builtin_coding_tools() -> None:
    disabled = {item["id"] for item in _load_patch() if item.get("disabled") is True}
    assert disabled == DISABLED_CODING_TOOLS


@pytest.mark.dsh_runtime
def test_patch_composes_with_sdk_profile(tmp_path: Path) -> None:
    """dsh --dump-config 实跑：insert/disable 语法被 sdk profile 接受，mcp-reven 出现在组合结果中。"""
    try:
        from deepseek_harness_runtime import resolve_bundled_launch_args

        base = resolve_bundled_launch_args()
    except (ImportError, FileNotFoundError) as exc:
        pytest.skip(f"未找到 dsh runtime 二进制：{exc}")
    env = {
        **os.environ,
        "DSH_HOME": str(tmp_path / "dsh-home"),
        "REVEN_AGENT_MCP_URL": "http://127.0.0.1:8000/agent/mcp",
        "REVEN_AGENT_MCP_TOKEN": "dump-config-only",
    }
    result = subprocess.run(
        [*base, "--profile", "sdk", "--patch", str(PATCH_FILE), "--dump-config"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "mcp-reven" in result.stdout
    assert "@deepseek-ai/dsh-mcp-client" in result.stdout
