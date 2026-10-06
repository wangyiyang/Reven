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
        "kind": "面谈",
        "occurred_on": _today().isoformat(),
        "summary": "确认了内容运营需求",
        "next_action": "发送方案",
        "next_due_on": (_today() + timedelta(days=3)).isoformat(),
    }
    payload.update(overrides)
    response = client.post(f"/api/crm/customers/{customer_id}/follow-ups", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_customer_crud_search_and_filters(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    overdue = _create_customer(client, name="逾期客户", status="跟进中")
    _create_follow_up(
        client,
        overdue["id"],
        next_action="电话回访",
        next_due_on=(_today() - timedelta(days=1)).isoformat(),
    )
    no_plan = _create_customer(client, name="无计划客户", status="合作客户")
    _create_contact(client, overdue["id"], name="可搜索联系人", phone="13900000000")

    customers = client.get("/api/crm/customers").json()
    assert [item["name"] for item in customers] == ["逾期客户", "无计划客户"]
    # 响应只携带派生计划字段（next_due_on），不再有 next_follow_up_on
    overdue_item = customers[0]
    assert overdue_item["next_action"] == "电话回访"
    assert overdue_item["next_due_on"] == (_today() - timedelta(days=1)).isoformat()
    assert "next_follow_up_on" not in overdue_item
    no_plan_item = customers[1]
    assert no_plan_item["next_action"] is None and no_plan_item["next_due_on"] is None

    by_status = client.get("/api/crm/customers", params={"status": "合作客户"})
    assert [item["id"] for item in by_status.json()] == [no_plan["id"]]
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
    assert updated.json()["next_due_on"] == (_today() - timedelta(days=1)).isoformat()
    assert client.get(f"/api/crm/customers/{overdue['id']}").json()["source"] == "主动咨询"

    assert client.delete(f"/api/crm/customers/{overdue['id']}").status_code == 204
    assert client.get(f"/api/crm/customers/{overdue['id']}").status_code == 404


def test_customer_validation_is_explicit(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    # 计划字段已从客户入参删除：extra=forbid 下旧字段一律 422
    for field in ("next_action", "next_follow_up_on", "next_due_on", "set_as_current"):
        response = client.post("/api/crm/customers", json={"name": "旧字段客户", field: None})
        assert response.status_code == 422, field
    assert client.post("/api/crm/customers", json={"name": "未知字段", "secret": "no"}).status_code == 422
    assert client.get("/api/crm/customers", params={"status": "任意状态"}).status_code == 422

    # 配对校验保留在跟进记录上：有日期无行动被拒
    customer = _create_customer(client, name="跟进校验客户")
    missing_action = client.post(
        f"/api/crm/customers/{customer['id']}/follow-ups",
        json={
            "kind": "电话",
            "occurred_on": _today().isoformat(),
            "summary": "沟通",
            "next_due_on": _today().isoformat(),
        },
    )
    assert missing_action.status_code == 422


def test_customer_due_filters_cover_today_upcoming_and_none(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    today = _create_customer(client, name="今日客户")
    _create_follow_up(client, today["id"], next_due_on=_today().isoformat())
    upcoming = _create_customer(client, name="未来客户")
    _create_follow_up(client, upcoming["id"], next_due_on=(_today() + timedelta(days=5)).isoformat())
    no_plan = _create_customer(client, name="无计划客户")

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


def test_follow_up_plan_is_derived_immediately_on_list_and_detail(workbench) -> None:  # type: ignore[no-untyped-def]
    """记一条带计划的跟进后，客户列表/详情立即呈现派生计划；新建客户不再接受计划字段。"""
    client, _factory = workbench
    customer = _create_customer(client)

    detail = client.get(f"/api/crm/customers/{customer['id']}").json()
    assert detail["next_action"] is None and detail["next_due_on"] is None

    due_on = (_today() + timedelta(days=3)).isoformat()
    _create_follow_up(client, customer["id"], next_action="发送方案", next_due_on=due_on)

    detail = client.get(f"/api/crm/customers/{customer['id']}").json()
    assert detail["next_action"] == "发送方案" and detail["next_due_on"] == due_on
    listed = client.get("/api/crm/customers").json()
    assert [(item["next_action"], item["next_due_on"]) for item in listed] == [("发送方案", due_on)]


def test_derived_plan_tracks_latest_follow_up_and_falls_back_on_delete(workbench) -> None:  # type: ignore[no-untyped-def]
    """派生计划取自最新跟进；更新旧记录不影响，删除最新一条后回退到次新计划，再删则归零。"""
    client, _factory = workbench
    customer = _create_customer(client)
    contact = _create_contact(client, customer["id"])
    old = _create_follow_up(
        client,
        customer["id"],
        contact_id=contact["id"],
        occurred_on=(_today() - timedelta(days=1)).isoformat(),
        next_action="旧约定",
        next_due_on=(_today() + timedelta(days=10)).isoformat(),
    )
    current = _create_follow_up(client, customer["id"], contact_id=contact["id"])

    def derived_plan() -> dict:  # type: ignore[no-untyped-def]
        return client.get(f"/api/crm/customers/{customer['id']}").json()

    timeline = client.get(f"/api/crm/customers/{customer['id']}/follow-ups").json()
    assert [item["id"] for item in timeline] == [current["id"], old["id"]]
    plan = derived_plan()
    assert plan["next_action"] == "发送方案"
    assert plan["next_due_on"] == (_today() + timedelta(days=3)).isoformat()

    # 更新次新跟进不影响派生计划（仍取最新一条）
    edited = client.put(
        f"/api/crm/customers/{customer['id']}/follow-ups/{old['id']}",
        json={"summary": "修正后的历史", "next_action": "次新修正"},
    )
    assert edited.status_code == 200, edited.text
    assert derived_plan()["next_action"] == "发送方案"

    # 更新最新跟进的计划即更新派生计划
    edited_current = client.put(
        f"/api/crm/customers/{customer['id']}/follow-ups/{current['id']}",
        json={"next_action": "改约演示", "next_due_on": (_today() + timedelta(days=7)).isoformat()},
    )
    assert edited_current.status_code == 200, edited_current.text
    plan = derived_plan()
    assert plan["next_action"] == "改约演示"
    assert plan["next_due_on"] == (_today() + timedelta(days=7)).isoformat()

    # 删除最新一条后回退到次新跟进的计划
    assert client.delete(f"/api/crm/customers/{customer['id']}/follow-ups/{current['id']}").status_code == 204
    plan = derived_plan()
    assert plan["next_action"] == "次新修正"
    assert plan["next_due_on"] == (_today() + timedelta(days=10)).isoformat()

    # 联系人删除后历史保留姓名快照
    assert client.delete(f"/api/crm/customers/{customer['id']}/contacts/{contact['id']}").status_code == 204
    timeline = client.get(f"/api/crm/customers/{customer['id']}/follow-ups").json()
    assert timeline[0]["contact_id"] is None
    assert timeline[0]["contact_name_snapshot"] == "王经理"

    # 再删次新（此时已成最新）后计划归零
    assert client.delete(f"/api/crm/customers/{customer['id']}/follow-ups/{old['id']}").status_code == 204
    plan = derived_plan()
    assert plan["next_action"] is None and plan["next_due_on"] is None


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


@pytest.mark.parametrize(
    ("method", "suffix", "payload", "code", "message"),
    [
        ("PUT", "", {"name": "改名"}, "CRM_CUSTOMER_NOT_FOUND", "客户不存在"),
        ("DELETE", "", None, "CRM_CUSTOMER_NOT_FOUND", "客户不存在"),
        ("POST", "/contacts", {"name": "联系人"}, "CRM_CUSTOMER_NOT_FOUND", "客户不存在"),
        ("PUT", "/contacts/{id}", {"name": "改名"}, "CRM_CONTACT_NOT_FOUND", "联系人不存在"),
        ("DELETE", "/contacts/{id}", None, "CRM_CONTACT_NOT_FOUND", "联系人不存在"),
        (
            "POST",
            "/follow-ups",
            {"kind": "电话", "occurred_on": "2026-10-01", "summary": "沟通"},
            "CRM_CUSTOMER_NOT_FOUND",
            "客户不存在",
        ),
        ("PUT", "/follow-ups/{id}", {"summary": "补充"}, "CRM_FOLLOW_UP_NOT_FOUND", "跟进记录不存在"),
        ("DELETE", "/follow-ups/{id}", None, "CRM_FOLLOW_UP_NOT_FOUND", "跟进记录不存在"),
    ],
)
def test_mutation_not_found_errors_keep_http_contract(workbench, method, suffix, payload, code, message) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    path = f"/api/crm/customers/{uuid4()}{suffix.format(id=uuid4())}"

    response = client.request(method, path, json=payload)

    assert response.status_code == 404
    assert response.json() == {"code": code, "message": message}


def test_invalid_merged_action_on_follow_up_returns_domain_error_shape(workbench) -> None:  # type: ignore[no-untyped-def]
    """跟进已有到期日时清空行动：合并校验抛 InvalidActionPairError，REST 映射 422 域错误。"""
    client, _factory = workbench
    customer = _create_customer(client)
    history = _create_follow_up(client, customer["id"])

    response = client.put(
        f"/api/crm/customers/{customer['id']}/follow-ups/{history['id']}",
        json={"next_action": None},
    )

    assert response.status_code == 422
    assert response.json() == {"code": "CRM_NEXT_ACTION_REQUIRED", "message": "设置跟进日期时必须提供下一步行动"}


def test_customer_update_rejects_plan_fields(workbench) -> None:  # type: ignore[no-untyped-def]
    """客户更新入参同样不再接受计划字段（extra=forbid）。"""
    client, _factory = workbench
    customer = _create_customer(client)

    for field in ("next_action", "next_follow_up_on", "next_due_on"):
        response = client.put(f"/api/crm/customers/{customer['id']}", json={field: None})
        assert response.status_code == 422, field
