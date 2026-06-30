import os

os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-characters")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-characters")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "nexusmesh")
os.environ.setdefault("POSTGRES_PASSWORD", "changeme")
os.environ.setdefault("POSTGRES_DB", "nexusmesh_db")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_DB", "0")
