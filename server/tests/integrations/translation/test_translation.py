import hashlib
from urllib.parse import parse_qsl

import httpx
import pytest
import respx
from reven.integrations.translation import TranslationError
from reven.integrations.translation.aliyun import AliyunTranslateClient
from reven.integrations.translation.aliyun import test_aliyun_translation as aliyun_adapter
from reven.integrations.translation.baidu import BaiduTranslateClient
from reven.integrations.translation.baidu import test_baidu_translation as baidu_adapter


@pytest.mark.anyio
async def test_baidu_client_signs_and_returns_translation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        params = dict(parse_qsl(request.url.query.decode()))
        assert params["q"] == "hello"
        assert params["from"] == "en" and params["to"] == "zh"
        assert params["appid"] == "2026082500001"
        expected = hashlib.md5(f"2026082500001hello{params['salt']}baidu-key".encode()).hexdigest()
        assert params["sign"] == expected
        return httpx.Response(200, json={"from": "en", "to": "zh", "trans_result": [{"src": "hello", "dst": "你好"}]})

    async with httpx.AsyncClient(
        base_url="https://fanyi-api.baidu.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        assert await BaiduTranslateClient("2026082500001", "baidu-key", http=http).translate("hello") == "你好"


@pytest.mark.anyio
async def test_baidu_client_raises_on_business_error() -> None:
    async with httpx.AsyncClient(
        base_url="https://fanyi-api.baidu.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"error_code": "52003"})),
    ) as http:
        with pytest.raises(TranslationError, match="52003"):
            await BaiduTranslateClient("appid", "key", http=http).translate("hello")


@pytest.mark.anyio
async def test_baidu_client_raises_on_http_error() -> None:
    async with httpx.AsyncClient(
        base_url="https://fanyi-api.baidu.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ) as http:
        with pytest.raises(TranslationError, match="HTTP 500"):
            await BaiduTranslateClient("appid", "key", http=http).translate("hello")


@pytest.mark.anyio
async def test_aliyun_client_signs_and_returns_translation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        params = dict(parse_qsl(request.url.query.decode()))
        assert params["Action"] == "TranslateGeneral"
        assert params["SourceText"] == "hello"
        assert params["AccessKeyId"] == "LTAI5tExample"
        assert params["SignatureMethod"] == "HMAC-SHA1"
        assert params["Signature"]
        return httpx.Response(200, json={"Code": "200", "Data": {"Translated": "你好"}, "RequestId": "req"})

    async with httpx.AsyncClient(
        base_url="https://mt.cn-hangzhou.aliyuncs.com",
        transport=httpx.MockTransport(handler),
    ) as http:
        assert await AliyunTranslateClient("LTAI5tExample", "secret", http=http).translate("hello") == "你好"


@pytest.mark.anyio
async def test_aliyun_client_raises_on_business_error() -> None:
    async with httpx.AsyncClient(
        base_url="https://mt.cn-hangzhou.aliyuncs.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"Code": "10001", "Message": "bad"})),
    ) as http:
        with pytest.raises(TranslationError, match="10001"):
            await AliyunTranslateClient("akid", "secret", http=http).translate("hello")


@pytest.mark.anyio
async def test_aliyun_client_raises_on_http_error() -> None:
    async with httpx.AsyncClient(
        base_url="https://mt.cn-hangzhou.aliyuncs.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(403)),
    ) as http:
        with pytest.raises(TranslationError, match="HTTP 403"):
            await AliyunTranslateClient("akid", "secret", http=http).translate("hello")


@pytest.mark.anyio
async def test_adapters_report_missing_secrets() -> None:
    assert (await baidu_adapter({}, None)).message == "百度翻译 Secret 尚未配置"
    result = await aliyun_adapter({}, {"access_key_id": "only-id"})
    assert result.success is False
    assert result.message == "阿里翻译 Secret 尚未配置"


@pytest.mark.anyio
@respx.mock
async def test_baidu_adapter_returns_latency_on_success() -> None:
    respx.get("https://fanyi-api.baidu.com/api/trans/vip/translate").mock(
        return_value=httpx.Response(200, json={"trans_result": [{"src": "hello", "dst": "你好"}]})
    )

    result = await baidu_adapter({}, {"app_id": "2026082500001", "app_key": "baidu-key"})

    assert result.success is True
    assert result.latency_ms is not None and result.latency_ms >= 0


@pytest.mark.anyio
@respx.mock
async def test_aliyun_adapter_failure_does_not_leak_secret() -> None:
    respx.get("https://mt.cn-hangzhou.aliyuncs.com/").mock(
        return_value=httpx.Response(200, json={"Code": "SignatureDoesNotMatch", "Message": "specify signature"})
    )

    result = await aliyun_adapter({}, {"access_key_id": "LTAI5tExample", "access_key_secret": "top-secret"})

    assert result.success is False
    assert result.message is not None
    assert "top-secret" not in result.message
    assert "LTAI5tExample" not in result.message
