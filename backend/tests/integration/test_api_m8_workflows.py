import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.orchestrator import get_coordinator
from app.core.auth import UserRole, get_current_user
from app.core.exceptions import NotFoundError, ValidationError
from app.main import app
from app.services.workflow_service import WorkflowService


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_coordinator] = lambda: object()
    return TestClient(app)


@pytest.fixture
def as_admin() -> SimpleNamespace:
    user = _user(UserRole.ADMIN)
    _override_user(user)
    return user


def _user(role: UserRole) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role.value)


def _override_user(user: SimpleNamespace) -> None:
    async def fake_current_user() -> SimpleNamespace:
        return user

    app.dependency_overrides[get_current_user] = fake_current_user


def _topology() -> dict:
    agent_id = str(uuid.uuid4())
    return {
        "nodes": [
            {"id": "start", "type": "agent", "data": {"agent_id": agent_id}},
        ],
        "edges": [],
    }


def _workflow(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid.uuid4(),
        "name": "support-workflow",
        "description": "Routes customer support tasks",
        "topology": _topology(),
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _workflow_payload() -> dict:
    return {
        "name": "support-workflow",
        "description": "Routes customer support tasks",
        "topology": _topology(),
    }


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("get", "/api/v1/workflows", None),
        ("get", f"/api/v1/workflows/{uuid.uuid4()}", None),
        ("post", "/api/v1/workflows", _workflow_payload()),
        ("patch", f"/api/v1/workflows/{uuid.uuid4()}", {"name": "denied"}),
        ("delete", f"/api/v1/workflows/{uuid.uuid4()}", None),
        (
            "post",
            f"/api/v1/workflows/{uuid.uuid4()}/execute",
            {"task_input": {"ticket_id": "T-100"}},
        ),
    ],
)
def test_workflow_routes_require_authentication(
    client: TestClient, method: str, path: str, json: dict | None
) -> None:
    response = client.request(method.upper(), path, json=json)

    assert response.status_code == 401


def test_developer_creates_workflow_with_detail_view(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    developer = _user(UserRole.DEVELOPER)
    _override_user(developer)
    workflow = _workflow()
    captured = {}

    async def fake_create_workflow(
        self, schema, *, created_by: uuid.UUID
    ) -> SimpleNamespace:
        captured["schema"] = schema
        captured["created_by"] = created_by
        return workflow

    monkeypatch.setattr(WorkflowService, "create_workflow", fake_create_workflow)

    response = client.post("/api/v1/workflows", json=_workflow_payload())

    assert response.status_code == 201
    assert captured["created_by"] == developer.id
    assert captured["schema"].name == "support-workflow"
    body = response.json()
    assert body["id"] == str(workflow.id)
    assert body["description"] == "Routes customer support tasks"
    assert body["topology"] == workflow.topology


def test_admin_creates_workflow_with_detail_view(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, as_admin: SimpleNamespace
) -> None:
    workflow = _workflow()
    captured = {}

    async def fake_create_workflow(
        self, schema, *, created_by: uuid.UUID
    ) -> SimpleNamespace:
        captured["schema"] = schema
        captured["created_by"] = created_by
        return workflow

    monkeypatch.setattr(WorkflowService, "create_workflow", fake_create_workflow)

    response = client.post("/api/v1/workflows", json=_workflow_payload())

    assert response.status_code == 201
    assert captured["created_by"] == as_admin.id
    assert captured["schema"].name == "support-workflow"
    assert response.json()["topology"] == workflow.topology


def test_create_workflow_validation_error_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.DEVELOPER))

    async def fake_create_workflow(
        self, schema, *, created_by: uuid.UUID
    ) -> SimpleNamespace:
        raise ValidationError("拓扑非法")

    monkeypatch.setattr(WorkflowService, "create_workflow", fake_create_workflow)

    response = client.post("/api/v1/workflows", json=_workflow_payload())

    assert response.status_code == 422
    assert response.json()["detail"] == "拓扑非法"


def test_viewer_cannot_create_workflow(client: TestClient) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.post("/api/v1/workflows", json=_workflow_payload())

    assert response.status_code == 403


def test_viewer_lists_workflows_without_topology(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    workflow = _workflow()

    async def fake_list_workflows(
        self, limit: int = 20, offset: int = 0
    ) -> list[SimpleNamespace]:
        assert limit == 10
        assert offset == 5
        return [workflow]

    monkeypatch.setattr(WorkflowService, "list_workflows", fake_list_workflows)

    response = client.get("/api/v1/workflows?limit=10&offset=5")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(workflow.id)
    assert body[0]["description"] == "Routes customer support tasks"
    assert "topology" not in body[0]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_list_workflows_rejects_invalid_pagination(
    client: TestClient, query: str
) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.get(f"/api/v1/workflows?{query}")

    assert response.status_code == 422


def test_viewer_gets_workflow_detail_with_topology(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    workflow = _workflow()

    async def fake_get_workflow_detail(
        self, workflow_id: uuid.UUID
    ) -> SimpleNamespace:
        assert workflow_id == workflow.id
        return workflow

    monkeypatch.setattr(
        WorkflowService, "get_workflow_detail", fake_get_workflow_detail
    )

    response = client.get(f"/api/v1/workflows/{workflow.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(workflow.id)
    assert body["topology"] == workflow.topology


def test_workflow_detail_not_found_error_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    workflow_id = uuid.uuid4()

    async def fake_get_workflow_detail(
        self, workflow_id: uuid.UUID
    ) -> SimpleNamespace:
        raise NotFoundError(f"工作流不存在或已被删除: {workflow_id}")

    monkeypatch.setattr(
        WorkflowService, "get_workflow_detail", fake_get_workflow_detail
    )

    response = client.get(f"/api/v1/workflows/{workflow_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"工作流不存在或已被删除: {workflow_id}"


def test_developer_updates_workflow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.DEVELOPER))
    workflow = _workflow(name="updated-workflow")
    captured = {}

    async def fake_update_workflow(
        self, workflow_id: uuid.UUID, schema
    ) -> SimpleNamespace:
        captured["workflow_id"] = workflow_id
        captured["schema"] = schema
        return workflow

    monkeypatch.setattr(WorkflowService, "update_workflow", fake_update_workflow)

    response = client.patch(
        f"/api/v1/workflows/{workflow.id}", json={"name": "updated-workflow"}
    )

    assert response.status_code == 200
    assert captured["workflow_id"] == workflow.id
    assert captured["schema"].name == "updated-workflow"
    assert response.json()["name"] == "updated-workflow"


def test_admin_updates_workflow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, as_admin: SimpleNamespace
) -> None:
    workflow = _workflow(name="admin-updated-workflow")
    captured = {}

    async def fake_update_workflow(
        self, workflow_id: uuid.UUID, schema
    ) -> SimpleNamespace:
        captured["workflow_id"] = workflow_id
        captured["schema"] = schema
        return workflow

    monkeypatch.setattr(WorkflowService, "update_workflow", fake_update_workflow)

    response = client.patch(
        f"/api/v1/workflows/{workflow.id}",
        json={"name": "admin-updated-workflow"},
    )

    assert response.status_code == 200
    assert as_admin.role == UserRole.ADMIN.value
    assert captured["workflow_id"] == workflow.id
    assert captured["schema"].name == "admin-updated-workflow"
    assert response.json()["name"] == "admin-updated-workflow"


def test_viewer_cannot_update_workflow(client: TestClient) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.patch(f"/api/v1/workflows/{uuid.uuid4()}", json={"name": "denied"})

    assert response.status_code == 403


def test_developer_deletes_workflow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.DEVELOPER))
    workflow_id = uuid.uuid4()
    captured = {}

    async def fake_delete_workflow(self, workflow_id: uuid.UUID) -> None:
        captured["workflow_id"] = workflow_id

    monkeypatch.setattr(WorkflowService, "delete_workflow", fake_delete_workflow)

    response = client.delete(f"/api/v1/workflows/{workflow_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert captured["workflow_id"] == workflow_id


def test_admin_deletes_workflow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, as_admin: SimpleNamespace
) -> None:
    workflow_id = uuid.uuid4()
    captured = {}

    async def fake_delete_workflow(self, workflow_id: uuid.UUID) -> None:
        captured["workflow_id"] = workflow_id

    monkeypatch.setattr(WorkflowService, "delete_workflow", fake_delete_workflow)

    response = client.delete(f"/api/v1/workflows/{workflow_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert as_admin.role == UserRole.ADMIN.value
    assert captured["workflow_id"] == workflow_id


def test_viewer_cannot_delete_workflow(client: TestClient) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.delete(f"/api/v1/workflows/{uuid.uuid4()}")

    assert response.status_code == 403


def test_developer_triggers_workflow_execution(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.DEVELOPER))
    workflow_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    captured = {}

    async def fake_trigger_execution(
        self, *, workflow_id: uuid.UUID, task_input: dict
    ) -> uuid.UUID:
        captured["workflow_id"] = workflow_id
        captured["task_input"] = task_input
        return execution_id

    monkeypatch.setattr(WorkflowService, "trigger_execution", fake_trigger_execution)

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/execute",
        json={"task_input": {"ticket_id": "T-100"}},
    )

    assert response.status_code == 202
    assert captured == {
        "workflow_id": workflow_id,
        "task_input": {"ticket_id": "T-100"},
    }
    assert response.json() == {"execution_id": str(execution_id)}


def test_admin_triggers_workflow_execution(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, as_admin: SimpleNamespace
) -> None:
    workflow_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    captured = {}

    async def fake_trigger_execution(
        self, *, workflow_id: uuid.UUID, task_input: dict
    ) -> uuid.UUID:
        captured["workflow_id"] = workflow_id
        captured["task_input"] = task_input
        return execution_id

    monkeypatch.setattr(WorkflowService, "trigger_execution", fake_trigger_execution)

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/execute",
        json={"task_input": {"ticket_id": "T-200"}},
    )

    assert response.status_code == 202
    assert as_admin.role == UserRole.ADMIN.value
    assert captured == {
        "workflow_id": workflow_id,
        "task_input": {"ticket_id": "T-200"},
    }
    assert response.json() == {"execution_id": str(execution_id)}


def test_viewer_cannot_trigger_workflow(client: TestClient) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.post(
        f"/api/v1/workflows/{uuid.uuid4()}/execute",
        json={"task_input": {"ticket_id": "T-100"}},
    )

    assert response.status_code == 403


def test_trigger_workflow_not_found_error_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.DEVELOPER))
    workflow_id = uuid.uuid4()

    async def fake_trigger_execution(
        self, *, workflow_id: uuid.UUID, task_input: dict
    ) -> uuid.UUID:
        raise NotFoundError(f"工作流不存在或已被删除: {workflow_id}")

    monkeypatch.setattr(WorkflowService, "trigger_execution", fake_trigger_execution)

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/execute",
        json={"task_input": {"ticket_id": "T-100"}},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == f"工作流不存在或已被删除: {workflow_id}"
