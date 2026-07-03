def test_get_redis_instance_importable():
    from app.common.redis_client import get_redis_instance

    assert callable(get_redis_instance)
