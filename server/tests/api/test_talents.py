from datetime import date, timedelta
from uuid import uuid4

import pytest


def _create_talent(client, **overrides):  # type: ignore[no-untyped-def]
    payload = {
        "name": "设计师小李",
        "organization": "自由职业",
        "tags": ["设计", "品牌"],
        "capability": "品牌视觉设计",
        "engagement_terms": "预付 50%",
        "availability": "每周 20 小时",
        "rate_amount": "500.00",
        "rate_unit": "按天",
        "rating": 4,
        "status": "候选",
        "notes": "朋友推荐",
    }
    payload.update(overrides)
    response = client.post("/api/talents", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_interaction(client, talent_id: str, **overrides):  # type: ignore[no-untyped-def]
    payload = {
        "occurred_on": date.today().isoformat(),
        "channel": "微信",
        "summary": "沟通了品牌设计需求",
        "next_action": "发送作品集",
        "next_due_on": (date.today() + timedelta(days=3)).isoformat(),
    }
    payload.update(overrides)
    response = client.post(f"/api/talents/{talent_id}/interactions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_talent_crud_and_filters(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    designer = _create_talent(client)
    developer = _create_talent(
        client,
        name="工程师小王",
        organization="某科技公司",
        tags=["开发"],
        status="接洽中",
    )

    listing = client.get("/api/talents")
    assert [item["name"] for item in listing.json()] == ["工程师小王", "设计师小李"]
    by_status = client.get("/api/talents", params={"status": "接洽中"})
    assert [item["id"] for item in by_status.json()] == [developer["id"]]
    by_name = client.get("/api/talents", params={"q": "设计师"})
    assert [item["id"] for item in by_name.json()] == [designer["id"]]
    by_organization = client.get("/api/talents", params={"q": "科技公司"})
    assert [item["id"] for item in by_organization.json()] == [developer["id"]]
    by_tag = client.get("/api/talents", params={"tag": "开发"})
    assert [item["id"] for item in by_tag.json()] == [developer["id"]]

    detail = client.get(f"/api/talents/{designer['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "候选"

    updated = client.patch(
        f"/api/talents/{designer['id']}",
        json={"status": "已合作", "notes": "完成首个项目"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "已合作"
    assert client.get(f"/api/talents/{designer['id']}").json()["notes"] == "完成首个项目"

    assert client.delete(f"/api/talents/{developer['id']}").status_code == 204
    missing = client.get(f"/api/talents/{developer['id']}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "TALENT_NOT_FOUND"


def test_talent_due_filters_use_earliest_next_due(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    overdue = _create_talent(client, name="逾期人才")
    _create_interaction(client, overdue["id"], next_due_on=(date.today() - timedelta(days=1)).isoformat())
    _create_interaction(client, overdue["id"], next_due_on=(date.today() + timedelta(days=5)).isoformat())
    today = _create_talent(client, name="今日人才")
    _create_interaction(client, today["id"], next_due_on=date.today().isoformat())
    upcoming = _create_talent(client, name="未来人才")
    _create_interaction(client, upcoming["id"], next_due_on=(date.today() + timedelta(days=2)).isoformat())
    none = _create_talent(client, name="无计划人才")
    _create_interaction(client, none["id"], next_due_on=None)

    def ids(due: str) -> list[str]:
        return [item["id"] for item in client.get("/api/talents", params={"due": due}).json()]

    assert ids("overdue") == [overdue["id"]]
    assert ids("today") == [today["id"]]
    assert ids("upcoming") == [upcoming["id"]]
    assert ids("none") == [none["id"]]


def test_talent_query_escapes_like_wildcards(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    percent = _create_talent(client, name="100% 投入")
    _create_talent(client, name="普通人才")

    response = client.get("/api/talents", params={"q": "%"})

    assert [item["id"] for item in response.json()] == [percent["id"]]


def test_talent_validation_is_explicit(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    assert client.post("/api/talents", json={"organization": "缺名字"}).status_code == 422
    assert client.post("/api/talents", json={"name": "未知字段", "secret": "no"}).status_code == 422
    assert client.post("/api/talents", json={"name": "坏状态", "status": "任意状态"}).status_code == 422
    assert client.get("/api/talents", params={"status": "任意状态"}).status_code == 422
    assert client.get("/api/talents", params={"due": "任意过滤"}).status_code == 422
    assert client.post("/api/talents", json={"name": "评分过低", "rating": 0}).status_code == 422
    assert client.post("/api/talents", json={"name": "评分过高", "rating": 6}).status_code == 422
    half_rate = client.post("/api/talents", json={"name": "只填金额", "rate_amount": "500.00"})
    assert half_rate.status_code == 422
    half_unit = client.post("/api/talents", json={"name": "只填单位", "rate_unit": "按天"})
    assert half_unit.status_code == 422

    talent = _create_talent(client)
    assert client.patch(f"/api/talents/{talent['id']}", json={"name": None}).status_code == 422
    assert client.patch(f"/api/talents/{talent['id']}", json={"status": None}).status_code == 422
    assert client.patch(f"/api/talents/{talent['id']}", json={"tags": None}).status_code == 422


@pytest.mark.parametrize("talent_status", ["候选", "接洽中", "已合作", "搁置"])
def test_each_talent_status_can_be_saved_and_filtered(workbench, talent_status: str) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    talent = _create_talent(client, name=f"{talent_status}示例", status=talent_status)

    response = client.get("/api/talents", params={"status": talent_status})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [talent["id"]]


@pytest.mark.parametrize("channel", ["面谈", "电话语音", "微信", "邮件"])
def test_each_interaction_channel_can_be_saved(workbench, channel: str) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    talent = _create_talent(client)

    interaction = _create_interaction(client, talent["id"], channel=channel)

    assert interaction["channel"] == channel
    assert (
        client.post(
            f"/api/talents/{talent['id']}/interactions",
            json={"occurred_on": date.today().isoformat(), "channel": "飞书"},
        ).status_code
        == 422
    )


def test_structured_fields_round_trip_and_rate_pair(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    talent = _create_talent(client, tags=["设计", "品牌", "插画"])

    detail = client.get(f"/api/talents/{talent['id']}").json()
    assert detail["tags"] == ["设计", "品牌", "插画"]
    assert detail["rate_amount"] == "500.00"
    assert detail["rate_unit"] == "按天"
    assert detail["rating"] == 4

    retagged = client.patch(f"/api/talents/{talent['id']}", json={"tags": ["插画"]})
    assert retagged.status_code == 200, retagged.text
    assert retagged.json()["tags"] == ["插画"]

    half_clear = client.patch(f"/api/talents/{talent['id']}", json={"rate_amount": None})
    assert half_clear.status_code == 422
    assert half_clear.json()["code"] == "TALENT_RATE_PAIR_INCOMPLETE"
    cleared = client.patch(f"/api/talents/{talent['id']}", json={"rate_amount": None, "rate_unit": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["rate_amount"] is None
    assert cleared.json()["rate_unit"] is None

    rerated = client.patch(f"/api/talents/{talent['id']}", json={"rating": None})
    assert rerated.status_code == 200, rerated.text
    assert rerated.json()["rating"] is None
    assert client.patch(f"/api/talents/{talent['id']}", json={"rating": 7}).status_code == 422


def test_interactions_nested_scoped_and_cascade(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    talent = _create_talent(client)
    other = _create_talent(client, name="其他人才")
    older = _create_interaction(
        client,
        talent["id"],
        occurred_on=(date.today() - timedelta(days=2)).isoformat(),
        summary="初次沟通",
    )
    newer = _create_interaction(client, talent["id"])

    timeline = client.get(f"/api/talents/{talent['id']}/interactions").json()
    assert [item["id"] for item in timeline] == [newer["id"], older["id"]]

    # 追加跟进刷新人才 updated_at，列表按最近活跃排序
    listing = client.get("/api/talents").json()
    assert listing[0]["id"] == talent["id"]

    edited = client.patch(
        f"/api/talents/interactions/{older['id']}",
        json={"summary": "修正后的沟通记录"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["summary"] == "修正后的沟通记录"
    assert client.patch(f"/api/talents/interactions/{older['id']}", json={"occurred_on": None}).status_code == 422
    assert client.patch(f"/api/talents/interactions/{older['id']}", json={"channel": None}).status_code == 422

    missing_interaction = client.patch(f"/api/talents/interactions/{uuid4()}", json={"summary": "无"})
    assert missing_interaction.status_code == 404
    assert missing_interaction.json()["code"] == "TALENT_INTERACTION_NOT_FOUND"
    assert client.delete(f"/api/talents/interactions/{uuid4()}").status_code == 404
    assert client.get(f"/api/talents/{uuid4()}/interactions").status_code == 404
    not_found = client.post(
        f"/api/talents/{uuid4()}/interactions",
        json={"occurred_on": date.today().isoformat(), "channel": "微信"},
    )
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "TALENT_NOT_FOUND"

    assert client.delete(f"/api/talents/interactions/{newer['id']}").status_code == 204
    remaining = client.get(f"/api/talents/{talent['id']}/interactions").json()
    assert [item["id"] for item in remaining] == [older["id"]]

    # 删除人才级联删除跟进记录
    orphan = _create_interaction(client, other["id"])
    assert client.delete(f"/api/talents/{other['id']}").status_code == 204
    assert client.get(f"/api/talents/{other['id']}/interactions").status_code == 404
    assert client.patch(f"/api/talents/interactions/{orphan['id']}", json={"summary": "无"}).status_code == 404
