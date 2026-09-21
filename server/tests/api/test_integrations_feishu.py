"""Retired webhook provider is rejected even before parsing its body."""

from fastapi.testclient import TestClient


def test_retired_feishu_provider_routes_return_unknown(client: TestClient) -> None:
    responses = (
        client.get("/api/integrations/feishu"),
        client.put("/api/integrations/feishu", content="not-json"),
        client.delete("/api/integrations/feishu/secret"),
        client.post("/api/integrations/feishu/test"),
    )
    for response in responses:
        assert response.status_code == 404
        assert response.json()["code"] == "INTEGRATION_PROVIDER_UNKNOWN"
