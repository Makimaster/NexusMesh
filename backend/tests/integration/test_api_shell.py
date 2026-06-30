from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_service import AuthService


def test_root_health_endpoint_returns_status_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_routes_are_registered(monkeypatch) -> None:
    async def fake_login(self, email: str, password: str) -> dict[str, str]:
        return {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "token_type": "bearer",
        }

    monkeypatch.setattr(AuthService, "login", fake_login)
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "s3cure-passw0rd"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
