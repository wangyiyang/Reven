from datetime import date
from uuid import uuid4

from reven.finance.models import FinanceEntry


def test_finance_entries_crud_and_summary(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench

    created = client.post(
        "/api/finance/entries",
        json={
            "kind": "income",
            "name": "OLL 项目预付款",
            "amount": 150000,
            "category": "服务",
            "occurred_on": "2026-02-06",
            "status": "已收",
            "source": "产品",
            "notes": "首付款",
        },
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert created.json()["amount_cents"] == 15000000

    client.post(
        "/api/finance/entries",
        json={
            "kind": "expense",
            "name": "DeepSeek 充值",
            "amount": 100,
            "category": "AI / 大模型",
            "occurred_on": "2026-07-21",
            "status": "已付",
        },
    )

    listed = client.get("/api/finance/entries", params={"kind": "income", "query": "OLL"})
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["OLL 项目预付款"]

    summary = client.get("/api/finance/summary")
    assert summary.status_code == 200
    assert summary.json()["income_cents"] == 15000000
    assert summary.json()["expense_cents"] == 10000
    assert summary.json()["net_cents"] == 14990000

    updated = client.put(
        f"/api/finance/entries/{entry_id}",
        json={
            "kind": "income",
            "name": "OLL 尾款",
            "amount": 350000,
            "category": "服务",
            "occurred_on": "2026-08-31",
            "status": "应收",
            "source": "服务",
            "notes": "金额与支付节点待核实",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "应收"

    summary_after = client.get("/api/finance/summary").json()
    assert summary_after["receivable_cents"] == 35000000

    deleted = client.delete(f"/api/finance/entries/{entry_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/finance/entries/{entry_id}").status_code == 404


def test_finance_summary_uses_strict_cash_statuses(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    entries = [
        ("income", "已收收入", 101.01, "已收"),
        ("expense", "已付花销", 202.02, "已付"),
        ("income", "待收款项", 303.03, "应收"),
        ("expense", "待付款项", 404.04, "应付"),
        ("income", "未确认收入", 505.05, "已记录"),
        ("expense", "未确认支出", 606.06, "已记录"),
    ]
    for kind, name, amount, status in entries:
        response = client.post(
            "/api/finance/entries",
            json={
                "kind": kind,
                "name": name,
                "amount": amount,
                "occurred_on": "2026-09-02",
                "status": status,
            },
        )
        assert response.status_code == 201

    response = client.get("/api/finance/summary")

    assert response.status_code == 200
    assert response.json() == {
        "income_cents": 10101,
        "expense_cents": 20202,
        "net_cents": -10101,
        "receivable_cents": 30303,
        "payable_cents": 40404,
    }


def test_finance_entries_filter_by_status_month_and_category(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    payloads = [
        {
            "kind": "income",
            "name": "八月服务费",
            "amount": 100,
            "category": "服务",
            "occurred_on": "2026-08-05",
            "status": "已收",
        },
        {
            "kind": "expense",
            "name": "八月云资源",
            "amount": 50,
            "category": "云服务",
            "occurred_on": "2026-08-10",
            "status": "已付",
        },
        {"kind": "income", "name": "八月应收款", "amount": 200, "occurred_on": "2026-08-20", "status": "应收"},
        {
            "kind": "income",
            "name": "九月服务费",
            "amount": 300,
            "category": "服务",
            "occurred_on": "2026-09-01",
            "status": "已收",
        },
    ]
    for payload in payloads:
        assert client.post("/api/finance/entries", json=payload).status_code == 201

    by_status = client.get("/api/finance/entries", params={"status": "已收,已付"})
    assert by_status.status_code == 200
    assert [item["name"] for item in by_status.json()] == ["九月服务费", "八月云资源", "八月服务费"]

    by_month = client.get("/api/finance/entries", params={"month": "2026-08"})
    assert [item["name"] for item in by_month.json()] == ["八月应收款", "八月云资源", "八月服务费"]

    by_category = client.get("/api/finance/entries", params={"category": "服务"})
    assert [item["name"] for item in by_category.json()] == ["九月服务费", "八月服务费"]

    combined = client.get(
        "/api/finance/entries",
        params={"status": "已收,已付", "month": "2026-08", "category": "服务"},
    )
    assert [item["name"] for item in combined.json()] == ["八月服务费"]

    assert client.get("/api/finance/entries", params={"month": "2026-13"}).status_code == 422


def test_finance_summary_month_scopes_cash_totals(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    payloads = [
        {"kind": "income", "name": "八月已收", "amount": 100, "occurred_on": "2026-08-15", "status": "已收"},
        {"kind": "income", "name": "九月已收", "amount": 200, "occurred_on": "2026-09-02", "status": "已收"},
        {"kind": "expense", "name": "九月已付", "amount": 50, "occurred_on": "2026-09-10", "status": "已付"},
        {"kind": "income", "name": "存量应收", "amount": 300, "occurred_on": "2026-08-01", "status": "应收"},
        {"kind": "expense", "name": "存量应付", "amount": 70, "occurred_on": "2026-09-01", "status": "应付"},
        {"kind": "income", "name": "九月已记录", "amount": 999, "occurred_on": "2026-09-05", "status": "已记录"},
    ]
    for payload in payloads:
        assert client.post("/api/finance/entries", json=payload).status_code == 201

    september = client.get("/api/finance/summary", params={"month": "2026-09"})
    assert september.status_code == 200
    assert september.json() == {
        "income_cents": 20000,
        "expense_cents": 5000,
        "net_cents": 15000,
        "receivable_cents": 30000,
        "payable_cents": 7000,
    }

    august = client.get("/api/finance/summary", params={"month": "2026-08"}).json()
    assert august == {
        "income_cents": 10000,
        "expense_cents": 0,
        "net_cents": 10000,
        "receivable_cents": 30000,
        "payable_cents": 7000,
    }

    all_time = client.get("/api/finance/summary").json()
    assert all_time == {
        "income_cents": 30000,
        "expense_cents": 5000,
        "net_cents": 25000,
        "receivable_cents": 30000,
        "payable_cents": 7000,
    }

    assert client.get("/api/finance/summary", params={"month": "2026-13"}).status_code == 422


def test_finance_entry_validation_rejects_bad_amount(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    response = client.post(
        "/api/finance/entries",
        json={
            "kind": "expense",
            "name": "bad",
            "amount": -1,
            "occurred_on": "2026-08-19",
        },
    )
    assert response.status_code == 422


def test_finance_entry_not_found(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    missing = uuid4()
    assert client.get(f"/api/finance/entries/{missing}").status_code == 404
    assert (
        client.put(
            f"/api/finance/entries/{missing}",
            json={"kind": "income", "name": "x", "amount": 1, "occurred_on": "2026-08-19"},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/finance/entries/{missing}").status_code == 404


def test_finance_confirm_settles_receivable_into_actual_month(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    created = client.post(
        "/api/finance/entries",
        json={
            "kind": "income",
            "name": "OLL 项目尾款",
            "amount": 350,
            "occurred_on": "2026-08-20",
            "due_on": "2026-08-31",
            "status": "应收",
            "source": "客户 A",
        },
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]

    confirmed = client.post(f"/api/finance/entries/{entry_id}/confirm", json={"occurred_on": "2026-09-03"})
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "已收"
    assert body["occurred_on"] == "2026-09-03"
    assert body["due_on"] == "2026-08-31"

    september = client.get("/api/finance/summary", params={"month": "2026-09"}).json()
    assert september["income_cents"] == 35000
    assert september["receivable_cents"] == 0
    august = client.get("/api/finance/summary", params={"month": "2026-08"}).json()
    assert august["income_cents"] == 0
    assert august["receivable_cents"] == 0

    repeated = client.post(f"/api/finance/entries/{entry_id}/confirm", json={"occurred_on": "2026-09-04"})
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "FINANCE_ENTRY_ALREADY_SETTLED"
    settled = client.get(f"/api/finance/entries/{entry_id}").json()
    assert settled["occurred_on"] == "2026-09-03"
    assert client.get("/api/finance/summary", params={"month": "2026-09"}).json()["income_cents"] == 35000


def test_finance_confirm_settles_payable(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    created = client.post(
        "/api/finance/entries",
        json={
            "kind": "expense",
            "name": "办公室租金",
            "amount": 80,
            "occurred_on": "2026-08-25",
            "due_on": "2026-09-01",
            "status": "应付",
        },
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]

    confirmed = client.post(f"/api/finance/entries/{entry_id}/confirm", json={"occurred_on": "2026-09-02"})
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "已付"

    september = client.get("/api/finance/summary", params={"month": "2026-09"}).json()
    assert september["expense_cents"] == 8000
    assert september["payable_cents"] == 0
    assert client.get("/api/finance/summary", params={"month": "2026-08"}).json()["expense_cents"] == 0


def test_finance_confirm_rejects_non_pending_statuses(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    cases = [("income", "已收"), ("expense", "已付"), ("income", "已记录")]
    for kind, status_value in cases:
        created = client.post(
            "/api/finance/entries",
            json={
                "kind": kind,
                "name": f"{status_value}记录",
                "amount": 10,
                "occurred_on": "2026-08-19",
                "status": status_value,
            },
        )
        assert created.status_code == 201
        entry_id = created.json()["id"]

        response = client.post(f"/api/finance/entries/{entry_id}/confirm", json={"occurred_on": "2026-09-03"})
        assert response.status_code == 409
        assert response.json()["code"] == "FINANCE_ENTRY_ALREADY_SETTLED"

        entry = client.get(f"/api/finance/entries/{entry_id}").json()
        assert entry["status"] == status_value
        assert entry["occurred_on"] == "2026-08-19"


def test_finance_confirm_not_found_and_invalid_body(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    missing = uuid4()
    not_found = client.post(f"/api/finance/entries/{missing}/confirm", json={"occurred_on": "2026-09-03"})
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "FINANCE_ENTRY_NOT_FOUND"

    created = client.post(
        "/api/finance/entries",
        json={"kind": "income", "name": "待确认款项", "amount": 10, "occurred_on": "2026-08-19", "status": "应收"},
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert client.post(f"/api/finance/entries/{entry_id}/confirm", json={}).status_code == 422


def test_finance_entry_model_round_trip() -> None:
    entry = FinanceEntry(
        id=uuid4(),
        kind="expense",
        name="Kimi 套餐升级",
        amount_cents=670067,
        category="AI / 大模型",
        occurred_on=date(2026, 7, 23),
        status="已付",
    )
    assert entry.amount_cents == 670067
    assert entry.kind == "expense"
