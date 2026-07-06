import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.auth import UserRole, get_current_user
from app.core.exceptions import NotFoundError
from app.main import app
from app.services.agent_service import AgentService


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
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


def _agent(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid.uuid4(),
        "name": "support-agent",
        "description": "Handles customer support",
        "agent_type": "assistant",
        "llm_provider": "openai",
        "llm_model": "gpt-4o",
        "system_prompt": "Be helpful",
        "config": {"temperature": 0.2},
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _agent_payload() -> dict:
    return {
        "name": "support-agent",
        "description": "Handles customer support",
        "agent_type": "assistant",
        "llm_provider": "openai",
        "llm_model": "gpt-4o",
        "system_prompt": "Be helpful",
        "config": {"temperature": 0.2},
    }


def test_create_agent_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/v1/agents", json=_agent_payload())

    assert response.status_code == 401


def test_viewer_cannot_create_agent(client: TestClient) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.post("/api/v1/agents", json=_agent_payload())

    assert response.status_code == 403


def test_developer_creates_agent_with_detail_view(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    developer = _user(UserRole.DEVELOPER)
    _override_user(developer)
    created_agent = _agent()
    captured = {}

    async def fake_create_agent(self, schema, created_by: uuid.UUID) -> SimpleNamespace:
        captured["schema"] = schema
        captured["created_by"] = created_by
        return created_agent

    monkeypatch.setattr(AgentService, "create_agent", fake_create_agent)

    response = client.post("/api/v1/agents", json=_agent_payload())

    assert response.status_code == 201
    assert captured["created_by"] == developer.id
    assert captured["schema"].description == "Handles customer support"
    body = response.json()
    assert body["id"] == str(created_agent.id)
    assert body["description"] == "Handles customer support"
    assert body["system_prompt"] == "Be helpful"
    assert body["config"] == {"temperature": 0.2}


def test_admin_creates_agent_with_detail_view(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, as_admin: SimpleNamespace
) -> None:
    created_agent = _agent()
    captured = {}

    async def fake_create_agent(self, schema, created_by: uuid.UUID) -> SimpleNamespace:
        captured["schema"] = schema
        captured["created_by"] = created_by
        return created_agent

    monkeypatch.setattr(AgentService, "create_agent", fake_create_agent)

    response = client.post("/api/v1/agents", json=_agent_payload())

    assert response.status_code == 201
    assert captured["created_by"] == as_admin.id
    assert captured["schema"].name == "support-agent"
    assert response.json()["config"] == {"temperature": 0.2}


def test_list_agents_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/agents")

    assert response.status_code == 401


def test_viewer_lists_agents_without_detail_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))

    async def fake_list_agents(
        self, limit: int = 20, offset: int = 0
    ) -> list[SimpleNamespace]:
        assert limit == 10
        assert offset == 5
        return [_agent()]

    monkeypatch.setattr(AgentService, "list_agents", fake_list_agents)

    response = client.get("/api/v1/agents?limit=10&offset=5")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["description"] == "Handles customer support"
    assert "system_prompt" not in body[0]
    assert "config" not in body[0]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_list_agents_rejects_invalid_pagination(
    client: TestClient, query: str
) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.get(f"/api/v1/agents?{query}")

    assert response.status_code == 422


def test_get_agent_detail_requires_authentication(client: TestClient) -> None:
    response = client.get(f"/api/v1/agents/{uuid.uuid4()}")

    assert response.status_code == 401


def test_viewer_gets_agent_detail_with_config(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    agent = _agent()

    async def fake_get_agent_detail(self, agent_id: uuid.UUID) -> SimpleNamespace:
        assert agent_id == agent.id
        return agent

    monkeypatch.setattr(AgentService, "get_agent_detail", fake_get_agent_detail)

    response = client.get(f"/api/v1/agents/{agent.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(agent.id)
    assert body["config"] == {"temperature": 0.2}


def test_agent_service_not_found_error_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.VIEWER))
    agent_id = uuid.uuid4()

    async def fake_get_agent_detail(self, agent_id: uuid.UUID) -> SimpleNamespace:
        raise NotFoundError(f"Agent 不存在: {agent_id}")

    monkeypatch.setattr(AgentService, "get_agent_detail", fake_get_agent_detail)

    response = client.get(f"/api/v1/agents/{agent_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"Agent 不存在: {agent_id}"


def test_developer_updates_agent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.DEVELOPER))
    agent = _agent(name="updated-agent")
    captured = {}

    async def fake_update_agent(
        self, agent_id: uuid.UUID, schema
    ) -> SimpleNamespace:
        captured["agent_id"] = agent_id
        captured["schema"] = schema
        return agent

    monkeypatch.setattr(AgentService, "update_agent", fake_update_agent)

    response = client.patch(f"/api/v1/agents/{agent.id}", json={"name": "updated-agent"})

    assert response.status_code == 200
    assert captured["agent_id"] == agent.id
    assert captured["schema"].name == "updated-agent"
    assert response.json()["name"] == "updated-agent"


def test_viewer_cannot_update_agent(client: TestClient) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.patch(f"/api/v1/agents/{uuid.uuid4()}", json={"name": "denied"})

    assert response.status_code == 403


def test_developer_deletes_agent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _override_user(_user(UserRole.DEVELOPER))
    agent_id = uuid.uuid4()
    captured = {}

    async def fake_delete_agent(self, agent_id: uuid.UUID) -> None:
        captured["agent_id"] = agent_id

    monkeypatch.setattr(AgentService, "delete_agent", fake_delete_agent)

    response = client.delete(f"/api/v1/agents/{agent_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert captured["agent_id"] == agent_id


def test_viewer_cannot_delete_agent(client: TestClient) -> None:
    _override_user(_user(UserRole.VIEWER))

    response = client.delete(f"/api/v1/agents/{uuid.uuid4()}")

    assert response.status_code == 403
