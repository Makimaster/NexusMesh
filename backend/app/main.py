from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.common.redis_client import close_redis, get_redis_instance
from app.config.settings import settings
from app.core.exceptions import register_exception_handlers
from app.websocket.broadcaster import broadcaster
from app.websocket.gateway import router as ws_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    redis = await get_redis_instance()
    await broadcaster.start(redis)
    yield
    await broadcaster.stop()
    await close_redis()


app = FastAPI(
    title=f"{settings.APP_NAME} API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(ws_router)


@app.get("/health", tags=["health"])
async def root_health() -> dict:
    return {"status": "ok", "version": "0.1.0", "env": settings.APP_ENV}
