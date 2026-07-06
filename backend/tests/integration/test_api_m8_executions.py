import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.auth import UserRole, get_current_user
from app.core.exceptions import NotFoundError
from app.main import app
from app.services.execution_service import ExecutionService


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _user(role: UserRole) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role.value)


def _override_user(user: SimpleNamespace) -> None:
    async def fake_current_user() -> SimpleNamespace:
        return user

    app.dependency_overrides[get_current_user] = fake_current_user


def _execution(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "status": "completed",
        "input": {"ticket_id": "T-100"},
        "output": {"answer": "resolved"},
        "error": None,
        "created_at": datetime.now(UTC),
        "started_at": datetime.now(UTC),
        "finished_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _timeline_event(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid.uuid4(),
        "execution_id": uuid.uuid4(),
        "protocol_stage": "routing",
        "event_type": "agent_selected",
        "payload": {"agent": "support-agent"},
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/executions",
        f"/api/v1/executions/{uuid.uuid4()}",
        f"/api/v1/executions/{uuid.uuid4()}/timeline",
    ],
)
def test_execution_routes_require_authentication(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 401


def test_viewer_lists_executions_without_payload_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    execution = _execution()

    async def fake_list_executions(
        self,
        workflow_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SimpleNamespace]:
        assert workflow_id is None
        assert status is None
        assert limit == 20
        assert offset == 0
        return [execution]

    monkeypatch.setattr(ExecutionService, "list_executions", fake_list_executions)

    response = client.get("/api/v1/executions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(execution.id)
    assert body[0]["status"] == "completed"
    assert "input" not in body[0]
    assert "output" not in body[0]
    assert "error" not in body[0]


def test_list_executions_passes_filters_to_service(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    workflow_id = uuid.uuid4()
    captured = {}

    async def fake_list_executions(
        self,
        workflow_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[SimpleNamespace]:
        captured["workflow_id"] = workflow_id
        captured["status"] = status
        captured["limit"] = limit
        captured["offset"] = offset
        return []

    monkeypatch.setattr(ExecutionService, "list_executions", fake_list_executions)

    response = client.get(
        f"/api/v1/executions?workflow_id={workflow_id}&status=running&limit=10&offset=5"
    )

    assert response.status_code == 200
    assert captured == {
        "workflow_id": workflow_id,
        "status": "running",
        "limit": 10,
        "offset": 5,
    }


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_list_executions_rejects_invalid_pagination(
    client: TestClient, query: str
) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.get(f"/api/v1/executions?{query}")

    assert response.status_code == 422


def test_viewer_gets_execution_detail_with_output(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    execution = _execution()

    async def fake_get_execution_detail(
        self, execution_id: uuid.UUID
    ) -> SimpleNamespace:
        assert execution_id == execution.id
        return execution

    monkeypatch.setattr(
        ExecutionService, "get_execution_detail", fake_get_execution_detail
    )

    response = client.get(f"/api/v1/executions/{execution.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(execution.id)
    assert body["input"] == {"ticket_id": "T-100"}
    assert body["output"] == {"answer": "resolved"}
    assert body["error"] is None


def test_execution_detail_not_found_error_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    execution_id = uuid.uuid4()

    async def fake_get_execution_detail(
        self, execution_id: uuid.UUID
    ) -> SimpleNamespace:
        raise NotFoundError(f"执行实例不存在: {execution_id}")

    monkeypatch.setattr(
        ExecutionService, "get_execution_detail", fake_get_execution_detail
    )

    response = client.get(f"/api/v1/executions/{execution_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"执行实例不存在: {execution_id}"


def test_viewer_gets_execution_timeline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    execution_id = uuid.uuid4()
    event = _timeline_event(execution_id=execution_id)

    async def fake_get_execution_timeline(
        self, execution_id: uuid.UUID
    ) -> list[SimpleNamespace]:
        assert execution_id == event.execution_id
        return [event]

    monkeypatch.setattr(
        ExecutionService, "get_execution_timeline", fake_get_execution_timeline
    )

    response = client.get(f"/api/v1/executions/{execution_id}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(event.id)
    assert body[0]["execution_id"] == str(execution_id)
    assert body[0]["payload"] == {"agent": "support-agent"}


def test_execution_timeline_not_found_error_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    execution_id = uuid.uuid4()

    async def fake_get_execution_timeline(
        self, execution_id: uuid.UUID
    ) -> list[SimpleNamespace]:
        raise NotFoundError(f"执行实例不存在: {execution_id}")

    monkeypatch.setattr(
        ExecutionService, "get_execution_timeline", fake_get_execution_timeline
    )

    response = client.get(f"/api/v1/executions/{execution_id}/timeline")

    assert response.status_code == 404
    assert response.json()["detail"] == f"执行实例不存在: {execution_id}"
