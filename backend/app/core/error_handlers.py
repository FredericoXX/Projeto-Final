"""Global handlers that translate domain errors into HTTP responses.

Centralizing this here means routers raise domain exceptions
(NotFoundError, ConflictError, ValidationError) and never construct
HTTPException themselves, keeping the error contract consistent across
every resource as more of them are added.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import ConflictError, NotFoundError, ValidationError


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code, "message": message}},
    )


async def not_found_error_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return _error_response(404, "resource_not_found", str(exc))


async def conflict_error_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return _error_response(409, "resource_conflict", str(exc))


async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return _error_response(422, "domain_validation_error", str(exc))


# Ponto único de registo: qualquer novo tipo de DomainError só precisa de
# um handler aqui para ganhar uma resposta HTTP consistente em toda a API.
def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, not_found_error_handler)
    app.add_exception_handler(ConflictError, conflict_error_handler)
    app.add_exception_handler(ValidationError, validation_error_handler)
