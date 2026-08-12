"""A3/A4.1 — o contrato de resultado do retrieval e a semântica do score.

Dois grupos de testes, com naturezas diferentes:

- **puros**, sobre as dataclasses de ``app.retrieval.base``: imutabilidade,
  campos mínimos e a declaração de semântica do score;
- **de integração**, com PostgreSQL real, que provam que o retriever lexical
  devolve o trace pelo contrato — e não por um método paralelo — e que o score
  público é o composto do reranker.

O que estes testes deliberadamente **não** afirmam: nada sobre o valor absoluto
de um score ("acima de 0.7 é bom"). Essa semântica não existe. O que se fixa é a
origem do número e a forma como é declarado, nunca uma escala de qualidade.
"""

import dataclasses
import inspect

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.text_normalization import normalize_text
from app.diagnostics import document_pipeline
from app.retrieval.base import (
    RetrievalResult,
    RetrievalTrace,
    ScoreKind,
    ScoreSemantics,
)
from app.retrieval.lexical import (
    LEXICAL_SCORE_SEMANTICS,
    LexicalRetrievalTrace,
    PostgresLexicalRetriever,
)
from app.retrieval.reranking import SCORING_VERSION
from tests.test_retrieval_reranking import _context, _setup_calendar

# --- Contratos puros ---------------------------------------------------------


@pytest.mark.parametrize(
    "contract", [RetrievalResult, RetrievalTrace, ScoreSemantics]
)
def test_contracts_are_frozen_dataclasses(contract: type) -> None:
    """Um resultado descreve uma pesquisa já feita: não deve ser editável."""
    assert dataclasses.is_dataclass(contract)
    assert contract.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_retrieval_trace_declares_only_strategy_neutral_counts() -> None:
    """Sinais lexicais não pertencem à base: uma estratégia densa não os tem."""
    assert {field.name for field in dataclasses.fields(RetrievalTrace)} == {
        "candidates_evaluated",
        "result_count_before_limit",
    }


def test_retrieval_result_carries_evidence_trace_and_score_semantics() -> None:
    assert {field.name for field in dataclasses.fields(RetrievalResult)} == {
        "evidence",
        "trace",
        "score_semantics",
    }


def test_retrieval_result_has_no_aggregated_outcome() -> None:
    """A A3/A4.0 rejeitou um ``RetrievalOutcome``.

    Um valor como ``SUFFICIENT`` afirmaria que a evidência **chega**, que é
    answerability e não recuperação: o retrieval não conhece os requisitos de
    informação do pedido. O consumidor observa contagens e conclui por si.
    """
    field_names = {field.name for field in dataclasses.fields(RetrievalResult)}

    assert "outcome" not in field_names
    assert not hasattr(RetrievalResult, "outcome")


def test_lexical_trace_satisfies_the_neutral_contract() -> None:
    """O trace lexical **é** um ``RetrievalTrace``, com detalhe acrescentado."""
    assert issubclass(LexicalRetrievalTrace, RetrievalTrace)

    lexical_only = {field.name for field in dataclasses.fields(LexicalRetrievalTrace)} - {
        field.name for field in dataclasses.fields(RetrievalTrace)
    }

    assert "fts_config" in lexical_only
    assert "excluded_below_threshold" in lexical_only


# --- Semântica do score ------------------------------------------------------


def test_lexical_score_semantics_declares_composed_lexical_relevance() -> None:
    assert LEXICAL_SCORE_SEMANTICS.kind is ScoreKind.LEXICAL_RELEVANCE
    assert LEXICAL_SCORE_SEMANTICS.version == SCORING_VERSION


def test_lexical_score_is_not_declared_comparable_across_queries() -> None:
    """Deriva do algoritmo, não de prudência.

    ``coverage`` é uma fração do número de termos **desta** pergunta, e
    ``exact_phrase``, ``ordered`` e ``proximity`` valem 1.0 por construção numa
    pergunta de um só termo. Comparar scores de perguntas diferentes compara
    sobretudo o comprimento das perguntas.
    """
    assert LEXICAL_SCORE_SEMANTICS.comparable_across_queries is False


def test_no_score_kind_claims_probability_or_confidence() -> None:
    """O vocabulário do contrato não sugere uma interpretação probabilística."""
    forbidden = ("probability", "confidence", "certainty", "probabilistic")
    declared = {member.value for member in ScoreKind}
    declared |= {member.name.lower() for member in ScoreKind}

    for term in forbidden:
        assert not any(term in value for value in declared)


# --- Integração: o trace atravessa o contrato --------------------------------


def test_search_returns_result_whose_trace_describes_that_same_search(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O trace é um subproduto da pesquisa, não uma segunda pesquisa.

    Este é o teste que falha se alguém voltar a escrever
    ``evidence, _trace = ...; return evidence``: sem o trace no contrato não há
    de onde ler as contagens, e a coerência aritmética entre elas e a evidência
    devolvida deixaria de poder ser afirmada.
    """
    institution, _headers = _setup_calendar(client)
    retriever = PostgresLexicalRetriever()

    with test_session_factory() as db:
        result = retriever.search(
            db,
            normalize_text("Até quando posso mudar o regime de avaliação?"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )

    assert isinstance(result, RetrievalResult)
    assert isinstance(result.trace, LexicalRetrievalTrace)
    assert result.evidence

    # A evidência devolvida é um subconjunto do que sobreviveu à seleção, e o
    # trace contabiliza a mesma pesquisa que a produziu.
    assert len(result.evidence) <= result.trace.result_count_before_limit
    assert result.trace.result_count_before_limit <= result.trace.candidates_evaluated
    assert result.trace.candidates_evaluated == (
        result.trace.result_count_before_limit
        + result.trace.excluded_no_content_match
        + result.trace.excluded_insufficient_coverage
        + result.trace.excluded_below_threshold
    )
    # E o detalhe do trace corresponde à evidência efetivamente devolvida.
    assert len(result.trace.results) == len(result.evidence)
    assert [row.chunk_id for row in result.trace.results] == [
        str(item.chunk_id) for item in result.evidence
    ]


def test_retriever_exposes_no_optional_trace_capability() -> None:
    """O trace deixou de ser descoberto por introspeção.

    Enquanto ``search_with_trace`` existisse, um consumidor podia continuar a
    perguntar ao retriever se ele "sabe" produzir trace — e um retriever que não
    soubesse degradava em silêncio. A capacidade é agora obrigatória.
    """
    assert not hasattr(PostgresLexicalRetriever, "search_with_trace")


def test_diagnostics_reads_the_trace_from_the_contract_not_by_introspection() -> None:
    """O diagnóstico deixou de descobrir capacidades por introspeção.

    Antes fazia ``getattr(retriever, "search_with_trace", None)`` e, se o
    método não existisse, seguia com ``trace = None``. Um retriever de outra
    estratégia perdia a secção lexical **e** as contagens, sem que nada o
    assinalasse. Hoje o trace chega pelo contrato e só o *detalhe lexical* é
    estreitado, por ``isinstance``.
    """
    module_source = inspect.getsource(document_pipeline)

    assert "search_with_trace" not in module_source
    assert "getattr(retriever" not in module_source
    assert "hasattr(retriever" not in module_source

    # E o estreitamento do trace faz-se por tipo, não por sondagem de atributos:
    # ``isinstance`` falha alto quando a forma muda; ``getattr(..., None)``
    # devolve ``None`` e segue. O módulo usa ``getattr`` noutro sítio, para
    # serializar campos de dataclasses — daí verificar-se esta função e não o
    # módulo inteiro.
    narrowing = document_pipeline._lexical_trace_of
    narrowing_code = inspect.getsource(narrowing).replace(narrowing.__doc__ or "", "")

    assert "isinstance(" in narrowing_code
    assert "getattr" not in narrowing_code
    assert "hasattr" not in narrowing_code


def test_evidence_is_an_immutable_tuple(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _headers = _setup_calendar(client)
    retriever = PostgresLexicalRetriever()

    with test_session_factory() as db:
        result = retriever.search(
            db,
            normalize_text("Até quando posso mudar o regime de avaliação?"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )

    assert isinstance(result.evidence, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.evidence = ()  # type: ignore[misc]


# --- Integração: o score público é o composto --------------------------------


def test_public_score_is_the_composed_rerank_score_not_raw_ts_rank_cd(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """Fixa a origem do número exposto em ``Evidence.score``.

    A A3/A4.0 mostrou que trocar ``ranked.score`` por ``candidate.raw_score``
    era detetado apenas por uma asserção incidental sobre ordenação, cuja
    mensagem nada dizia sobre score. Aqui a propriedade é afirmada
    diretamente: para cada evidência devolvida, o score é o que
    ``compute_score`` produz a partir dos sinais registados no trace, e **não**
    o ``ts_rank_cd`` cru que o trace guarda em separado.

    Nada aqui afirma que um valor alto é "bom": só de onde o valor vem.
    """
    institution, _headers = _setup_calendar(client)
    retriever = PostgresLexicalRetriever()

    with test_session_factory() as db:
        result = retriever.search(
            db,
            normalize_text("Até quando posso mudar o regime de avaliação?"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )

    assert result.evidence
    assert isinstance(result.trace, LexicalRetrievalTrace)
    rows_by_chunk = {row.chunk_id: row for row in result.trace.results}

    differed_from_raw = False
    for item in result.evidence:
        row = rows_by_chunk[str(item.chunk_id)]
        assert item.score == pytest.approx(row.score)
        if row.raw_score != pytest.approx(row.score):
            differed_from_raw = True

    # O cenário só prova alguma coisa se os dois valores forem distinguíveis.
    assert differed_from_raw, "cenário inútil: composto e raw coincidem"


def test_composed_score_stays_within_the_declared_unit_range(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _headers = _setup_calendar(client)
    retriever = PostgresLexicalRetriever()

    with test_session_factory() as db:
        result = retriever.search(
            db,
            normalize_text("Exames da 1.ª chamada"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )

    for item in result.evidence:
        assert 0.0 <= item.score <= 1.0


# --- O contrato interno não escapa para HTTP ---------------------------------


def test_public_retrieval_payload_exposes_no_internal_contract_fields(
    client: TestClient,
) -> None:
    """Trace e semântica do score são domínio interno e ficam lá."""
    _institution, headers = _setup_calendar(client)
    body = client.post(
        "/api/v1/retrieval/search",
        json={"query": "Até quando posso mudar o regime de avaliação?"},
        headers=headers,
    ).json()

    assert set(body) == {"query", "language", "items"}
    assert body["items"]
    for item in body["items"]:
        for leaked in ("trace", "score_semantics", "score_kind", "candidates_evaluated"):
            assert leaked not in item
