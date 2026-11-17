"""Bitable client 单测：请求形状、分页、分批、错误脱敏（respx MockTransport）。"""

import json

import httpx
import pytest
import respx
from reven.integrations.feishu_bot.client import (
    TENANT_TOKEN_URL,
    BitableFilterCondition,
    BitableRecordUpdate,
    BitableRecordWrite,
    BitableSortField,
    FeishuBotApiClient,
    FeishuBotApiError,
)

APP_TOKEN = "bascn_test_app"
TABLE_ID = "tbl_test_table"
TABLE_URL = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}"


def _mock_token(router: respx.MockRouter) -> respx.Route:
    return router.post(TENANT_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "tenant_access_token": "t-token"})
    )


def _field_item(field_id: str, name: str, field_type: int) -> dict[str, object]:
    return {"field_id": field_id, "field_name": name, "type": field_type}


@pytest.mark.anyio
async def test_list_fields_paginates_with_page_token() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        route = router.get(url__startswith=f"{TABLE_URL}/fields").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "items": [_field_item("fld1", "标题", 1)],
                            "has_more": True,
                            "page_token": "p2",
                        },
                    },
                ),
                httpx.Response(
                    200,
                    json={"code": 0, "data": {"items": [_field_item("fld2", "状态", 3)], "has_more": False}},
                ),
            ]
        )
        fields = await FeishuBotApiClient("cli_test", "secret").list_fields(APP_TOKEN, TABLE_ID)

    assert [(field.field_id, field.name, field.type) for field in fields] == [
        ("fld1", "标题", 1),
        ("fld2", "状态", 3),
    ]
    assert route.call_count == 2
    first, second = (call.request for call in route.calls)
    assert first.headers["authorization"] == "Bearer t-token"
    assert "page_token" not in first.url.params
    assert second.url.params["page_token"] == "p2"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0, "data": {}},
        {"code": 0, "data": {"items": "not-a-list"}},
        {"code": 0, "data": {"items": [{"field_id": "fld1", "field_name": "标题"}]}},
        {"code": 0, "data": {"items": [{"field_id": "fld1", "field_name": "标题", "type": "1"}]}},
        {"code": 0},
    ],
)
async def test_list_fields_malformed_payload_is_rejected(payload: dict[str, object]) -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.get(url__startswith=f"{TABLE_URL}/fields").mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(FeishuBotApiError, match="格式无效"):
            await FeishuBotApiClient("cli_test", "secret").list_fields(APP_TOKEN, TABLE_ID)


@pytest.mark.anyio
async def test_search_records_posts_filter_and_parses_page() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        route = router.post(url__startswith=f"{TABLE_URL}/records/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [{"record_id": "rec1", "fields": {"标题": "文章"}}],
                        "has_more": True,
                        "page_token": "next",
                        "total": 5,
                    },
                },
            )
        )
        page = await FeishuBotApiClient("cli_test", "secret").search_records(
            APP_TOKEN,
            TABLE_ID,
            filter_conditions=[BitableFilterCondition(field_name="去重键", operator="is", value=("key-1",))],
            sort_fields=[BitableSortField(field_name="发布时间", desc=True)],
            page_size=1000,
            page_token="prev",
        )

    assert page.has_more is True
    assert page.page_token == "next"
    assert page.total == 5
    assert [(record.record_id, record.fields) for record in page.records] == [("rec1", {"标题": "文章"})]
    request = route.calls[0].request
    assert request.url.params["page_size"] == "500"  # clamp 到单页上限
    assert request.url.params["page_token"] == "prev"
    assert json.loads(request.content) == {
        "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "去重键", "operator": "is", "value": ["key-1"]}],
        },
        "sort": [{"field_name": "发布时间", "desc": True}],
    }


@pytest.mark.anyio
async def test_search_records_without_filter_sends_empty_body() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        route = router.post(url__startswith=f"{TABLE_URL}/records/search").mock(
            return_value=httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})
        )
        page = await FeishuBotApiClient("cli_test", "secret").search_records(APP_TOKEN, TABLE_ID, page_size=1)

    assert page.records == ()
    assert page.page_token is None
    assert page.total is None  # total 缺失时防御性解析为 None
    assert route.calls[0].request.url.params["page_size"] == "1"
    assert json.loads(route.calls[0].request.content) == {}


@pytest.mark.anyio
async def test_get_record_returns_record_and_marks_absent_as_none() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        route = router.post(f"{TABLE_URL}/records/batch_get").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": (
                        {"records": [{"record_id": "rec1", "fields": {"标题": "文章"}}]}
                        if json.loads(request.content)["record_ids"] == ["rec1"]
                        else {"records": [], "absent_record_ids": json.loads(request.content)["record_ids"]}
                    ),
                },
            )
        )
        client = FeishuBotApiClient("cli_test", "secret")

        found = await client.get_record(APP_TOKEN, TABLE_ID, "rec1")
        missing = await client.get_record(APP_TOKEN, TABLE_ID, "rec_gone")

    assert found is not None and found.record_id == "rec1" and found.fields == {"标题": "文章"}
    assert missing is None
    assert route.call_count == 2


@pytest.mark.anyio
async def test_batch_create_splits_batches_and_passes_client_token() -> None:
    records = [BitableRecordWrite(fields={"标题": f"文章{i}"}) for i in range(500)]
    records.append(BitableRecordWrite(fields={"标题": "文章500"}, client_token="run-1:key-500"))
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        route = router.post(f"{TABLE_URL}/records/batch_create").mock(
            side_effect=lambda request: httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "records": [
                            {"record_id": f"rec_{i}", "fields": item["fields"]}
                            for i, item in enumerate(json.loads(request.content)["records"])
                        ]
                    },
                },
            )
        )
        created = await FeishuBotApiClient("cli_test", "secret").batch_create_records(APP_TOKEN, TABLE_ID, records)

    assert route.call_count == 2
    first_body = json.loads(route.calls[0].request.content)
    second_body = json.loads(route.calls[1].request.content)
    assert len(first_body["records"]) == 500
    assert len(second_body["records"]) == 1
    assert "client_token" not in first_body["records"][0]
    assert second_body["records"][0]["client_token"] == "run-1:key-500"
    assert len(created) == 501


@pytest.mark.anyio
async def test_batch_create_empty_records_skips_http() -> None:
    with respx.mock(assert_all_called=False) as router:
        created = await FeishuBotApiClient("cli_test", "secret").batch_create_records(APP_TOKEN, TABLE_ID, [])

    assert created == ()
    assert len(router.calls) == 0


@pytest.mark.anyio
async def test_batch_update_sends_record_id_and_fields() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        route = router.post(f"{TABLE_URL}/records/batch_update").mock(
            return_value=httpx.Response(
                200,
                json={"code": 0, "data": {"records": [{"record_id": "rec1", "fields": {"状态": "saved"}}]}},
            )
        )
        updated = await FeishuBotApiClient("cli_test", "secret").batch_update_records(
            APP_TOKEN, TABLE_ID, [BitableRecordUpdate(record_id="rec1", fields={"状态": "saved"})]
        )

    assert [record.record_id for record in updated] == ["rec1"]
    assert json.loads(route.calls[0].request.content) == {
        "records": [{"record_id": "rec1", "fields": {"状态": "saved"}}]
    }


@pytest.mark.anyio
async def test_batch_delete_splits_batches() -> None:
    record_ids = [f"rec{i}" for i in range(501)]
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        route = router.post(f"{TABLE_URL}/records/batch_delete").mock(
            return_value=httpx.Response(200, json={"code": 0, "data": {"records": []}})
        )
        await FeishuBotApiClient("cli_test", "secret").batch_delete_records(APP_TOKEN, TABLE_ID, record_ids)

    assert route.call_count == 2
    assert len(json.loads(route.calls[0].request.content)["records"]) == 500
    assert json.loads(route.calls[1].request.content)["records"] == ["rec500"]


@pytest.mark.anyio
async def test_bitable_error_keeps_code_and_redacts_payload() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.get(url__startswith=f"{TABLE_URL}/fields").mock(
            return_value=httpx.Response(200, json={"code": 1254043, "msg": "secret t-token leaked"})
        )
        with pytest.raises(FeishuBotApiError) as caught:
            await FeishuBotApiClient("cli_test", "secret").list_fields(APP_TOKEN, TABLE_ID)

    assert caught.value.code == 1254043
    assert "code=1254043" in str(caught.value)
    assert "secret" not in str(caught.value)
    assert "t-token" not in str(caught.value)


@pytest.mark.anyio
async def test_bitable_calls_share_cached_tenant_token() -> None:
    with respx.mock(assert_all_called=True) as router:
        token_route = _mock_token(router)
        router.get(url__startswith=f"{TABLE_URL}/fields").mock(
            return_value=httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})
        )
        client = FeishuBotApiClient("cli_test", "secret")
        await client.list_fields(APP_TOKEN, TABLE_ID)
        await client.list_fields(APP_TOKEN, TABLE_ID)

    assert token_route.call_count == 1
