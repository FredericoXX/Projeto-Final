"""Harness offline que executa a camada real de answering.

Nada aqui reimplementa comportamento da aplicação. O fallback,
`select_evidence`, `validate_generated_answer`, a precedência das
rejeições e a construção do `AnsweringResponse` continuam a ser os da
aplicação: este módulo apenas fornece as dependências sintéticas que
`app.services.answering_service.ask` exige.

Dois obstáculos técnicos separam a camada real de uma execução offline, e
ambos são contornados **sem alterar código de produção**:

1. `get_institution` precisa de uma `Session`. `SentinelSession` responde
   ao único `get` que essa função faz e recusa tudo o resto, pelo que a
   função real permanece no caminho executado.
2. `ask` lê os limites de `settings`. `answering_limits` substitui-os
   temporariamente pelos de `corpus.execution_config` e restaura-os
   sempre, para que a avaliação não dependa da configuração local.

Este módulo não é reexportado por `app/evaluation/__init__.py`: importar
`app.evaluation.assets` tem de continuar a não carregar as Settings nem o
SDK do fornecedor.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.orm import Session

from app.answering.base import AnsweringContext, GeneratedAnswer
from app.core.config import settings
from app.evaluation.contracts import CorpusCase, ExecutionConfig
from app.models.institution import Institution
from app.models.user import User
from app.retrieval.base import (
    Evidence,
    RetrievalContext,
    RetrievalResult,
    RetrievalTrace,
    ScoreKind,
    ScoreSemantics,
)

# Namespace estável: os UUID técnicos são derivados, nunca versionados no
# corpus, e nunca aparecem no relatório.
EVALUATION_NAMESPACE: Final[UUID] = uuid5(
    NAMESPACE_URL, "https://example.invalid/moment-05/evaluation"
)
SYNTHETIC_INSTITUTION_ID: Final[UUID] = uuid5(EVALUATION_NAMESPACE, "institution")
SYNTHETIC_USER_ID: Final[UUID] = uuid5(EVALUATION_NAMESPACE, "user")

# `Evidence` exige o campo, mas o answering usa a **ordem** do ranking e
# nunca o valor (ver docs/answering.md). Uma constante deixa isso claro.
SYNTHETIC_EVIDENCE_SCORE: Final = 1.0

# E o contrato deixa-o explícito: este 1.0 não é relevância lexical nem
# qualquer outra medida. Declará-lo `LEXICAL_RELEVANCE` daria significado
# científico a um número que existe apenas para satisfazer o dataclass.
SYNTHETIC_SCORE_SEMANTICS: Final = ScoreSemantics(
    kind=ScoreKind.SYNTHETIC,
    version="moment05_harness_v1",
    comparable_across_queries=False,
)

SYNTHETIC_LANGUAGES: Final[list[str]] = ["pt", "en"]

# Fixo, para que o harness não dependa de settings.answering_default_top_k.
# O retriever falso devolve as evidências do caso independentemente deste
# valor, mas regista-o para auditoria.
HARNESS_TOP_K: Final = 1


class UnexpectedDatabaseAccess(RuntimeError):
    """A execução offline tentou aceder à base de dados.

    A avaliação nunca lê nem escreve na base de dados de desenvolvimento;
    o único acesso previsto é a leitura da instituição sintética, que
    `SentinelSession` serve de memória.
    """


@dataclass
class SentinelSession:
    """Substituto mínimo de `Session`: falha fechada.

    Não herda de `sqlalchemy.orm.Session` — herdar traria comportamento
    que não queremos e mascararia acessos inesperados atrás de erros do
    SQLAlchemy. Implementa apenas `get`; qualquer outro atributo levanta.
    """

    institution: Institution
    accesses: list[tuple[str, str]] = field(default_factory=list)

    def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        name = getattr(entity, "__name__", str(entity))
        self.accesses.append((name, str(ident)))
        if entity is Institution and ident == SYNTHETIC_INSTITUTION_ID:
            return self.institution
        msg = f"acesso inesperado à base de dados: get({name})"
        raise UnexpectedDatabaseAccess(msg)

    def __getattr__(self, name: str) -> Any:
        msg = f"acesso inesperado à base de dados: {name}"
        raise UnexpectedDatabaseAccess(msg)


@dataclass
class FakeRetriever:
    """Devolve exatamente as evidências do caso e regista os argumentos."""

    evidence: list[Evidence]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> RetrievalResult:
        self.calls.append({"top_k": top_k, "official_only": official_only})
        # O trace é factual sobre este fake: as evidências do caso são as
        # únicas candidatas e nenhuma é excluída. Não se inventa detalhe
        # lexical — o fake não faz correspondência lexical nenhuma.
        return RetrievalResult(
            evidence=tuple(self.evidence),
            trace=RetrievalTrace(
                candidates_evaluated=len(self.evidence),
                result_count_before_limit=len(self.evidence),
            ),
            score_semantics=SYNTHETIC_SCORE_SEMANTICS,
        )


@dataclass
class FakeAnswerGenerator:
    """Devolve o `generator_output` declarado e regista cada contexto.

    Os contextos registados são a única forma honesta de observar que IDs
    existiam de facto no pedido — o resultado de `select_evidence`, não a
    lista do corpus.
    """

    generated: GeneratedAnswer
    contexts: list[AnsweringContext] = field(default_factory=list)

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        self.contexts.append(context)
        return self.generated

    @property
    def call_count(self) -> int:
        return len(self.contexts)


def synthetic_institution(name: str) -> Institution:
    """Instituição desligada: `ask` lê apenas nome e idiomas."""
    return Institution(
        id=SYNTHETIC_INSTITUTION_ID,
        name=name,
        code="SYNTHETIC",
        default_language="pt",
        supported_languages=list(SYNTHETIC_LANGUAGES),
        is_active=True,
    )


def synthetic_user() -> User:
    """Utilizador desligado: `ask` lê apenas `institution_id`."""
    return User(id=SYNTHETIC_USER_ID, institution_id=SYNTHETIC_INSTITUTION_ID)


def build_evidence(case: CorpusCase) -> list[Evidence]:
    """Materializa as evidências do caso com identificadores derivados.

    `document_id` e `document_version_id` derivam de `document_ref`, pelo
    que dois chunks do mesmo documento os partilham, como no retrieval
    real. `chunk_index` é a posição dentro do próprio `document_ref`.
    """
    chunk_positions: dict[str, int] = {}
    materialized: list[Evidence] = []
    for item in case.evidence:
        position = chunk_positions.get(item.document_ref, 0)
        chunk_positions[item.document_ref] = position + 1
        materialized.append(
            Evidence(
                chunk_id=uuid5(EVALUATION_NAMESPACE, f"{case.case_id}/{item.evidence_id}/chunk"),
                document_id=uuid5(
                    EVALUATION_NAMESPACE, f"{case.case_id}/{item.document_ref}/document"
                ),
                document_version_id=uuid5(
                    EVALUATION_NAMESPACE, f"{case.case_id}/{item.document_ref}/version"
                ),
                document_title=item.document_title,
                chunk_index=position,
                content=item.content,
                score=SYNTHETIC_EVIDENCE_SCORE,
                language=item.language.value,
                official_source=item.official_source,
                source_url=item.source_url,
                valid_from=item.valid_from,
                valid_until=item.valid_until,
            )
        )
    return materialized


@contextmanager
def answering_limits(config: ExecutionConfig) -> Iterator[None]:
    """Aplica os limites do corpus e restaura sempre os originais.

    Os valores vêm exclusivamente de `corpus.execution_config`, para que a
    avaliação não dependa do `.env` da máquina. A restauração vive num
    `finally`, pelo que ocorre também quando um caso levanta.
    """
    original_answer_chars = settings.answering_max_answer_chars
    original_context_chars = settings.answering_max_context_chars
    settings.answering_max_answer_chars = config.max_answer_chars
    settings.answering_max_context_chars = config.max_context_chars
    try:
        yield
    finally:
        settings.answering_max_answer_chars = original_answer_chars
        settings.answering_max_context_chars = original_context_chars
