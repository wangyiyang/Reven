"""Native schema fidelity and the machine channel's write boundary."""

from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from reven.agent.mcp_server import create_agent_mcp_server
from reven.agent.tool_registry import ToolRegistry
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_catalog_keeps_37_tools_25_writes_and_eight_mandatory_deletes() -> None:
    registry = ToolRegistry(async_sessionmaker())
    assert len(registry.tool_names) == 37
    assert sum(definition.spec.is_write for definition in registry.definitions.values()) == 25
    assert set(registry.confirmation_tools()) == {
        "rss_keyword_delete",
        "crm_customer_delete",
        "crm_contact_delete",
        "crm_follow_up_delete",
        "talent_delete",
        "talent_interaction_delete",
        "talent_experience_delete",
        "talent_education_delete",
    }
    assert len(registry.native_tools()) == 37
    with pytest.raises(ValueError):
        registry.native_tools(["unknown_tool"])
    with pytest.raises(ValueError):
        registry.native_tools(["talent_get", "talent_get"])


def test_native_schemas_keep_descriptions_defaults_types_and_hide_trusted_context() -> None:
    registry = ToolRegistry(async_sessionmaker())
    tools = {tool.name: tool for tool in registry.native_tools()}
    for name, tool in tools.items():
        native = tool.tool_call_schema.model_json_schema()
        business = registry.definitions[name].args_schema.model_json_schema()
        assert native.get("properties", {}) == business.get("properties", {})
        assert native.get("required", []) == business.get("required", [])
        assert not {"runtime", "owner_id", "session_id", "run_id", "tool_call_id"} & set(native.get("properties", {}))
    properties = tools["crm_follow_up_create"].args
    assert properties["customer_id"]["format"] == "uuid"
    assert properties["occurred_on"]["format"] == "date"
    assert "跟进" in properties["kind"]["description"]
    assert tools["rss_keyword_create"].args["enabled"]["default"] is True
    assert "clear_contact" in tools["crm_follow_up_update"].args
    assert "clear_rate" in tools["talent_update"].args
    assert "experiences" in tools["talent_import_profile"].args


def test_canonical_arguments_include_defaults_and_reject_model_supplied_actor() -> None:
    registry = ToolRegistry(async_sessionmaker())
    normalized = registry.canonical_tool_arguments("rss_keyword_create", {"term": "  AI  ", "kind": "positive"})
    assert normalized == {"term": "AI", "kind": "positive", "enabled": True}
    with pytest.raises(ValidationError):
        registry.canonical_tool_arguments("rss_keyword_create", {"term": "AI", "kind": "positive", "owner_id": "fake"})
    with pytest.raises(ValidationError):
        registry.canonical_tool_arguments("crm_customer_get", {"customer_id": "invalid-uuid"})


@pytest.mark.anyio
async def test_machine_bearer_cannot_execute_any_of_25_write_tools() -> None:
    factory = async_sessionmaker()
    registry = ToolRegistry(factory)
    async with Client(create_agent_mcp_server(factory, "test-token")) as client:
        schemas = {tool.name: tool.input_schema for tool in await client.list_tools()}
        for definition in registry.definitions.values():
            if not definition.spec.is_write:
                continue
            arguments = _required_values(schemas[definition.name])
            with pytest.raises(ToolError, match="MCP_WRITE_CONTEXT_REQUIRED"):
                await client.call_tool(definition.name, arguments)


def _required_values(schema: dict[str, object]) -> dict[str, object]:
    properties = schema["properties"]
    assert isinstance(properties, dict)
    values: dict[str, object] = {}
    for name in schema.get("required", []):
        field = properties[name]
        if field.get("format") == "uuid":
            values[name] = str(uuid4())
        elif field.get("format") == "date":
            values[name] = "2026-01-01"
        elif field.get("type") == "boolean":
            values[name] = True
        elif "enum" in field:
            values[name] = field["enum"][0]
        else:
            values[name] = "测试"
    return values
