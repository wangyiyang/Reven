import json

import httpx
import respx
from fastapi.testclient import TestClient

WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/connection-test"


def test_feishu_connection_test_sends_signed_message(client: TestClient) -> None:
    configured = client.put(
        "/api/integrations/feishu",
        json={
            "public_config": {"name": "发布通知"},
            "secret": {
                "webhook_url": WEBHOOK_URL,
                "signing_secret": "feishu-signing-secret",
            },
        },
    )
    assert configured.status_code == 200

    with respx.mock(assert_all_called=True) as router:
        request = router.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, json={"code": 0}))
        response = client.post("/api/integrations/feishu/test")

    assert response.status_code == 200
    assert response.json()["connection_status"] == "连接正常"
    payload = json.loads(request.calls[0].request.content)
    assert payload["timestamp"].isdigit()
    assert payload["sign"]
