"""Integração da pesquisa lexical progressiva com PostgreSQL real.

Cobre perguntas naturais (PT/EN), a prioridade exact → reduced_and →
reduced_or, a preservação da semântica de operadores websearch, a
precisão da baseline (redução de falsos positivos) e a aplicação dos
filtros existentes durante as estratégias de fallback. Reutiliza os
helpers do módulo de testes de retrieval.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.document_version import DocumentVersion
from tests.test_retrieval import (
    _create_admin,
    _create_document,
    _create_institution,
    _create_searchable,
    _search,
    _setup,
    _upload,
)

# Pergunta natural cuja variante exact nunca corresponde aos conteúdos de
# teste ("começam" ausente): garante que cada cenário exercita de facto o
# fallback disjuntivo, não a consulta exata. Os conteúdos de teste
# partilham dois termos informativos com a pergunta ("aulas", "setembro"),
# porque uma única coincidência num total de três termos deixou de ser
# evidência (ver app.retrieval.eligibility).
FALLBACK_QUESTION = "Quando começam as aulas de setembro?"

# --- Perguntas naturais ----------------------------------------------------


def test_natural_portuguese_question_finds_same_evidence_as_keyword(
    client: TestClient,
) -> None:
    _, headers, _ = _setup(client)
    document, _ = _create_searchable(
        client,
        headers,
        "As aulas do primeiro semestre iniciam-se em 21 de setembro de 2026.",
        title="Calendário Letivo",
    )

    keyword = _search(client, headers, "aulas").json()["items"]
    assert len(keyword) == 1

    # O documento não contém "quando" nem "começam": a variante exata
    # falha e a evidência chega pela estratégia disjuntiva reduzida, com
    # dois dos três termos informativos cobertos ("aulas", "setembro").
    natural = _search(client, headers, FALLBACK_QUESTION)
    assert natural.status_code == 200
    body = natural.json()
    assert body["query"] == FALLBACK_QUESTION
    assert len(body["items"]) == 1
    assert body["items"][0]["chunk_id"] == keyword[0]["chunk_id"]
    assert body["items"][0]["document_id"] == document["id"]
    # Nenhum detalhe interno da estratégia aparece na resposta pública.
    assert set(body.keys()) == {"query", "language", "items"}
    for forbidden in ("strategy", "tsquery", "normalized_content", "stopword"):
        assert forbidden not in natural.text


def test_natural_english_question_finds_evidence(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(
        client,
        headers,
        "The International Office is open from Monday to Friday.",
        title="International Office",
        language="en",
    )

    items = _search(
        client, headers, "When is the International Office open?", language="en"
    ).json()["items"]
    assert len(items) == 1
    assert "International Office" in items[0]["content"]


def test_partial_coverage_candidates_are_excluded(client: TestClient) -> None:
    """A pergunta contém termos funcionais ("qual", "e", "o", "dos"), por
    isso a variante exata falha. As variantes são agregadas, incluindo a
    disjuntiva, pelo que o documento de matrículas (que também contém
    "período") entra no candidate pool — mas é excluído por **cobertura
    insuficiente**: cobre 1 dos 2 termos informativos, e uma única
    coincidência não é evidência."""
    _, headers, _ = _setup(client)
    exams, _ = _create_searchable(
        client,
        headers,
        "O período de exames decorre de 11 a 29 de janeiro de 2027.",
        title="Período de Exames",
    )
    _create_searchable(
        client,
        headers,
        "O período de matrícula decorre em setembro.",
        title="Período de Matrícula",
    )

    items = _search(client, headers, "Qual é o período dos exames?").json()["items"]
    assert [item["document_id"] for item in items] == [exams["id"]]


def test_exact_strategy_priority_over_disjunctive_fallback(client: TestClient) -> None:
    """Sem termos funcionais, a variante exata (conjuntiva) já casa o
    documento com ambos os termos. As variantes são agregadas, pelo que o
    documento que só contém "aulas" entra no candidate pool pela
    disjuntiva, mas é excluído por cobertura insuficiente (1 de 2)."""
    _, headers, _ = _setup(client)
    both, _ = _create_searchable(
        client, headers, "aulas de setembro no campus", title="Com Ambos"
    )
    _create_searchable(client, headers, "aulas de laboratório", title="Só Aulas")

    items = _search(client, headers, "aulas setembro").json()["items"]
    assert [item["document_id"] for item in items] == [both["id"]]


def test_precision_natural_question_prefers_relevant_document(
    client: TestClient,
) -> None:
    _, headers, _ = _setup(client)
    relevant, _ = _create_searchable(
        client, headers, "As aulas iniciam-se em setembro.", title="Aulas"
    )
    _create_searchable(
        client, headers, "O atendimento começa em agosto.", title="Atendimento"
    )

    items = _search(client, headers, FALLBACK_QUESTION).json()["items"]
    # Com a configuração portuguesa, "começa" casa "começam" na recuperação
    # FTS, mas a elegibilidade mantém apenas o documento de aulas: o
    # documento de atendimento não corresponde a nenhum termo canónico no
    # conteúdo (cobertura zero) e é excluído.
    assert [item["document_id"] for item in items] == [relevant["id"]]


def test_stopword_only_question_returns_no_irrelevant_results(
    client: TestClient,
) -> None:
    """Reprodução do achado da auditoria: o documento contém literalmente
    "O que é", pelo que a antiga variante exact corresponderia por pura
    coincidência de palavras funcionais. Sem termos informativos, não se
    pesquisa de todo — mas o documento continua pesquisável por termos
    com conteúdo."""
    _, headers, _ = _setup(client)
    _create_searchable(
        client,
        headers,
        "O que é a matrícula? A matrícula é o registo anual do estudante.",
        title="FAQ Matrícula",
    )

    for functional_query in ("O que é?", "Qual é o quê?"):
        response = _search(client, headers, functional_query)
        assert response.status_code == 200
        assert response.json()["items"] == []

    assert _search(client, headers, "matrícula").json()["items"]


def test_natural_question_without_match_stays_empty(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "As aulas iniciam-se em setembro.")
    items = _search(client, headers, "Qual o preço do transporte urbano?").json()[
        "items"
    ]
    assert items == []


def test_natural_question_respects_existing_filters(client: TestClient) -> None:
    """O fallback disjuntivo aplica exatamente os filtros atuais: fonte
    oficial, documento ativo e isolamento institucional."""
    _, headers, _ = _setup(client)
    # Todos os documentos partilham "aulas" e "setembro" com a pergunta,
    # pelo que todos seriam elegíveis: o que os exclui são exclusivamente
    # os filtros institucionais.
    _create_searchable(
        client,
        headers,
        "As aulas não oficiais iniciam-se em setembro.",
        title="Não Oficial",
        official_source=False,
    )
    inactive, _ = _create_searchable(
        client, headers, "As aulas antigas iniciam-se em setembro.", title="Inativo"
    )
    client.patch(
        f"/api/v1/documents/{inactive['id']}",
        json={"is_active": False},
        headers=headers,
    )

    institution_b = _create_institution(client)
    headers_b, _ = _create_admin(client, institution_b["id"])
    _create_searchable(
        client,
        headers_b,
        "As aulas da instituição B iniciam-se em setembro.",
        title="Outra Instituição",
    )

    official_only = _search(client, headers, FALLBACK_QUESTION).json()["items"]
    assert official_only == []

    relaxed = _search(
        client, headers, FALLBACK_QUESTION, official_only=False
    ).json()["items"]
    assert [item["document_title"] for item in relaxed] == ["Não Oficial"]


def test_natural_question_respects_top_k(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    for index in range(3):
        _create_searchable(
            client,
            headers,
            f"As aulas do curso {index} iniciam-se em setembro.",
            title=f"Curso {index}",
        )
    items = _search(client, headers, FALLBACK_QUESTION, top_k=2).json()["items"]
    assert len(items) == 2


# --- Operadores explícitos preservados ---------------------------------------


def test_or_operator_returns_union_without_relaxation(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    a, _ = _create_searchable(client, headers, "calendário de aulas teóricas", title="A")
    b, _ = _create_searchable(client, headers, "calendário de exames finais", title="B")

    items = _search(client, headers, "aulas OR exames").json()["items"]
    assert {item["document_id"] for item in items} == {a["id"], b["id"]}


def test_negated_term_semantics_never_relaxed(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(
        client, headers, "matricula exige pagamento de propinas", title="Com Propinas"
    )
    without_fees, _ = _create_searchable(
        client, headers, "matricula gratuita para bolseiros", title="Sem Propinas"
    )

    items = _search(client, headers, "matricula -propinas").json()["items"]
    assert [item["document_id"] for item in items] == [without_fees["id"]]

    # Quando a negação elimina tudo, o resultado permanece vazio: a
    # relaxação nunca pode voltar a procurar o termo negado.
    none = _search(client, headers, "matricula -propinas -gratuita").json()["items"]
    assert none == []


def test_quoted_phrase_semantics_preserved(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    phrase, _ = _create_searchable(
        client, headers, "aulas do primeiro semestre decorrem no campus", title="Frase"
    )
    _create_searchable(
        client, headers, "primeiro dia do semestre é festivo", title="Sem Frase"
    )

    items = _search(client, headers, '"primeiro semestre"').json()["items"]
    assert [item["document_id"] for item in items] == [phrase["id"]]

    # Frase sem correspondência não ganha fallback disjuntivo.
    reversed_phrase = _search(client, headers, '"semestre primeiro"').json()["items"]
    assert reversed_phrase == []


# --- Filtros aplicados durante o fallback ------------------------------------


def test_fallback_excludes_future_and_expired_documents(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    today = datetime.now(UTC).date()
    current, _ = _create_searchable(
        client, headers, "As aulas atuais decorrem em setembro.", title="Atual"
    )
    _create_searchable(
        client,
        headers,
        "As aulas futuras decorrem em setembro.",
        title="Futuro",
        valid_from=(today + timedelta(days=1)).isoformat(),
    )
    _create_searchable(
        client,
        headers,
        "As aulas expiradas decorreram em setembro.",
        title="Expirado",
        valid_until=(today - timedelta(days=1)).isoformat(),
    )

    items = _search(client, headers, FALLBACK_QUESTION).json()["items"]
    assert [item["document_id"] for item in items] == [current["id"]]


def test_fallback_searches_only_latest_processed_version(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    document = _create_document(client, headers)
    _upload(client, headers, document["id"], b"as aulas antigas decorrem em setembro")
    newest = _upload(
        client, headers, document["id"], b"as aulas novas decorrem em setembro"
    )

    items = _search(client, headers, FALLBACK_QUESTION).json()["items"]
    assert [item["document_version_id"] for item in items] == [newest["id"]]
    assert "novas" in items[0]["content"]


@pytest.mark.parametrize("latest_status", ["failed", "pending", "processing"])
def test_fallback_ignores_nonprocessed_newer_versions(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    latest_status: str,
) -> None:
    _, headers, _ = _setup(client)
    document = _create_document(client, headers)
    processed = _upload(
        client, headers, document["id"], b"as aulas decorrem em setembro"
    )
    if latest_status == "failed":
        response = client.post(
            f"/api/v1/documents/{document['id']}/versions",
            files={"file": ("bad.txt", b"\xff\xfe invalid", "text/plain")},
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["processing_status"] == "failed"
    else:
        newer = _upload(
            client, headers, document["id"], b"conteudo posterior distinto"
        )
        session = test_session_factory()
        try:
            stored = session.get(DocumentVersion, uuid.UUID(newer["id"]))
            assert stored is not None
            stored.processing_status = latest_status
            session.commit()
        finally:
            session.close()

    items = _search(client, headers, FALLBACK_QUESTION).json()["items"]
    assert [item["document_version_id"] for item in items] == [processed["id"]]


def test_fallback_ties_have_deterministic_secondary_order(client: TestClient) -> None:
    """Três documentos com correspondência idêntica ("aulas" e "setembro"
    uma vez em conteúdos do mesmo comprimento) produzem scores empatados na
    variante disjuntiva: a ordenação secundária por document_id tem de ser
    estável entre execuções."""
    _, headers, _ = _setup(client)
    for suffix in ("alfa", "beta", "gama"):
        _create_searchable(
            client,
            headers,
            f"as aulas {suffix} decorrem em setembro",
            title=f"Curso {suffix}",
        )

    first = _search(client, headers, FALLBACK_QUESTION).json()["items"]
    second = _search(client, headers, FALLBACK_QUESTION).json()["items"]
    assert len(first) == 3
    assert [item["chunk_id"] for item in first] == [item["chunk_id"] for item in second]

    scores = [item["score"] for item in first]
    assert scores == sorted(scores, reverse=True)
    for previous, current in zip(first, first[1:], strict=False):
        if previous["score"] == current["score"]:
            assert previous["document_id"] < current["document_id"]


def test_fallback_respects_language_isolation(client: TestClient) -> None:
    """Documentos concorrentes em idiomas diferentes: o fallback pesquisa
    apenas o idioma resolvido, mesmo quando o termo aparece em ambos."""
    _, headers, _ = _setup(client)
    portuguese, _ = _create_searchable(
        client, headers, "As aulas decorrem em setembro.", title="PT"
    )
    english, _ = _create_searchable(
        client,
        headers,
        "The aulas timetable begins in setembro.",
        title="EN",
        language="en",
    )

    pt_items = _search(client, headers, FALLBACK_QUESTION, language="pt").json()["items"]
    assert [item["document_id"] for item in pt_items] == [portuguese["id"]]

    en_items = _search(
        client, headers, "When do the aulas begin in setembro?", language="en"
    ).json()["items"]
    assert [item["document_id"] for item in en_items] == [english["id"]]
