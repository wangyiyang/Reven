from uuid import uuid4

from reven.projects.models import Project


def test_projects_crud_and_filters(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = workbench

    created = client.post(
        "/api/projects",
        json={
            "name": "OLL 交付",
            "goal": "9 月底完成验收",
            "status": "进行中",
            "department": "工程交付",
            "due_on": "2026-09-30",
            "github_repo": "wangyiyang/OLL",
            "notion_url": "https://www.notion.so/example",
            "notes": "主线项目",
        },
    )
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["name"] == "OLL 交付"
    assert project["status"] == "进行中"

    listed = client.get("/api/projects")
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["OLL 交付"]

    filtered = client.get("/api/projects", params={"status": "已暂停"})
    assert filtered.status_code == 200
    assert filtered.json() == []

    queried = client.get("/api/projects", params={"query": "OLL"})
    assert queried.status_code == 200
    assert [item["id"] for item in queried.json()] == [project["id"]]

    updated = client.put(f"/api/projects/{project['id']}", json={"status": "已暂停", "due_on": "2026-10-15"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "已暂停"
    assert updated.json()["due_on"] == "2026-10-15"

    deleted = client.delete(f"/api/projects/{project['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/projects").json() == []


def test_projects_model_round_trip(workbench) -> None:  # type: ignore[no-untyped-def]
    _client, session_factory = workbench

    async def round_trip() -> None:
        project = Project(name="Reven", goal="一人公司操作系统", status="进行中")
        async with session_factory() as session:
            session.add(project)
            await session.commit()
            await session.refresh(project)
            assert project.id is not None
            assert project.created_at is not None

    import asyncio

    asyncio.run(round_trip())


def test_projects_not_found(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = workbench
    missing = uuid4()
    assert client.get("/api/projects", params={"query": "不存在"}).json() == []
    assert client.put(f"/api/projects/{missing}", json={"status": "已暂停"}).status_code == 404
    assert client.delete(f"/api/projects/{missing}").status_code == 404
