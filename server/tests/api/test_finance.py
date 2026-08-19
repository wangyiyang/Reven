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
