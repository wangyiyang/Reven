from uuid import uuid4

from reven.playbooks.models import Playbook


def test_playbooks_crud_and_filters(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = workbench

    created = client.post(
        "/api/playbooks",
        json={
            "title": "客户首次沟通 SOP",
            "kind": "sop",
            "status": "试行",
            "body": "1. 确认背景\n2. 确认预算\n3. 约演示",
            "tags": ["CRM", "销售"],
        },
    )
    assert created.status_code == 201
    playbook_id = created.json()["id"]
    assert created.json()["tags"] == ["CRM", "销售"]

    client.post(
        "/api/playbooks",
        json={
            "title": "公众号发布 Checklist",
            "kind": "checklist",
            "status": "正式",
            "body": "- 题图\n- 摘要",
            "tags": ["内容"],
        },
    )

    listed = client.get("/api/playbooks")
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    by_kind = client.get("/api/playbooks", params={"kind": "sop"})
    assert [item["title"] for item in by_kind.json()] == ["客户首次沟通 SOP"]

    by_query = client.get("/api/playbooks", params={"query": "发布"})
    assert [item["title"] for item in by_query.json()] == ["公众号发布 Checklist"]

    updated = client.put(f"/api/playbooks/{playbook_id}", json={"status": "正式", "tags": ["CRM", "销售", "已验证"]})
    assert updated.status_code == 200
    assert updated.json()["status"] == "正式"
    assert updated.json()["tags"] == ["CRM", "销售", "已验证"]

    deleted = client.delete(f"/api/playbooks/{playbook_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/playbooks/{playbook_id}").status_code == 404


def test_playbooks_model_round_trip(workbench) -> None:  # type: ignore[no-untyped-def]
    _client, session_factory = workbench

    async def round_trip() -> None:
        playbook = Playbook(title="报价话术", kind="script", status="草稿", body="你好", tags=["报价"])
        async with session_factory() as session:
            session.add(playbook)
            await session.commit()
            await session.refresh(playbook)
            assert playbook.id is not None
            assert playbook.tags == ["报价"]

    import asyncio

    asyncio.run(round_trip())


def test_playbooks_not_found(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = workbench
    missing = uuid4()
    assert client.get(f"/api/playbooks/{missing}").status_code == 404
    assert client.put(f"/api/playbooks/{missing}", json={"status": "正式"}).status_code == 404
    assert client.delete(f"/api/playbooks/{missing}").status_code == 404
