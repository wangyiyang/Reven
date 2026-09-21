import pytest
from fastapi.testclient import TestClient
from reven.api.schemas.integrations import PUT_MODELS
from reven.app import create_app
from reven.integrations.providers import SUPPORTED_INTEGRATION_PROVIDERS
from reven.integrations.service import SECRET_HINT_FIELDS

RETIRED_PROVIDERS = ("notion", "github", "wechat")


@pytest.mark.parametrize("provider", (*RETIRED_PROVIDERS, "gitlab"))
@pytest.mark.parametrize(
    ("method", "suffix"),
    [("GET", ""), ("PUT", ""), ("DELETE", "/secret"), ("POST", "/test")],
)
def test_retired_and_unknown_providers_are_rejected_before_parsing_body(
    client: TestClient, provider: str, method: str, suffix: str
) -> None:
    response = client.request(method, f"/api/integrations/{provider}{suffix}", content="invalid-json")

    assert response.status_code == 404
    assert response.json()["code"] == "INTEGRATION_PROVIDER_UNKNOWN"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/articles"),
        ("GET", "/api/articles/11111111-1111-1111-1111-111111111111"),
        ("POST", "/api/articles/11111111-1111-1111-1111-111111111111/publish"),
        ("POST", "/api/sync/notion"),
        ("POST", "/api/integrations/notion/bootstrap-schema"),
    ],
)
def test_retired_routes_return_404(workbench, method: str, path: str) -> None:
    client, _ = workbench

    assert client.request(method, path).status_code == 404


def test_retired_routes_are_absent_from_openapi_and_provider_schemas_stay_in_sync() -> None:
    paths = create_app(start_background_tasks=False).openapi()["paths"]

    assert all(not path.startswith(("/api/articles", "/api/sync")) for path in paths)
    assert "/api/integrations/notion/bootstrap-schema" not in paths
    assert set(PUT_MODELS) == set(SECRET_HINT_FIELDS) == set(SUPPORTED_INTEGRATION_PROVIDERS)
    assert set(RETIRED_PROVIDERS).isdisjoint(SUPPORTED_INTEGRATION_PROVIDERS)
