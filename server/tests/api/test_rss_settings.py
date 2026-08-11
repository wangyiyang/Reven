from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def test_user_can_create_and_list_an_rss_source(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench

    created = client.post(
        "/api/rss/sources",
        json={
            "name": "OpenAI Blog",
            "feed_url": "https://openai.com/blog/rss.xml",
            "enabled": True,
        },
    )

    assert created.status_code == 201
    source = created.json()
    assert set(source) == {"id", "name", "feed_url", "enabled", "created_at", "updated_at"}
    assert source == {
        "id": source["id"],
        "name": "OpenAI Blog",
        "feed_url": "https://openai.com/blog/rss.xml",
        "enabled": True,
        "created_at": source["created_at"],
        "updated_at": source["updated_at"],
    }
    assert client.get("/api/rss/sources").json() == [source]


def test_user_can_edit_and_disable_an_rss_source(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    source = client.post(
        "/api/rss/sources",
        json={"name": "旧名称", "feed_url": "https://example.com/old.xml"},
    ).json()

    response = client.put(
        f"/api/rss/sources/{source['id']}",
        json={
            "name": "新名称",
            "feed_url": "https://example.com/new.xml",
            "enabled": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        **source,
        "name": "新名称",
        "feed_url": "https://example.com/new.xml",
        "enabled": False,
        "updated_at": response.json()["updated_at"],
    }


def test_user_can_delete_an_rss_source(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    source = client.post(
        "/api/rss/sources",
        json={"name": "待删除", "feed_url": "https://example.com/delete.xml"},
    ).json()

    response = client.delete(f"/api/rss/sources/{source['id']}")

    assert response.status_code == 204
    assert client.get("/api/rss/sources").json() == []


def test_user_can_create_and_list_positive_and_negative_keywords(
    workbench: tuple[TestClient, object],
) -> None:
    client, _ = workbench

    positive = client.post(
        "/api/rss/keywords",
        json={"term": "AI agents", "kind": "positive"},
    )
    negative = client.post(
        "/api/rss/keywords",
        json={"term": "sponsored post", "kind": "negative", "enabled": False},
    )

    assert positive.status_code == 201
    assert negative.status_code == 201
    assert client.get("/api/rss/keywords").json() == [positive.json(), negative.json()]


def test_user_can_edit_reclassify_and_disable_a_keyword(
    workbench: tuple[TestClient, object],
) -> None:
    client, _ = workbench
    keyword = client.post(
        "/api/rss/keywords",
        json={"term": "old keyword", "kind": "positive"},
    ).json()

    response = client.put(
        f"/api/rss/keywords/{keyword['id']}",
        json={"term": "new keyword", "kind": "negative", "enabled": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        **keyword,
        "term": "new keyword",
        "kind": "negative",
        "enabled": False,
        "updated_at": response.json()["updated_at"],
    }


def test_user_can_delete_a_keyword(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    keyword = client.post(
        "/api/rss/keywords",
        json={"term": "temporary", "kind": "positive"},
    ).json()

    response = client.delete(f"/api/rss/keywords/{keyword['id']}")

    assert response.status_code == 204
    assert client.get("/api/rss/keywords").json() == []


def test_duplicate_rss_source_url_is_rejected(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    client.post(
        "/api/rss/sources",
        json={"name": "第一个", "feed_url": "https://example.com/feed.xml"},
    )

    response = client.post(
        "/api/rss/sources",
        json={"name": "第二个", "feed_url": "https://EXAMPLE.com/feed.xml"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "RSS_SOURCE_URL_CONFLICT",
        "message": "RSS 源地址已存在",
    }


def test_keyword_cannot_exist_in_both_lists(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    client.post(
        "/api/rss/keywords",
        json={"term": "ＡＩ   Agents", "kind": "positive"},
    )

    response = client.post(
        "/api/rss/keywords",
        json={"term": "ai agents", "kind": "negative"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "RSS_KEYWORD_CONFLICT",
        "message": "关键词已存在于正向或反向列表",
    }


def test_keyword_edit_cannot_create_a_duplicate(workbench: tuple[TestClient, object]) -> None:
    client, _ = workbench
    client.post(
        "/api/rss/keywords",
        json={"term": "AI Agents", "kind": "positive"},
    )
    keyword = client.post(
        "/api/rss/keywords",
        json={"term": "temporary", "kind": "negative"},
    ).json()

    response = client.put(
        f"/api/rss/keywords/{keyword['id']}",
        json={"term": "ａｉ   agents", "kind": "negative"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "RSS_KEYWORD_CONFLICT",
        "message": "关键词已存在于正向或反向列表",
    }


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/rss/sources", {"name": "  ", "feed_url": "https://example.com/feed"}),
        ("/api/rss/sources", {"name": "无效协议", "feed_url": "ftp://example.com/feed"}),
        ("/api/rss/keywords", {"term": "  ", "kind": "positive"}),
        ("/api/rss/keywords", {"term": "AI", "kind": "neutral"}),
        ("/api/rss/keywords", {"term": "ﬃ" * 200, "kind": "positive"}),
    ],
)
def test_invalid_rss_settings_are_rejected(
    workbench: tuple[TestClient, object],
    path: str,
    payload: dict[str, object],
) -> None:
    client, _ = workbench

    response = client.post(path, json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("resource", "payload", "error_code"),
    [
        (
            "sources",
            {"name": "不存在", "feed_url": "https://example.com/missing"},
            "RSS_SOURCE_NOT_FOUND",
        ),
        (
            "keywords",
            {"term": "不存在", "kind": "positive"},
            "RSS_KEYWORD_NOT_FOUND",
        ),
    ],
)
def test_updating_missing_rss_setting_returns_not_found(
    workbench: tuple[TestClient, object],
    resource: str,
    payload: dict[str, object],
    error_code: str,
) -> None:
    client, _ = workbench

    response = client.put(f"/api/rss/{resource}/{uuid4()}", json=payload)

    assert response.status_code == 404
    assert response.json()["code"] == error_code
