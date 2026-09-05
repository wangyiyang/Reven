from uuid import uuid4

from reven.sops.models import Sop


def test_sops_crud_and_filters(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = workbench

    created = client.post(
        "/api/sops",
        json={
            "title": "客户首次沟通 SOP",
            "kind": "procedure",
            "status": "试行",
            "body": "1. 确认背景\n2. 确认预算\n3. 约演示",
            "tags": ["CRM", "销售"],
        },
    )
    assert created.status_code == 201
    sop_id = created.json()["id"]
    assert created.json()["tags"] == ["CRM", "销售"]

    client.post(
        "/api/sops",
        json={
            "title": "公众号发布 Checklist",
            "kind": "checklist",
            "status": "正式",
            "body": "- 题图\n- 摘要",
            "tags": ["内容"],
        },
    )

    listed = client.get("/api/sops")
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    by_kind = client.get("/api/sops", params={"kind": "procedure"})
    assert [item["title"] for item in by_kind.json()] == ["客户首次沟通 SOP"]

    by_query = client.get("/api/sops", params={"query": "发布"})
    assert [item["title"] for item in by_query.json()] == ["公众号发布 Checklist"]

    updated = client.put(f"/api/sops/{sop_id}", json={"status": "正式", "tags": ["CRM", "销售", "已验证"]})
    assert updated.status_code == 200
    assert updated.json()["status"] == "正式"
    assert updated.json()["tags"] == ["CRM", "销售", "已验证"]

    deleted = client.delete(f"/api/sops/{sop_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/sops/{sop_id}").status_code == 404


def test_sops_reject_empty_body(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = workbench

    created = client.post("/api/sops", json={"title": "空内容", "body": ""})
    assert created.status_code == 422

    valid = client.post("/api/sops", json={"title": "有内容", "body": "步骤"})
    assert valid.status_code == 201
    sop_id = valid.json()["id"]

    updated = client.put(f"/api/sops/{sop_id}", json={"body": "   "})
    assert updated.status_code == 422


def test_sops_model_round_trip(workbench) -> None:  # type: ignore[no-untyped-def]
    _client, session_factory = workbench

    async def round_trip() -> None:
        sop = Sop(title="报价话术", kind="script", status="草稿", body="你好", tags=["报价"])
        async with session_factory() as session:
            session.add(sop)
            await session.commit()
            await session.refresh(sop)
            assert sop.id is not None
            assert sop.tags == ["报价"]

    import asyncio

    asyncio.run(round_trip())


def test_sops_not_found(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = workbench
    missing = uuid4()
    assert client.get(f"/api/sops/{missing}").status_code == 404
    assert client.put(f"/api/sops/{missing}", json={"status": "正式"}).status_code == 404
    assert client.delete(f"/api/sops/{missing}").status_code == 404
