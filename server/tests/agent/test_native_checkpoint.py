from uuid import uuid4

import pytest
from psycopg.conninfo import conninfo_to_dict
from reven.agent.checkpoint import _serializer, postgres_conninfo
from reven.agent.context import AgentContext
from sqlalchemy import URL


def test_conninfo_preserves_special_characters_and_maps_asyncpg_ssl() -> None:
    url = URL.create(
        "postgresql+asyncpg",
        username="u@name",
        password="p@ss:'/?#%",
        host="::1",
        port=55433,
        database="reven_test",
        query={"ssl": "require", "sslrootcert": "/test/root.pem"},
    )
    values = conninfo_to_dict(postgres_conninfo(url.render_as_string(hide_password=False)))
    assert values["host"] == "::1"
    assert values["port"] == "55433"
    assert values["user"] == "u@name"
    assert values["password"] == "p@ss:'/?#%"
    assert values["sslmode"] == "require"
    assert values["sslrootcert"] == "/test/root.pem"


@pytest.mark.parametrize("ssl, expected", [("true", "require"), ("false", "disable"), ("verify-full", "verify-full")])
def test_conninfo_ssl_mapping(ssl: str, expected: str) -> None:
    assert conninfo_to_dict(postgres_conninfo(f"postgresql://test@localhost/test?ssl={ssl}"))["sslmode"] == expected


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///test.db",
        "postgresql+asyncpg://u:private-value@localhost/test?statement_cache_size=0",
        "postgresql+asyncpg://u:private-value@localhost/test?ssl=true&sslmode=require",
        "postgresql+asyncpg://u:private-value@localhost/test?sslmode=require&sslmode=disable",
    ],
)
def test_unsupported_database_parameters_fail_without_echoing_url(url: str) -> None:
    with pytest.raises(ValueError) as error:
        postgres_conninfo(url)
    assert "private-value" not in str(error.value)


def test_serializer_is_strict_without_env_and_cannot_restore_application_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGGRAPH_STRICT_MSGPACK", raising=False)
    serializer = _serializer()
    context = AgentContext("test-owner", uuid4(), uuid4())
    assert serializer.loads_typed(serializer.dumps_typed(context)) == {
        "owner_id": context.owner_id,
        "session_id": context.session_id,
        "run_id": context.run_id,
    }
    assert serializer.loads_typed(serializer.dumps_typed({"id": context.run_id})) == {"id": context.run_id}
    assert serializer.pickle_fallback is False
