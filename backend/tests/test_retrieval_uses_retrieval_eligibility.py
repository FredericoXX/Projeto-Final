"""Fase 2 da issue #24 — o retrieval lexical consome ``RetrievalEligibility``.

O que já existe cobre o **comportamento**: ``test_retrieval.py`` prova pela API
que documentos inativos, expirados, não oficiais, de outra instituição ou de
uma versão superada não aparecem nos resultados, e
``test_evidence_retrievability_contract.py`` prova que os dois adaptadores da
política selecionam o mesmo conjunto. Nenhum deles falharia se alguém voltasse
a escrever a admissibilidade documental à mão dentro do retriever: o
comportamento seria o mesmo e a duplicação regressaria em silêncio.

É essa a lacuna que este ficheiro fecha. Fixa a **fonte de verdade**, não a
matriz C1–C12 — essa não é repetida aqui — e o risco específico que a migração
introduziu: o join novo a ``DocumentVersion``, que a política exige por
referenciar as colunas da versão, poderia alterar a cardinalidade da consulta.

A fonte de verdade é fixada **dinamicamente**, por espia sobre as duas chamadas
que a produzem — ``as_sql_filters`` para C1–C4 e C6–C11,
``latest_processed_version_subquery`` para C5. Procurar o texto dos predicados
dentro do SQL compilado não bastaria: filtros reescritos à mão produzem
exatamente o mesmo texto, e o import da política ficaria por usar sem que nada
falhasse.

Os cenários com base de dados reutilizam os helpers de ``moment06_support``, que
atravessam a API real, em vez de duplicar a construção de instituições e
documentos.
"""

import re
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import BooleanClauseList
from sqlalchemy.sql.selectable import Subquery

from app import retrieval as retrieval_package
from app.documents.retrievability import (
    EvidencePolicy,
    RetrievabilityContext,
    RetrievalEligibility,
    latest_processed_version_subquery,
)
from app.models.document_chunk import DocumentChunk
from app.retrieval import lexical as lexical_module
from app.retrieval.base import RetrievalContext
from app.retrieval.lexical import PostgresLexicalRetriever
from tests.moment06_support import (
    create_searchable_document,
    setup_institution_with_admin,
    upload_version,
)

REFERENCE_DATE = date(2026, 8, 11)
QUOTA = 100

# Termo presente em todos os documentos dos cenários: a admissibilidade é a
# única variável, nunca a correspondência lexical.
TERM = "campus"

_BIND_PARAM = re.compile(r"%\(\w+\)s")
_WHITESPACE = re.compile(r"\s+")


def _normalise(sql: object) -> str:
    """Texto SQL sem nomes de bind params nem quebras de linha.

    Os nomes gerados (``institution_id_1`` contra ``institution_id_2``) mudam
    com a posição na consulta e não fazem parte da semântica; compará-los
    tornaria o teste sensível à ordem das cláusulas em vez de à sua presença.
    """
    return _WHITESPACE.sub(" ", _BIND_PARAM.sub("?", str(sql))).strip()


def _retrieval_context(institution_id: uuid.UUID) -> RetrievalContext:
    return RetrievalContext(
        institution_id=institution_id,
        language="pt",
        reference_date=REFERENCE_DATE,
    )


def _expected_retrievability_context(
    institution_id: uuid.UUID, *, official_only: bool
) -> RetrievabilityContext:
    return RetrievabilityContext(
        institution_id=institution_id,
        language="pt",
        reference_date=REFERENCE_DATE,
        official_only=official_only,
    )


def _ts_query(term: str = TERM):
    return func.websearch_to_tsquery("portuguese", term)


def _compiled_statement(*, official_only: bool, institution_id: uuid.UUID) -> str:
    statement = PostgresLexicalRetriever()._build_statement(
        _ts_query(), _retrieval_context(institution_id), QUOTA, official_only
    )
    return _normalise(statement.compile(dialect=postgresql.dialect()))


# --- A fonte de verdade -------------------------------------------------------


def test_the_retriever_no_longer_defines_documental_admissibility_itself() -> None:
    """A definição duplicada saiu do módulo, em vez de coexistir com a nova."""
    assert not hasattr(PostgresLexicalRetriever, "_latest_processed_subquery")

    # Importa a política de recuperação e a forma canónica de C5...
    assert lexical_module.RetrievalEligibility is RetrievalEligibility
    assert (
        lexical_module.latest_processed_version_subquery
        is latest_processed_version_subquery
    )
    # ...e não a política de persistência de citações, que responde a outra
    # pergunta e não pertence à recuperação.
    assert not hasattr(lexical_module, "CitationPersistenceEligibility")


def test_the_policy_used_by_retrieval_is_the_one_that_includes_c5() -> None:
    """Recuperação pergunta "agora"; por isso C5 tem de fazer parte."""
    assert RetrievalEligibility.requires_latest_processed_version is True
    assert "version_is_highest_processed" in RetrievalEligibility.condition_names


def test_the_documental_policy_module_does_not_depend_on_retrieval() -> None:
    """A dependência é ``retrieval -> documents``, e só nesse sentido.

    Se ela se invertesse, uma estratégia futura (densa, híbrida) deixaria de
    poder reutilizar a política sem arrastar o retrieval lexical consigo.
    """
    import app.documents.retrievability as retrievability_module

    for name, value in vars(retrievability_module).items():
        module = getattr(value, "__module__", "")
        assert not module.startswith(retrieval_package.__name__), (
            f"{name} vem de {module}"
        )


class _PolicySpy:
    """Delega na política real e regista o que lhe foi pedido.

    Existe porque procurar o SQL dos predicados dentro do statement **não
    distingue** "o retriever pediu-os à política" de "o retriever voltou a
    escrevê-los à mão e deixou o import por usar": as duas situações produzem
    exatamente o mesmo texto compilado.
    """

    def __init__(self, policy: EvidencePolicy) -> None:
        self._policy = policy
        self.contexts: list[RetrievabilityContext] = []
        self.returned: tuple[ColumnElement[bool], ...] = ()

    def as_sql_filters(
        self, context: RetrievabilityContext
    ) -> tuple[ColumnElement[bool], ...]:
        self.contexts.append(context)
        self.returned = self._policy.as_sql_filters(context)
        return self.returned


@pytest.mark.parametrize("official_only", [True, False])
def test_the_documental_filters_are_obtained_from_the_policy(
    official_only: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1–C4 e C6–C11 vêm de uma chamada real a ``as_sql_filters``.

    Não se afirma quantas condições a política tem — isso é matéria do teste de
    composição da Fase 1, e depender aqui desse número tornaria este ficheiro
    refém de uma decisão que não lhe pertence. Afirma-se que **tudo** o que a
    chamada devolveu está no ``WHERE``, e que o ``WHERE`` não tem mais nada
    além disso, do corte da window que materializa C5 e da correspondência
    lexical.
    """
    institution_id = uuid.uuid4()
    spy = _PolicySpy(RetrievalEligibility)
    monkeypatch.setattr(lexical_module, "RetrievalEligibility", spy)

    statement = PostgresLexicalRetriever()._build_statement(
        _ts_query(), _retrieval_context(institution_id), QUOTA, official_only
    )

    assert spy.contexts == [
        _expected_retrievability_context(institution_id, official_only=official_only)
    ]
    assert spy.returned

    compiled = _normalise(statement.compile(dialect=postgresql.dialect()))
    for clause in spy.returned:
        rendered = _normalise(clause.compile(dialect=postgresql.dialect()))
        assert rendered in compiled, rendered

    # Os dois predicados que `as_sql_filters` não devolve. `rn == 1` também é
    # admissibilidade documental — é a forma SQL de C5, que não é condição de
    # linha e por isso chega pela subquery; só a correspondência lexical
    # pertence ao mecanismo de pesquisa. A igualdade impede que um filtro
    # documental reapareça inline **ao lado** da chamada à política.
    where = statement.whereclause
    assert isinstance(where, BooleanClauseList)
    assert len(where.clauses) == len(spy.returned) + 2


def test_official_only_removes_the_condition_instead_of_negating_it() -> None:
    """C11 sai do ``WHERE`` quando desligada — não vira tautologia."""
    institution_id = uuid.uuid4()
    restricted = _compiled_statement(official_only=True, institution_id=institution_id)
    permissive = _compiled_statement(official_only=False, institution_id=institution_id)

    assert "documents.official_source IS true" in restricted
    assert "documents.official_source IS true" not in permissive
    # A coluna continua a ser devolvida: o que desaparece é o filtro.
    assert "documents.official_source" in permissive


def test_c5_is_obtained_from_the_canonical_subquery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C5 vem da definição do módulo documental, com o contexto traduzido."""
    institution_id = uuid.uuid4()
    calls: list[RetrievabilityContext] = []

    def _recording(context: RetrievabilityContext) -> Subquery:
        calls.append(context)
        return latest_processed_version_subquery(context)

    monkeypatch.setattr(
        lexical_module, "latest_processed_version_subquery", _recording
    )
    PostgresLexicalRetriever()._build_statement(
        _ts_query(), _retrieval_context(institution_id), QUOTA, True
    )

    assert calls == [
        _expected_retrievability_context(institution_id, official_only=True)
    ]


def test_only_one_window_function_survives_in_the_statement() -> None:
    """Uma única definição de "versão efetiva", não duas em paralelo."""
    compiled = _compiled_statement(official_only=True, institution_id=uuid.uuid4())
    assert compiled.count("row_number()") == 1
    assert compiled.count("PARTITION BY document_versions.document_id") == 1


# --- O mecanismo que permanece no retrieval -----------------------------------


def test_lexical_matching_and_quota_stay_in_the_retriever() -> None:
    """A correspondência lexical não pertence à política de admissibilidade."""
    compiled = _compiled_statement(official_only=True, institution_id=uuid.uuid4())
    assert "search_vector @@ websearch_to_tsquery" in compiled
    assert "ts_rank_cd(document_chunks.search_vector" in compiled
    assert "LIMIT" in compiled
    assert (
        "ORDER BY score DESC, documents.id ASC, document_chunks.chunk_index ASC, "
        "document_chunks.id ASC" in compiled
    )

    # E a política, do seu lado, não sabe nada sobre a pergunta.
    policy_sql = _normalise(
        RetrievalEligibility.select_eligible_chunk_ids(
            _expected_retrievability_context(uuid.uuid4(), official_only=True)
        ).compile(dialect=postgresql.dialect())
    )
    assert "search_vector" not in policy_sql
    assert "ts_rank_cd" not in policy_sql


def test_institution_isolation_is_applied_by_postgresql() -> None:
    """As três colunas ``institution_id`` continuam no ``WHERE``, não em Python."""
    compiled = _compiled_statement(official_only=True, institution_id=uuid.uuid4())
    for column in (
        "document_chunks.institution_id = ?",
        "documents.institution_id = ?",
        "document_versions.institution_id = ?",
    ):
        assert column in compiled


# --- Cardinalidade e equivalência, contra o PostgreSQL real --------------------


def test_the_version_join_does_not_duplicate_candidates(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O join novo é sobre a chave primária: uma linha por chunk, não mais.

    O documento tem chunks em duas versões ``processed``; se o join a
    ``DocumentVersion`` alterasse a cardinalidade, ou se C5 deixasse de
    escolher a versão efetiva, a contagem mudaria.
    """
    institution, headers, _ = setup_institution_with_admin(client)
    document, first = create_searchable_document(
        client, headers, f"O {TERM} antigo mantinha o horario alargado."
    )
    second = upload_version(
        client, headers, document["id"], f"O {TERM} atual encerra as dezoito horas."
    )

    institution_id = uuid.UUID(institution["id"])
    statement = PostgresLexicalRetriever()._build_statement(
        _ts_query(), _retrieval_context(institution_id), QUOTA, True
    )
    with test_session_factory() as db:
        rows = list(db.execute(statement))
        stored = db.scalars(
            select(DocumentChunk.id).where(
                DocumentChunk.document_id == uuid.UUID(document["id"])
            )
        ).all()

    # As duas versões deixaram chunks persistidos — havia matéria para duplicar.
    assert len(stored) >= 2
    assert len(rows) == 1
    assert str(rows[0].document_version_id) == second["id"]
    assert first["id"] != second["id"]


def test_the_statement_selects_exactly_the_eligible_chunks_that_match(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """A tese da Fase 2, observada em linhas reais.

    ``candidatos == RetrievalEligibility ∩ correspondência lexical``. Os
    documentos inadmissíveis contêm todos o mesmo termo, para que a exclusão
    seja da política e não do índice; e existe um documento admissível **sem**
    o termo, para que a interseção não seja trivialmente igual à política.
    """
    institution, headers, _ = setup_institution_with_admin(client)
    create_searchable_document(client, headers, f"O {TERM} principal recebe visitas.")
    create_searchable_document(
        client, headers, f"O {TERM} secundario nao e oficial.", official_source=False
    )
    create_searchable_document(
        client,
        headers,
        f"O {TERM} antigo esteve aberto.",
        valid_until=(REFERENCE_DATE.replace(year=REFERENCE_DATE.year - 1)).isoformat(),
    )
    inactive, _ = create_searchable_document(
        client, headers, f"O {TERM} desativado permanece registado."
    )
    patched = client.patch(
        f"/api/v1/documents/{inactive['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    create_searchable_document(client, headers, "A biblioteca abre ao sabado.")

    # Instituição vizinha com o mesmo termo: C1–C3 em jogo.
    _, other_headers, _ = setup_institution_with_admin(client)
    create_searchable_document(
        client, other_headers, f"O {TERM} da outra instituicao tambem existe."
    )

    institution_id = uuid.UUID(institution["id"])
    statement = PostgresLexicalRetriever()._build_statement(
        _ts_query(), _retrieval_context(institution_id), QUOTA, True
    )
    policy_selection = RetrievalEligibility.select_eligible_chunk_ids(
        _expected_retrievability_context(institution_id, official_only=True)
    )

    with test_session_factory() as db:
        candidates = {row.chunk_id for row in db.execute(statement)}
        eligible = set(db.scalars(policy_selection).all())
        matching = set(
            db.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.search_vector.op("@@")(_ts_query())
                )
            ).all()
        )

    assert candidates == eligible & matching
    # Nenhum dos dois lados é trivial: há elegíveis sem o termo e linhas com o
    # termo que a política recusa.
    assert eligible - matching
    assert matching - eligible
    assert candidates
