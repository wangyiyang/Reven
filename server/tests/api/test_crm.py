from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from reven.scheduling import SHANGHAI


def _today() -> date:
    # 服务端按上海时区计算“今天”（见 api/routes/crm.py），测试必须用同一时钟，
    # 否则在 UTC 16:00-24:00 窗口内（CI Runner 为 UTC）两侧日期差一天，due=today 匹配为空
    return datetime.now(SHANGHAI).date()


def _create_customer(client, **overrides):  # type: ignore[no-untyped-def]
    payload = {
        "name": "示例科技",
        "status": "潜在客户",
        "source": "朋友介绍",
        "notes": "关注内容运营",
        "next_action": "安排需求访谈",
        "next_follow_up_on": (_today() + timedelta(days=2)).isoformat(),
    }
    payload.update(overrides)
    response = client.post("/api/crm/customers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_contact(client, customer_id: str, **overrides):  # type: ignore[no-untyped-def]
    payload = {
        "name": "王经理",
        "role": "创始人",
        "phone": "13800000000",
        "email": "wang@example.com",
        "wechat": "wang-crm",
        "is_primary": True,
        "notes": "主要决策人",
    }
    payload.update(overrides)
    response = client.post(f"/api/crm/customers/{customer_id}/contacts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_follow_up(client, customer_id: str, **overrides):  # type: ignore[no-untyped-def]
    payload = {
        "kind": "会议",
        "occurred_on": _today().isoformat(),
        "summary": "确认了内容运营需求",
        "next_action": "发送方案",
        "next_follow_up_on": (_today() + timedelta(days=3)).isoformat(),
        "set_as_current": True,
    }
    payload.update(overrides)
    response = client.post(f"/api/crm/customers/{customer_id}/follow-ups", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_customer_crud_search_and_filters(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    overdue = _create_customer(
        client,
        name="逾期客户",
        status="跟进中",
        next_follow_up_on=(_today() - timedelta(days=1)).isoformat(),
    )
    _create_customer(client, name="无计划客户", status="合作客户", next_action=None, next_follow_up_on=None)
    _create_contact(client, overdue["id"], name="可搜索联系人", phone="13900000000")

    assert [item["name"] for item in client.get("/api/crm/customers").json()] == ["逾期客户", "无计划客户"]
    by_status = client.get("/api/crm/customers", params={"status": "合作客户"})
    assert [item["name"] for item in by_status.json()] == ["无计划客户"]
    by_due = client.get("/api/crm/customers", params={"due": "overdue"})
    assert [item["id"] for item in by_due.json()] == [overdue["id"]]
    by_contact = client.get("/api/crm/customers", params={"query": "可搜索"})
    assert [item["id"] for item in by_contact.json()] == [overdue["id"]]

    updated = client.put(
        f"/api/crm/customers/{overdue['id']}",
        json={"status": "合作客户", "source": "主动咨询"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "合作客户"
    assert client.get(f"/api/crm/customers/{overdue['id']}").json()["source"] == "主动咨询"

    assert client.delete(f"/api/crm/customers/{overdue['id']}").status_code == 204
    assert client.get(f"/api/crm/customers/{overdue['id']}").status_code == 404


def test_customer_validation_is_explicit(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    missing_action = client.post(
        "/api/crm/customers",
        json={"name": "无行动客户", "next_follow_up_on": _today().isoformat()},
    )
    assert missing_action.status_code == 422
    assert client.post("/api/crm/customers", json={"name": "未知字段", "secret": "no"}).status_code == 422
    assert client.get("/api/crm/customers", params={"status": "任意状态"}).status_code == 422


def test_customer_due_filters_cover_today_upcoming_and_none(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    today = _create_customer(client, name="今日客户", next_follow_up_on=_today().isoformat())
    upcoming = _create_customer(
        client,
        name="未来客户",
        next_follow_up_on=(_today() + timedelta(days=5)).isoformat(),
    )
    no_plan = _create_customer(client, name="无计划客户", next_action=None, next_follow_up_on=None)

    assert [item["id"] for item in client.get("/api/crm/customers", params={"due": "today"}).json()] == [today["id"]]
    assert [item["id"] for item in client.get("/api/crm/customers", params={"due": "upcoming"}).json()] == [
        upcoming["id"]
    ]
    assert [item["id"] for item in client.get("/api/crm/customers", params={"due": "none"}).json()] == [no_plan["id"]]


@pytest.mark.parametrize("customer_status", ["潜在客户", "跟进中", "合作客户", "暂停跟进", "已流失"])
def test_each_customer_status_can_be_saved_and_filtered(workbench, customer_status: str) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    customer = _create_customer(client, name=f"{customer_status}示例", status=customer_status)

    response = client.get("/api/crm/customers", params={"status": customer_status})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [customer["id"]]


def test_contacts_keep_one_primary_and_enforce_ownership(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    customer = _create_customer(client)
    other_customer = _create_customer(client, name="其他客户")
    first = _create_contact(client, customer["id"])
    _create_contact(client, customer["id"], name="李总", email="li@example.com")

    contacts = client.get(f"/api/crm/customers/{customer['id']}/contacts").json()
    assert [(item["name"], item["is_primary"]) for item in contacts] == [("李总", True), ("王经理", False)]
    cross_customer = client.put(
        f"/api/crm/customers/{other_customer['id']}/contacts/{first['id']}",
        json={"name": "不允许修改"},
    )
    assert cross_customer.status_code == 404
    assert (
        client.post(
            f"/api/crm/customers/{customer['id']}/contacts",
            json={"name": "坏邮箱", "email": "not-an-email"},
        ).status_code
        == 422
    )


def test_follow_ups_sync_current_action_and_preserve_contact_snapshot(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    customer = _create_customer(client, next_action="原行动")
    contact = _create_contact(client, customer["id"])
    old = _create_follow_up(
        client,
        customer["id"],
        contact_id=contact["id"],
        occurred_on=(_today() - timedelta(days=1)).isoformat(),
        next_action="仅历史行动",
        set_as_current=False,
    )
    assert client.get(f"/api/crm/customers/{customer['id']}").json()["next_action"] == "原行动"

    current = _create_follow_up(client, customer["id"], contact_id=contact["id"])
    timeline = client.get(f"/api/crm/customers/{customer['id']}/follow-ups").json()
    assert [item["id"] for item in timeline] == [current["id"], old["id"]]
    assert client.get(f"/api/crm/customers/{customer['id']}").json()["next_action"] == "发送方案"

    edited = client.put(
        f"/api/crm/customers/{customer['id']}/follow-ups/{old['id']}",
        json={"summary": "修正后的历史", "next_action": "不覆盖当前"},
    )
    assert edited.status_code == 200, edited.text
    assert client.get(f"/api/crm/customers/{customer['id']}").json()["next_action"] == "发送方案"

    assert client.delete(f"/api/crm/customers/{customer['id']}/contacts/{contact['id']}").status_code == 204
    timeline = client.get(f"/api/crm/customers/{customer['id']}/follow-ups").json()
    assert timeline[0]["contact_id"] is None
    assert timeline[0]["contact_name_snapshot"] == "王经理"
    assert client.delete(f"/api/crm/customers/{customer['id']}/follow-ups/{old['id']}").status_code == 204
    remaining = client.get(f"/api/crm/customers/{customer['id']}/follow-ups").json()
    assert [item["id"] for item in remaining] == [current["id"]]


def test_nested_resources_and_customer_delete_are_scoped(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    customer = _create_customer(client)
    other_customer = _create_customer(client, name="其他客户")
    follow_up = _create_follow_up(client, customer["id"])

    cross_customer = client.delete(f"/api/crm/customers/{other_customer['id']}/follow-ups/{follow_up['id']}")
    assert cross_customer.status_code == 404
    assert client.delete(f"/api/crm/customers/{customer['id']}").status_code == 204
    assert client.get(f"/api/crm/customers/{customer['id']}/contacts").status_code == 404
    assert client.get(f"/api/crm/customers/{customer['id']}/follow-ups").status_code == 404
    assert client.get(f"/api/crm/customers/{uuid4()}").status_code == 404
