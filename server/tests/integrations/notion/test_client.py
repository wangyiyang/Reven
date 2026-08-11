import json

import httpx
import pytest
import respx
from reven.integrations.notion.client import MAX_NOTION_RESPONSE_BYTES, NotionClient
from reven.integrations.notion.models import NotionConfigError, NotionSchemaError, NotionTransientError

BASE_URL = "https://api.notion.com"
TOKEN = "ntn_test_token_0000"
DATA_SOURCE_ID = "33333333-3333-3333-3333-333333333333"
PAGE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.anyio
async def test_query_data_source_sends_versioned_headers() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(
                200, json={"object": "list", "results": [], "has_more": False, "next_cursor": None}
            )
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            result = await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID)

    assert result["has_more"] is False
    request = route.calls[0].request
    assert request.headers["Notion-Version"] == "2026-03-11"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["Content-Type"] == "application/json"
    assert request.url.path == f"/v1/data_sources/{DATA_SOURCE_ID}/query"
    assert json.loads(request.content) == {"page_size": 100, "result_type": "page"}


@pytest.mark.anyio
async def test_query_data_source_passes_start_cursor_for_pagination() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(
                200, json={"object": "list", "results": [], "has_more": False, "next_cursor": None}
            )
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID, start_cursor="cursor-abc")

    assert json.loads(route.calls[0].request.content) == {
        "page_size": 100,
        "result_type": "page",
        "start_cursor": "cursor-abc",
    }


@pytest.mark.anyio
async def test_query_data_source_passes_exact_filter() -> None:
    filter_value = {"property": "Reven ID", "rich_text": {"equals": "item-1"}}
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(
                200, json={"object": "list", "results": [], "has_more": False, "next_cursor": None}
            )
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID, filter=filter_value)

    assert json.loads(route.calls[0].request.content) == {
        "page_size": 100,
        "result_type": "page",
        "filter": filter_value,
    }


@pytest.mark.anyio
async def test_create_page_uses_data_source_parent_and_properties() -> None:
    properties = {"名称": {"title": [{"text": {"content": "素材"}}]}}
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/v1/pages").mock(
            return_value=httpx.Response(200, json={"object": "page", "id": PAGE_ID, "url": "https://notion.so/page"})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            result = await NotionClient(token=TOKEN, http=http).create_page(DATA_SOURCE_ID, properties=properties)

    assert result["id"] == PAGE_ID
    assert json.loads(route.calls[0].request.content) == {
        "parent": {"type": "data_source_id", "data_source_id": DATA_SOURCE_ID},
        "properties": properties,
    }


@pytest.mark.anyio
async def test_retrieve_page_markdown_returns_markdown() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        route = router.get(f"/v1/pages/{PAGE_ID}/markdown").mock(
            return_value=httpx.Response(200, json={"markdown": "# 测试稿件\n\n正文"})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            markdown = await NotionClient(token=TOKEN, http=http).retrieve_page_markdown(PAGE_ID)

    assert markdown == "# 测试稿件\n\n正文"
    assert route.calls[0].request.url.path == f"/v1/pages/{PAGE_ID}/markdown"


@pytest.mark.anyio
async def test_rate_limit_raises_transient_error_with_retry_after() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "2"}, json={"message": "rate limited"})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionTransientError) as exc_info:
                await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID)

    assert exc_info.value.retry_after == 2.0


@pytest.mark.anyio
async def test_rate_limit_without_retry_after_header_uses_default() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(429, json={"message": "rate limited"})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionTransientError) as exc_info:
                await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID)

    assert exc_info.value.retry_after is not None
    assert exc_info.value.retry_after > 0


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [401, 403, 404])
async def test_auth_and_not_found_raise_config_error_without_token(status_code: int) -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(status_code, json={"message": f"token {TOKEN} is invalid"})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionConfigError) as exc_info:
                await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID)

    message = str(exc_info.value)
    assert str(status_code) in message
    assert TOKEN not in message


@pytest.mark.anyio
async def test_server_error_raises_transient_error() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(502, json={"message": "bad gateway"})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionTransientError) as exc_info:
                await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID)

    assert "502" in str(exc_info.value)


@pytest.mark.anyio
async def test_timeout_raises_transient_error() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(side_effect=httpx.TimeoutException("timed out"))
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionTransientError):
                await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID)


@pytest.mark.anyio
async def test_invalid_json_success_body_raises_transient_error() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(200, content=b"not-json-at-all")
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionTransientError, match="响应格式异常"):
                await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID)


@pytest.mark.anyio
async def test_oversized_decompressed_response_is_rejected() -> None:
    oversized = b'{"markdown":"' + b"a" * MAX_NOTION_RESPONSE_BYTES + b'"}'
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/v1/pages/{PAGE_ID}/markdown").mock(return_value=httpx.Response(200, content=oversized))
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionTransientError, match="大小限制"):
                await NotionClient(token=TOKEN, http=http).retrieve_page_markdown(PAGE_ID)


@pytest.mark.anyio
async def test_markdown_response_missing_key_raises_schema_error() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/v1/pages/{PAGE_ID}/markdown").mock(return_value=httpx.Response(200, json={"unexpected": "shape"}))
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionSchemaError, match="markdown"):
                await NotionClient(token=TOKEN, http=http).retrieve_page_markdown(PAGE_ID)


@pytest.mark.anyio
async def test_markdown_response_non_string_value_raises_schema_error() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/v1/pages/{PAGE_ID}/markdown").mock(return_value=httpx.Response(200, json={"markdown": 42}))
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionSchemaError, match="markdown"):
                await NotionClient(token=TOKEN, http=http).retrieve_page_markdown(PAGE_ID)


@pytest.mark.anyio
@pytest.mark.parametrize("retry_after", ["nan", "inf", "-inf"])
async def test_non_finite_retry_after_falls_back_to_default(retry_after: str) -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.post(f"/v1/data_sources/{DATA_SOURCE_ID}/query").mock(
            return_value=httpx.Response(429, headers={"Retry-After": retry_after}, json={"message": "rate limited"})
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(NotionTransientError) as exc_info:
                await NotionClient(token=TOKEN, http=http).query_data_source(DATA_SOURCE_ID)

    assert exc_info.value.retry_after == 1.0


@pytest.mark.anyio
async def test_client_rejects_non_https_base_url() -> None:
    async with httpx.AsyncClient(base_url="http://api.notion.com") as http:
        with pytest.raises(ValueError, match="HTTPS"):
            NotionClient(token=TOKEN, http=http)
