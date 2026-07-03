def test_get_redis_instance_importable():
    from app.common.redis_client import get_redis_instance

    assert callable(get_redis_instance)


def test_extract_valid_channel():
    from app.websocket.broadcaster import broadcaster

    assert broadcaster._extract_execution_id("channel:execution:exec-123:events") == "exec-123"


def test_extract_uuid_channel():
    from app.websocket.broadcaster import broadcaster

    assert (
        broadcaster._extract_execution_id(
            "channel:execution:550e8400-e29b-41d4-a716-446655440000:events"
        )
        == "550e8400-e29b-41d4-a716-446655440000"
    )


def test_extract_empty_execution_id_returns_none():
    from app.websocket.broadcaster import broadcaster

    assert broadcaster._extract_execution_id("channel:execution::events") is None


def test_extract_bad_format_returns_none():
    from app.websocket.broadcaster import broadcaster

    assert broadcaster._extract_execution_id("channel:wrong:exec-123:events") is None


def test_extract_too_many_parts_returns_none():
    from app.websocket.broadcaster import broadcaster

    assert broadcaster._extract_execution_id("channel:execution:exec-123:events:extra") is None
