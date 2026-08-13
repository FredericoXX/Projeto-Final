"""Contratos neutros para geração experimental de respostas fundamentadas.

O router e o service de orquestração dependem apenas destes contratos —
nunca de um fornecedor, SDK ou modelo concreto. A geração aumentada por
evidências nesta fase é experimental e substituível; a abordagem final
depende da revisão da literatura e da avaliação experimental.
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.exceptions import ServiceUnavailableError, UpstreamServiceError
from app.retrieval.base import Evidence

# Mensagem única da indisponibilidade do gerador, qualquer que seja a
# causa: provider desconhecido (decidido na factory) ou chave/modelo em
# falta (detetado no adapter). Vive aqui, e não no adapter, para que a
# factory a possa usar sem importar fornecedor nenhum.
GENERATOR_UNAVAILABLE_MESSAGE = "Answer generation is not configured on this server."


class AnswerGeneratorUnavailableError(ServiceUnavailableError):
    """O gerador não está configurado/disponível (-> 503).

    Lançada apenas quando a geração é de facto necessária: a ausência de
    configuração nunca impede a aplicação de arrancar.
    """


class AnswerGenerationError(UpstreamServiceError):
    """O fornecedor falhou ou devolveu output inutilizável (-> 502).

    A mensagem é curta e segura; os detalhes técnicos (nunca a chave)
    ficam apenas nos logs do adapter.
    """


class InvalidGeneratedAnswerError(UpstreamServiceError):
    """A resposta gerada violou a validação determinística (-> 502).

    Ex.: citação de um evidence ID inexistente, resposta vazia ou acima
    do limite. A geração é rejeitada — nunca se adivinha a fonte nem se
    devolve a resposta como answered.

    `reason_code` é sempre um código estável controlado pela aplicação e
    `invalid_count` uma contagem — a exceção nunca armazena valores
    devolvidos pelo fornecedor (IDs, resposta, citações), porque esses
    dados são não confiáveis e acabariam nos logs. str(exc) é sempre a
    mensagem fixa e segura.
    """

    def __init__(
        self,
        message: str,
        reason_code: str = "invalid_output",
        invalid_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.invalid_count = invalid_count


@dataclass(frozen=True)
class ContextEvidence:
    """Uma evidência com o identificador estável (E1, E2, ...) do pedido."""

    evidence_id: str
    evidence: Evidence


@dataclass(frozen=True)
class AnsweringContext:
    """Input completo do gerador: pergunta + evidências já selecionadas.

    `evidence` preserva a ordem do ranking e já respeita
    `max_context_chars` (ver context.py); o gerador não volta a cortar.
    """

    query: str
    language: str
    institution_name: str
    evidence: tuple[ContextEvidence, ...]
    max_context_chars: int


@dataclass(frozen=True)
class GeneratedAnswer:
    """Output bruto do gerador, ainda por validar (ver validation.py)."""

    answer: str
    cited_evidence_ids: tuple[str, ...]


class AnswerGenerator(Protocol):
    def generate(self, context: AnsweringContext) -> GeneratedAnswer: ...
