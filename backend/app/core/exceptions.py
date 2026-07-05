from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class NexusMeshException(Exception):
    """Base exception for NexusMesh."""

    status_code: int = 500
    detail: str = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


class AuthenticationError(NexusMeshException):
    status_code = 401
    detail = "Authentication required"


class AuthorizationError(NexusMeshException):
    status_code = 403
    detail = "Permission denied"


class NotFoundError(NexusMeshException):
    status_code = 404
    detail = "Resource not found"


class ConflictError(NexusMeshException):
    status_code = 409
    detail = "Resource already exists"


class ValidationError(NexusMeshException):
    status_code = 422
    detail = "Validation failed"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NexusMeshException)
    async def nexusmesh_exception_handler(
        request: Request, exc: NexusMeshException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
