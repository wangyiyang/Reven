from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from reven.scheduling import SHANGHAI


def _today() -> date:
    # 服务端按上海时区计算“今天”（见 api/routes/talents.py），测试必须用同一时钟，
    # 否则在 UTC 16:00-24:00 窗口内（CI Runner 为 UTC）两侧日期差一天，due=today 匹配为空
    return datetime.now(SHANGHAI).date()


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
        "occurred_on": _today().isoformat(),
        "channel": "微信",
        "summary": "沟通了品牌设计需求",
        "next_action": "发送作品集",
        "next_due_on": (_today() + timedelta(days=3)).isoformat(),
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


def test_talent_due_filters_use_latest_interaction_next_due(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    overdue = _create_talent(client, name="逾期人才")
    _create_interaction(
        client,
        overdue["id"],
        occurred_on=(_today() - timedelta(days=10)).isoformat(),
        next_due_on=(_today() + timedelta(days=30)).isoformat(),
    )
    _create_interaction(client, overdue["id"], next_due_on=(_today() - timedelta(days=1)).isoformat())

    today = _create_talent(client, name="今日人才")
    _create_interaction(client, today["id"], next_due_on=_today().isoformat())

    # 旧记录已逾期，但最新记录改到未来 → 按最新日期分档（min 语义会误判 overdue）
    upcoming = _create_talent(client, name="未来人才")
    _create_interaction(
        client,
        upcoming["id"],
        occurred_on=(_today() - timedelta(days=10)).isoformat(),
        next_due_on=(_today() - timedelta(days=5)).isoformat(),
    )
    _create_interaction(client, upcoming["id"], next_due_on=(_today() + timedelta(days=2)).isoformat())

    # 旧记录有逾期日期，最新记录无日期 → 旧日期不再冒泡（min 语义会误判 overdue）
    none = _create_talent(client, name="无计划人才")
    _create_interaction(
        client,
        none["id"],
        occurred_on=(_today() - timedelta(days=10)).isoformat(),
        next_due_on=(_today() - timedelta(days=5)).isoformat(),
    )
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

    # 联系方式：email 格式与字段长度
    assert client.post("/api/talents", json={"name": "坏邮箱", "email": "not-an-email"}).status_code == 422
    assert client.post("/api/talents", json={"name": "长邮箱", "email": f"{'a' * 309}@example.com"}).status_code == 422
    assert client.post("/api/talents", json={"name": "长电话", "phone": "1" * 51}).status_code == 422
    assert client.post("/api/talents", json={"name": "长微信", "wechat": "w" * 101}).status_code == 422
    # preferences：非数组、非字符串元素、超量
    assert client.post("/api/talents", json={"name": "坏喜好", "preferences": "不是数组"}).status_code == 422
    assert client.post("/api/talents", json={"name": "坏喜好元素", "preferences": [123]}).status_code == 422
    too_many = client.post("/api/talents", json={"name": "喜好超量", "preferences": [f"喜好{i}" for i in range(21)]})
    assert too_many.status_code == 422

    talent = _create_talent(client)
    assert client.patch(f"/api/talents/{talent['id']}", json={"name": None}).status_code == 422
    assert client.patch(f"/api/talents/{talent['id']}", json={"status": None}).status_code == 422
    assert client.patch(f"/api/talents/{talent['id']}", json={"tags": None}).status_code == 422
    assert client.patch(f"/api/talents/{talent['id']}", json={"preferences": None}).status_code == 422
    assert client.patch(f"/api/talents/{talent['id']}", json={"email": "仍然不是邮箱"}).status_code == 422


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
            json={"occurred_on": _today().isoformat(), "channel": "飞书"},
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
        occurred_on=(_today() - timedelta(days=2)).isoformat(),
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
        json={"occurred_on": _today().isoformat(), "channel": "微信"},
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


def test_profile_fields_round_trip(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    talent = _create_talent(
        client,
        phone=" 13800001111 ",
        email="designer@example.com",
        wechat="wx-designer",
        preferences=[" 咖啡 ", "咖啡", "", " 远程工作 "],
    )

    detail = client.get(f"/api/talents/{talent['id']}").json()
    assert detail["phone"] == "13800001111"
    assert detail["email"] == "designer@example.com"
    assert detail["wechat"] == "wx-designer"
    # preferences：元素 trim、去空、保序去重
    assert detail["preferences"] == ["咖啡", "远程工作"]
    # 空串归 null
    assert _create_talent(client, name="空联系方式", phone="   ", email="")["email"] is None

    cleared = client.patch(
        f"/api/talents/{talent['id']}",
        json={"phone": None, "email": None, "wechat": "", "preferences": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["phone"] is None
    assert cleared.json()["email"] is None
    assert cleared.json()["wechat"] is None
    assert cleared.json()["preferences"] == []


@pytest.mark.parametrize(
    ("resource", "missing_code", "payload", "required_field"),
    [
        pytest.param(
            "experiences",
            "TALENT_EXPERIENCE_NOT_FOUND",
            {"company": "远山设计", "title": "视觉设计师", "description": "负责品牌视觉", "start_on": "2023-03-01"},
            "company",
            id="experiences",
        ),
        pytest.param(
            "educations",
            "TALENT_EDUCATION_NOT_FOUND",
            {"school": "中央美术学院", "degree": "本科", "major": "视觉传达", "start_on": "2016-09-01"},
            "school",
            id="educations",
        ),
    ],
)
def test_profile_tables_nested_scoped_and_cascade(  # type: ignore[no-untyped-def]
    workbench,
    resource: str,
    missing_code: str,
    payload: dict[str, str],
    required_field: str,
) -> None:
    client, _factory = workbench
    talent = _create_talent(client)
    other = _create_talent(client, name="其他人才")

    def create(talent_id: str, **overrides: object) -> dict[str, object]:
        body = {**payload, **overrides}
        response = client.post(f"/api/talents/{talent_id}/{resource}", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    ended = create(talent["id"], start_on="2020-01-01", end_on="2021-01-01")
    current = create(talent["id"], start_on="2022-01-01", end_on=None)
    older = create(talent["id"], start_on="2018-01-01", end_on="2019-01-01")

    # 排序：至今（end_on NULL）最前，其余按 start_on 倒序
    timeline = client.get(f"/api/talents/{talent['id']}/{resource}").json()
    assert [item["id"] for item in timeline] == [current["id"], ended["id"], older["id"]]

    # 校验：end_on < start_on、缺必填、未知字段 → 422
    reversed_range = client.post(f"/api/talents/{talent['id']}/{resource}", json={**payload, "end_on": "2010-01-01"})
    assert reversed_range.status_code == 422
    missing_required = {key: value for key, value in payload.items() if key != required_field}
    assert client.post(f"/api/talents/{talent['id']}/{resource}", json=missing_required).status_code == 422
    assert client.post(f"/api/talents/{talent['id']}/{resource}", json={**payload, "unknown": "x"}).status_code == 422
    no_start = {key: value for key, value in payload.items() if key != "start_on"}
    assert client.post(f"/api/talents/{talent['id']}/{resource}", json=no_start).status_code == 422

    # PUT：部分字段更新 + 显式清空 end_on（至今）；必填字段显式 null → 422
    edited = client.put(f"/api/talents/{talent['id']}/{resource}/{ended['id']}", json={"end_on": None})
    assert edited.status_code == 200, edited.text
    assert edited.json()["end_on"] is None
    assert edited.json()["start_on"] == "2020-01-01"
    null_required = client.put(f"/api/talents/{talent['id']}/{resource}/{ended['id']}", json={required_field: None})
    assert null_required.status_code == 422
    null_start = client.put(f"/api/talents/{talent['id']}/{resource}/{ended['id']}", json={"start_on": None})
    assert null_start.status_code == 422

    # 区间校验：单边提交与现值合并后非法（service 合并校验）与双字段提交非法（schema 校验）均 422
    merged_invalid = client.put(
        f"/api/talents/{talent['id']}/{resource}/{older['id']}",
        json={"end_on": "2017-01-01"},
    )
    assert merged_invalid.status_code == 422
    assert merged_invalid.json()["code"] == "TALENT_DATE_RANGE_INVALID"
    both_invalid = client.put(
        f"/api/talents/{talent['id']}/{resource}/{older['id']}",
        json={"start_on": "2020-01-01", "end_on": "2019-06-01"},
    )
    assert both_invalid.status_code == 422

    # 越父访问 404，不泄露记录存在于其他人才名下
    cross = client.put(f"/api/talents/{other['id']}/{resource}/{current['id']}", json={"start_on": "2024-01-01"})
    assert cross.status_code == 404
    assert cross.json()["code"] == missing_code
    assert client.delete(f"/api/talents/{other['id']}/{resource}/{current['id']}").status_code == 404
    missing = client.put(f"/api/talents/{talent['id']}/{resource}/{uuid4()}", json={"start_on": "2024-01-01"})
    assert missing.status_code == 404
    assert missing.json()["code"] == missing_code
    assert client.get(f"/api/talents/{uuid4()}/{resource}").status_code == 404
    not_found = client.post(f"/api/talents/{uuid4()}/{resource}", json=payload)
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "TALENT_NOT_FOUND"

    # 子表写操作不 bump 父级 updated_at（履历修订 ≠ 接洽活跃）
    before = client.get(f"/api/talents/{talent['id']}").json()["updated_at"]
    create(talent["id"], start_on="2024-01-01", end_on=None)
    after = client.get(f"/api/talents/{talent['id']}").json()["updated_at"]
    assert after == before

    assert client.delete(f"/api/talents/{talent['id']}/{resource}/{current['id']}").status_code == 204
    remaining = client.get(f"/api/talents/{talent['id']}/{resource}").json()
    assert current["id"] not in [item["id"] for item in remaining]

    # 删除人才级联删除子表记录
    orphan = create(other["id"])
    assert client.delete(f"/api/talents/{other['id']}").status_code == 204
    assert client.get(f"/api/talents/{other['id']}/{resource}").status_code == 404
    orphan_put = client.put(f"/api/talents/{other['id']}/{resource}/{orphan['id']}", json={"start_on": "2024-01-01"})
    assert orphan_put.status_code == 404
