"""Global handlers that translate domain errors into HTTP responses.

Centralizing this here means routers raise domain exceptions
(NotFoundError, ConflictError, ValidationError) and never construct
HTTPException themselves, keeping the error contract consistent across
every resource as more of them are added.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InstitutionalAccessError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    UpstreamServiceError,
    ValidationError,
)


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


async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    return _error_response(401, "authentication_failed", str(exc))


async def authorization_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
    return _error_response(403, "forbidden", str(exc))


async def payload_too_large_error_handler(
    request: Request, exc: PayloadTooLargeError
) -> JSONResponse:
    return _error_response(413, "payload_too_large", str(exc))


async def unsupported_media_type_error_handler(
    request: Request, exc: UnsupportedMediaTypeError
) -> JSONResponse:
    return _error_response(415, "unsupported_media_type", str(exc))


async def service_unavailable_error_handler(
    request: Request, exc: ServiceUnavailableError
) -> JSONResponse:
    return _error_response(503, "service_unavailable", str(exc))


async def upstream_service_error_handler(
    request: Request, exc: UpstreamServiceError
) -> JSONResponse:
    return _error_response(502, "upstream_error", str(exc))


# Cada resultado não satisfatório da integração institucional tem estado e
# código próprios, para que o cliente distinga acesso recusado, integração
# desativada e falha técnica — e para que nenhum deles se confunda com os
# erros do fornecedor de geração (service_unavailable / upstream_error).
INSTITUTIONAL_ACCESS_ERRORS: dict[str, tuple[int, str]] = {
    # O detalhe de um pedido inexistente — ou de outro aluno — mantém o código
    # genérico de recurso inexistente; só a proveniência é acrescentada.
    "no_data": (404, "resource_not_found"),
    "access_denied": (403, "institutional_access_denied"),
    "not_configured": (503, "institutional_integration_not_configured"),
    "unavailable": (502, "institutional_integration_unavailable"),
}


async def institutional_access_error_handler(
    request: Request, exc: InstitutionalAccessError
) -> JSONResponse:
    status_code, code = INSTITUTIONAL_ACCESS_ERRORS.get(
        exc.outcome, (502, "institutional_integration_unavailable")
    )
    detail: dict[str, object] = {"code": code, "message": str(exc)}
    if exc.provenance is not None:
        detail["provenance"] = exc.provenance
    return JSONResponse(status_code=status_code, content={"detail": detail})


# Ponto único de registo: qualquer novo tipo de DomainError só precisa de
# um handler aqui para ganhar uma resposta HTTP consistente em toda a API.
#
# Starlette tipa add_exception_handler para um handler genérico de
# Exception; passar-lhe um handler tipado para uma subclasse concreta
# (NotFoundError, etc.) é seguro em runtime, mas o mypy não consegue
# verificar essa covariância, daí os ignores pontuais abaixo.
def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, not_found_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ConflictError, conflict_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        AuthenticationError, authentication_error_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        AuthorizationError, authorization_error_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        PayloadTooLargeError, payload_too_large_error_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        UnsupportedMediaTypeError, unsupported_media_type_error_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        ServiceUnavailableError, service_unavailable_error_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        UpstreamServiceError, upstream_service_error_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        InstitutionalAccessError, institutional_access_error_handler  # type: ignore[arg-type]
    )
