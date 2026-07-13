# Hierarquia de erros de domínio, independente de detalhes HTTP: os
# handlers globais (error_handlers.py) é que sabem converter cada tipo
# no código de estado e formato de resposta apropriados.
class DomainError(Exception):
    """Base class for domain-level errors."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ValidationError(DomainError):
    pass


class AuthenticationError(DomainError):
    pass


class AuthorizationError(DomainError):
    pass


class PayloadTooLargeError(DomainError):
    pass


class UnsupportedMediaTypeError(DomainError):
    pass


class ServiceUnavailableError(DomainError):
    """Uma capacidade interna não está configurada/disponível (-> 503)."""


class UpstreamServiceError(DomainError):
    """Um serviço externo falhou ou devolveu output inutilizável (-> 502).

    A mensagem tem de ser curta e segura; os detalhes técnicos do
    fornecedor ficam apenas nos logs.
    """
