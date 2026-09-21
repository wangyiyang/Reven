import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).parents[3]


@pytest.fixture
def notifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("notify_feishu_deploy", ROOT / "scripts" / "notify_feishu_deploy.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def configuration() -> dict[str, str]:
    return {
        "FEISHU_APP_ID": "cli_test",
        "FEISHU_APP_SECRET": "test-app-secret",
        "FEISHU_NOTIFY_OPEN_IDS": "ou_first, ou_second\nou_first",
        "DEPLOY_IMAGE": "example.invalid/reven@sha256:test",
        "JOB_STATUS": "success",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "example/reven",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }


def test_deploy_notification_authenticates_and_sends_once_per_user(
    notifier: ModuleType,
    configuration: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests: list[Any] = []

    def request_http(request: Any, **_: object) -> io.BytesIO:
        requests.append(request)
        result = {"code": 0, "tenant_access_token": "test-tenant-token"} if len(requests) == 1 else {"code": 0}
        return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setattr(notifier, "urlopen", request_http)
    assert notifier.send_notification(configuration) == 0
    assert len(requests) == 3
    assert requests[0].full_url == "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    assert json.loads(requests[0].data)["app_id"] == configuration["FEISHU_APP_ID"]
    messages = [json.loads(request.data) for request in requests[1:]]
    assert [message["receive_id"] for message in messages] == ["ou_first", "ou_second"]
    for request, message in zip(requests[1:], messages, strict=True):
        assert request.full_url == "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
        assert request.get_header("Authorization") == "Bearer test-tenant-token"
        content = json.loads(message["content"])["text"]
        assert "Reven production success: example.invalid/reven@sha256:test" in content
        assert "https://github.com/example/reven/actions/runs/123" in content
        assert message["msg_type"] == "text"
    assert messages[0]["uuid"] != messages[1]["uuid"]
    output = capsys.readouterr().out
    assert "2 位接收人" in output
    assert configuration["FEISHU_APP_SECRET"] not in output
    assert "test-tenant-token" not in output


def test_retries_reuse_message_uuid(
    notifier: ModuleType, configuration: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: list[dict[str, object]] = []

    def post(path: str, payload: dict[str, object], token: str | None = None) -> dict[str, object]:
        if token:
            messages.append(payload)
        return {"code": 0, "tenant_access_token": "test-token"}

    monkeypatch.setattr(notifier, "post", post)
    notifier.send_notification(configuration)
    notifier.send_notification(configuration)
    assert [message["uuid"] for message in messages[:2]] == [message["uuid"] for message in messages[2:]]


def test_unconfigured_notification_skips_without_network(notifier: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_request(*_: object) -> None:
        pytest.fail("未配置部署通知时不能发请求")

    monkeypatch.setattr(notifier, "post", unexpected_request)
    assert notifier.send_notification({}) == 0


@pytest.mark.parametrize("missing", ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_NOTIFY_OPEN_IDS"])
def test_partial_configuration_fails(notifier: ModuleType, configuration: dict[str, str], missing: str) -> None:
    del configuration[missing]
    with pytest.raises(ValueError, match="配置不完整"):
        notifier.send_notification(configuration)


@pytest.mark.parametrize("recipients", ["oc_group", "ou_valid,bad-id", ",", "on_union"])
def test_invalid_recipients_fail_before_authentication(
    notifier: ModuleType, configuration: dict[str, str], recipients: str
) -> None:
    configuration["FEISHU_NOTIFY_OPEN_IDS"] = recipients
    with pytest.raises(ValueError, match="Open ID"):
        notifier.send_notification(configuration)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"code": 99991672, "msg": "sensitive-provider-body"}, "code=99991672"),
        ({"code": "sensitive-provider-body"}, "invalid_response"),
        ({"code": False}, "invalid_response"),
        ({"code": 0.0}, "invalid_response"),
        ({}, "invalid_response"),
        (["sensitive-provider-body"], "响应格式无效"),
    ],
)
def test_application_errors_are_redacted(
    notifier: ModuleType, monkeypatch: pytest.MonkeyPatch, response: object, error: str
) -> None:
    monkeypatch.setattr(notifier, "urlopen", lambda *_args, **_kwargs: io.BytesIO(json.dumps(response).encode()))
    with pytest.raises(RuntimeError, match=error) as caught:
        notifier.post("/im/v1/messages", {})
    assert "sensitive-provider-body" not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("https://open.feishu.cn", 403, "sensitive-provider-body", None, None),
        URLError("sensitive-provider-body"),
    ],
)
def test_transport_errors_are_redacted(
    notifier: ModuleType, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def request_http(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(notifier, "urlopen", request_http)
    with pytest.raises(RuntimeError) as caught:
        notifier.post("/im/v1/messages", {})
    assert "sensitive-provider-body" not in str(caught.value)
