"""Agent Worker 服务与 RemoteAgentWorkerClient 协议测试。"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport
from reven.agent.client import RemoteAgentWorkerClient
from reven.agent.errors import AgentModelUnavailableError, AgentNotConfiguredError, AgentRuntimeError
from reven.agent.worker import app as worker_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def worker_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=worker_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testworker") as client:
        yield client


@pytest.mark.anyio
async def test_remote_worker_client_lifecycle_and_chat(respx_mock: object) -> None:
    import respx

    respx.get("http://agent-worker:8001/internal/agent/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "available": True,
                "configured": True,
                "default_model_ref": "deepseek-official/deepseek-v4-flash",
            },
        )
    )
    respx.post("http://agent-worker:8001/internal/agent/chat").mock(
        return_value=httpx.Response(200, json={"session_id": "sess-1", "response": "Hello from worker"})
    )

    client = RemoteAgentWorkerClient("http://agent-worker:8001", run_timeout_seconds=5.0)
    assert not client.available

    await client.start()
    assert client.available
    assert client.configured
    assert client.default_model_ref == "deepseek-official/deepseek-v4-flash"

    session_id, response = await client.chat("ping", "sess-1")
    assert session_id == "sess-1"
    assert response == "Hello from worker"

    await client.close()


@pytest.mark.anyio
async def test_remote_worker_client_error_mappings(respx_mock: object) -> None:
    import respx

    respx.post("http://agent-worker:8001/internal/agent/chat").mock(
        return_value=httpx.Response(503, json={"code": "AGENT_NOT_CONFIGURED", "message": "Not configured"})
    )
    client = RemoteAgentWorkerClient("http://agent-worker:8001")
    await client.start()

    with pytest.raises(AgentNotConfiguredError):
        await client.chat("ping")

    respx.post("http://agent-worker:8001/internal/agent/chat").mock(
        return_value=httpx.Response(404, json={"code": "AGENT_MODEL_UNAVAILABLE", "message": "Model not available"})
    )
    with pytest.raises(AgentModelUnavailableError):
        await client.chat("ping", model="invalid/model")

    respx.post("http://agent-worker:8001/internal/agent/chat").mock(
        return_value=httpx.Response(502, json={"code": "AGENT_CHAT_FAILED", "message": "Crash"})
    )
    with pytest.raises(AgentRuntimeError) as exc_info:
        await client.chat("ping")
    assert exc_info.value.code == "AGENT_CHAT_FAILED"

    await client.close()


@pytest.mark.anyio
async def test_worker_endpoints_integration(worker_client: httpx.AsyncClient) -> None:
    # 模拟 runtime 挂在 app.state.runtime 上
    mock_runtime = AsyncMock()
    mock_runtime.available = True
    mock_runtime.configured = True
    mock_runtime.default_model_ref = "deepseek-official/test-model"
    mock_runtime.chat.return_value = ("session-123", "Worker reply")

    worker_app.state.runtime = mock_runtime

    # 测试 health
    resp = await worker_client.get("/internal/agent/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["default_model_ref"] == "deepseek-official/test-model"

    # 测试 chat
    resp = await worker_client.post(
        "/internal/agent/chat",
        json={"message": "hello", "session_id": "session-123", "model": None},
    )
    assert resp.status_code == 200
    assert resp.json() == {"session_id": "session-123", "response": "Worker reply"}


@pytest.mark.anyio
async def test_agent_service_with_remote_worker(respx_mock: object) -> None:
    import respx
    from reven.agent.service import AgentService

    respx.get("http://agent-worker:8001/internal/agent/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "available": True,
                "configured": True,
                "default_model_ref": "deepseek-official/test-model",
            },
        )
    )
    respx.post("http://agent-worker:8001/internal/agent/chat").mock(
        return_value=httpx.Response(200, json={"session_id": "sess-remote", "response": "Answer from worker"})
    )

    client = RemoteAgentWorkerClient("http://agent-worker:8001")
    await client.start()

    service = AgentService(client)
    turn = await service.chat("hello", "sess-remote")
    assert turn.session_id == "sess-remote"
    assert turn.response == "Answer from worker"
    assert turn.model_ref == "deepseek-official/test-model"

    await client.close()


@pytest.mark.anyio
async def test_worker_auto_recovers_when_configured(
    worker_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path
    from unittest.mock import MagicMock

    from reven.agent.config import AgentConfig

    mock_runtime = AsyncMock()
    mock_runtime.available = False
    mock_runtime.configured = False
    mock_runtime.default_model_ref = None

    worker_app.state.runtime = mock_runtime
    worker_app.state.settings = MagicMock()
    worker_app.state.credentials = MagicMock()
    worker_app.state.last_config_check = 0.0

    target_config = AgentConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url=None,
        api_key="test-key",
        dsh_home=Path("/tmp/dsh"),
        cwd=Path("/tmp/cwd"),
    )

    async def fake_resolve(credentials: object, settings: object) -> AgentConfig:
        mock_runtime.available = True
        mock_runtime.configured = True
        mock_runtime.default_model_ref = "deepseek/deepseek-chat"
        return target_config

    monkeypatch.setattr("reven.agent.worker.resolve_agent_config", fake_resolve)

    resp = await worker_client.get("/internal/agent/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["available"] is True
    assert resp.json()["configured"] is True
    assert resp.json()["default_model_ref"] == "deepseek/deepseek-chat"
    mock_runtime.reload_config.assert_awaited_once_with(target_config)
