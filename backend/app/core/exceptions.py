class DomainError(Exception):
    """Base class for domain-level errors."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class ValidationError(DomainError):
    pass
