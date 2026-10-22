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


class InstitutionalAccessError(DomainError):
    """A consulta a um serviço institucional não produziu dados utilizáveis.

    ``outcome`` é um valor de
    :class:`app.institutional.contracts.InstitutionalAccessOutcome` diferente de
    sucesso e de ausência de dados; o handler HTTP traduz cada um num código
    distinto. Guardado como texto para que este módulo não dependa do contrato
    institucional. A mensagem é curta e pública: nunca transporta dados
    académicos nem detalhes do fornecedor.

    ``provenance`` é a proveniência mínima do resultado, já serializada
    (``InstitutionalProvenanceRead`` em modo JSON), e é devolvida ao cliente em
    ``detail.provenance``. Inclui ``no_data`` no detalhe de um pedido, que
    responde 404.
    """

    def __init__(
        self,
        outcome: str,
        message: str,
        *,
        provenance: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.provenance = provenance
