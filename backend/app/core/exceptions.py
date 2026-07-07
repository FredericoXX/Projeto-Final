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
