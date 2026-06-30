from app.config.settings import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_token,
)


def test_password_hash_and_verify_roundtrip() -> None:
    raw_password = "s3cure-passw0rd"

    hashed_password = get_password_hash(raw_password)

    assert hashed_password != raw_password
    assert verify_password(raw_password, hashed_password) is True
    assert verify_password("wrong-password", hashed_password) is False


def test_access_and_refresh_token_roundtrip() -> None:
    access_token = create_access_token({"sub": "user-1"})
    refresh_token = create_refresh_token({"sub": "user-1"})

    access_payload = verify_token(access_token)
    refresh_payload = verify_token(refresh_token)

    assert access_payload["sub"] == "user-1"
    assert access_payload["type"] == "access"
    assert refresh_payload["sub"] == "user-1"
    assert refresh_payload["type"] == "refresh"


def test_settings_load_required_secrets() -> None:
    assert len(settings.SECRET_KEY) >= 32
    assert len(settings.JWT_SECRET_KEY) >= 32
