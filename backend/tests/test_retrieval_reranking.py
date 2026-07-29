"""Integração do reranking lexical determinístico com PostgreSQL real.

Cobre o caso principal de regressão do Momento 4 (uma table_row curta e
coberta deve vencer parágrafos genéricos que apenas repetem termos), a
agregação de variantes num candidate pool limitado, o limiar de
relevância, o benefício condicionado de table_row, os ordinais padrão e os
testes negativos de OCR (nenhuma inferência inventada). Todos os dados são
sintéticos e usam os anos 2030/2031 — nunca o calendário real.

Reutiliza os helpers de ``tests.test_retrieval``.
"""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.retrieval.base import RetrievalContext
from app.retrieval.lexical import CANDIDATE_MAX, PostgresLexicalRetriever
from tests.test_retrieval import (
    _create_searchable,
    _search,
    _setup,
)

# --- Documentos sintéticos ---------------------------------------------------

# Documento A — calendário institucional com linhas de tabela ("... | ...").
CALENDAR_A = """Calendário Institucional 2030/2031

Mudança do regime de avaliação | Até 6 de novembro de 2030
Primeiro dia de aulas | 5 de outubro de 2030
Exames da 1.ª chamada | 1 a 12 de fevereiro de 2031
Exames da 2.ª chamada | 22 de fevereiro a 6 de março de 2031
"""

# Documento B — manual genérico que repete "regime" e "avaliação" muitas
# vezes, sem a data procurada (competidor de cobertura igual à table_row).
MANUAL_B = (
    "Manual genérico de avaliação. O regime de avaliação dos estudantes está "
    "definido no regulamento académico interno. A avaliação contínua e o "
    "regime de exame aplicam-se a todos os estudantes inscritos. O regime de "
    "avaliação pode incluir exame final ou avaliação distribuída. Este manual "
    "descreve o regime de avaliação em geral, o regime de frequência e a "
    "avaliação por competências, sem indicar quaisquer datas específicas."
)

# Documento C — relatório sobre assistentes virtuais, com termos genéricos
# ("avaliação", "regime", "sistema", "instituição") sem relação com o evento.
ASSISTANT_C = (
    "Relatório sobre assistentes virtuais. O sistema de avaliação automática "
    "do assistente virtual analisa o regime de funcionamento da instituição. "
    "A avaliação do sistema segue o regime técnico definido pela instituição. "
    "O assistente virtual não substitui a avaliação institucional nem o "
    "regime de decisão humana, e o sistema mantém um registo de avaliação "
    "contínua do próprio regime de operação."
)


def _context(institution_id: str, language: str = "pt") -> RetrievalContext:
    return RetrievalContext(
        institution_id=uuid.UUID(institution_id),
        language=language,
        reference_date=datetime.now(UTC).date(),
    )


def _setup_calendar(client: TestClient) -> tuple[dict, dict[str, str]]:
    institution, headers, _ = _setup(client)
    _create_searchable(client, headers, CALENDAR_A, title="Calendário Institucional 2030/2031")
    _create_searchable(client, headers, MANUAL_B, title="Manual de Avaliação")
    _create_searchable(client, headers, ASSISTANT_C, title="Assistente Virtual")
    return institution, headers


# --- Caso principal de regressão (secção 37) ---------------------------------


def test_change_of_assessment_regime_table_row_ranks_first(client: TestClient) -> None:
    _, headers = _setup_calendar(client)
    items = _search(client, headers, "Até quando posso mudar o regime de avaliação?").json()[
        "items"
    ]
    assert items, "a evidência correta deve ser recuperada"
    top = items[0]
    assert "Mudança do regime de avaliação" in top["content"]
    assert "6 de novembro de 2030" in top["content"]
    assert top["document_title"] == "Calendário Institucional 2030/2031"
    # Nenhum parágrafo genérico fica acima da evidência direta.
    assert "assistente virtual" not in top["content"].lower()


def test_generic_documents_do_not_outrank_direct_evidence(client: TestClient) -> None:
    _, headers = _setup_calendar(client)
    items = _search(client, headers, "Até quando posso mudar o regime de avaliação?").json()[
        "items"
    ]
    # O melhor score pertence à table_row curta e direta.
    assert items[0]["score"] == max(item["score"] for item in items)
    assert "Mudança do regime de avaliação" in items[0]["content"]
    # Se documentos genéricos aparecerem, aparecem sempre abaixo.
    for item in items[1:]:
        assert "Mudança do regime de avaliação" not in item["content"]


def test_additional_calendar_questions_prefer_correct_row(client: TestClient) -> None:
    _, headers = _setup_calendar(client)
    cases = {
        "Quando começa o primeiro dia de aulas?": "Primeiro dia de aulas",
        "Quando são os exames da primeira chamada?": "Exames da 1.ª chamada",
        "Quando são os exames da 1.ª chamada?": "Exames da 1.ª chamada",
        "Quando são os exames da segunda chamada?": "Exames da 2.ª chamada",
        "Quando são os exames da 2.º chamada?": "Exames da 2.ª chamada",
    }
    for question, expected_row in cases.items():
        items = _search(client, headers, question).json()["items"]
        assert items, f"sem resultados para {question!r}"
        assert expected_row in items[0]["content"], (
            f"esperava {expected_row!r} em topo para {question!r}, "
            f"veio {items[0]['content']!r}"
        )


def test_ordinal_distinguishes_first_from_second_chamada(client: TestClient) -> None:
    _, headers = _setup_calendar(client)
    first = _search(client, headers, "exames primeira chamada").json()["items"]
    second = _search(client, headers, "exames segunda chamada").json()["items"]
    assert "Exames da 1.ª chamada" in first[0]["content"]
    assert "Exames da 2.ª chamada" in second[0]["content"]


# --- Trace, candidate pool e limiar (secções 19, 25, 30) ---------------------


def test_trace_reports_ranking_signals_for_change_question(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers = _setup_calendar(client)
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("Até quando posso mudar o regime de avaliação?"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    assert trace.fts_config == "portuguese"
    assert set(trace.informative_terms) == {"mudar", "regime", "avaliacao"}
    # A table_row correta é o primeiro resultado do trace e tem cobertura alta.
    assert evidence
    assert trace.results[0].structure_type == "table_row"
    assert trace.results[0].coverage >= 0.66
    assert {"regime", "avaliacao"} <= set(trace.results[0].matched_terms)


def test_candidate_pool_is_limited_and_deduplicated(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers, _ = _setup(client)
    # Muitos documentos com o mesmo termo genérico.
    for index in range(40):
        _create_searchable(client, headers, f"avaliacao institucional numero {index}")
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        _evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("avaliacao"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    # candidate_limit = min(MAX, max(20, 5*5)) = 25.
    assert trace.candidate_limit == 25
    assert trace.unique_candidate_count <= CANDIDATE_MAX
    assert trace.unique_candidate_count <= 25


def test_threshold_removes_weak_partial_generic_match(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers, _ = _setup(client)
    _create_searchable(
        client, headers, "O período de exames decorre de 11 a 29 de janeiro.", title="Exames"
    )
    _create_searchable(
        client, headers, "O período de matrícula decorre em setembro.", title="Matrícula"
    )
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("Qual é o período dos exames?"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    titles = [ev.document_title for ev in evidence]
    assert titles == ["Exames"]
    # O documento de matrícula (só cobre "periodo") é removido por dominância.
    assert trace.removed_by_threshold >= 1


# --- Benefício condicionado de table_row (secção 24) -------------------------


def test_table_row_does_not_beat_paragraph_with_higher_coverage(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    # Parágrafo com cobertura total dos três termos.
    paragraph, _ = _create_searchable(
        client,
        headers,
        "O período de exames finais de matemática decorre em janeiro para todos.",
        title="Parágrafo",
    )
    # table_row que só cobre dois dos três termos.
    _create_searchable(
        client, headers, "Exames de matemática | Sala 3", title="Tabela"
    )
    items = _search(client, headers, "período exames matemática").json()["items"]
    assert items[0]["document_id"] == paragraph["id"]


# --- Testes negativos de OCR (secção 38) -------------------------------------

OCR_DOC = """Calendário com erros de OCR 2030/2031

Exames da 12 chamada | 1 a 12 de fevereiro de 2031
Semana institucional | 0509 de outubro de 2030
"""


def test_ocr_cardinal_is_not_treated_as_ordinal(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers, _ = _setup(client)
    _create_searchable(client, headers, OCR_DOC, title="OCR")
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("exames da primeira chamada"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    # A pergunta reconhece o ordinal 1; o conteúdo "12 chamada" não.
    assert 1 in trace.query_ordinals
    # O chunk pode ser recuperado pelos termos restantes (exames/chamada),
    # mas "ord:1" nunca é dado como correspondido a partir de "12".
    matched_ord1 = any("ord:1" in result.matched_terms for result in trace.results)
    assert not matched_ord1
    # O sistema não inventa a evidência: encontra por termos reais, sem
    # afirmar que "12" é o primeiro.
    assert evidence


def test_ocr_number_run_is_not_split_into_range(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers, _ = _setup(client)
    _create_searchable(client, headers, OCR_DOC, title="OCR")
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        _evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("semana institucional 0509"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    # "0509" não é reconhecido como intervalo em lado nenhum.
    assert trace.query_ranges == ()


# --- Consulta de um único termo continua funcional (secção 25.1) -------------


def test_single_term_query_still_works(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "O prazo de matrícula termina em setembro.")
    items = _search(client, headers, "matricula").json()["items"]
    assert len(items) == 1


# --- Configuração FTS por idioma / stemming (secção 36, itens 1-8) -----------


def test_portuguese_plural_stemming_retrieves_singular(client: TestClient) -> None:
    """A configuração portuguese unifica singular/plural: "matriculas"
    recupera conteúdo que só contém "matrícula"."""
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "Informação sobre a matrícula anual.")
    assert _search(client, headers, "matriculas").json()["items"]


def test_portuguese_verb_conjugation_stemming(client: TestClient) -> None:
    """Conjugações verbais colapsam no mesmo stem (começa ~ começam)."""
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "O atendimento começa em setembro.")
    assert _search(client, headers, "quando começam?").json()["items"]


def test_english_stemming_retrieves_related_form(client: TestClient) -> None:
    """A configuração english aplica stemming inglês."""
    _, headers, _ = _setup(client)
    _create_searchable(
        client,
        headers,
        "Enrollment deadline for international students.",
        language="en",
        title="Enrollment",
    )
    assert _search(client, headers, "enrollments", language="en").json()["items"]


def test_accents_remain_compatible_under_portuguese(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "Período de avaliação académica.")
    assert _search(client, headers, "avaliacao").json()["items"]
    assert _search(client, headers, "avaliação").json()["items"]


# --- Privacidade dos logs (secção 41) ----------------------------------------


def test_retrieval_logs_only_controlled_metadata(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """O log do retrieval contém apenas metadados controlados — nunca a
    pergunta, os termos extraídos ou o conteúdo dos chunks.

    Usa um handler próprio anexado diretamente ao logger do retriever (em
    vez de caplog), para ser imune ao estado global de logging deixado por
    outros testes da suite.
    """
    import logging

    from app.core.text_normalization import normalize_text

    institution, _ = _setup_calendar(client)

    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("app.retrieval.lexical")
    handler = _Collector()
    handler.setLevel(logging.INFO)
    previous_level = logger.level
    previous_disabled = logger.disabled
    previous_disable = logging.Logger.manager.disable
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Outros testes da suite (ex.: as migrações via fileConfig do Alembic,
    # com disable_existing_loggers=True) podem deixar este logger desativado
    # ou o logging globalmente inibido; forçamos a captura de forma isolada.
    logger.disabled = False
    logging.disable(logging.NOTSET)
    try:
        retriever = PostgresLexicalRetriever()
        with test_session_factory() as db:
            retriever.search_with_trace(
                db,
                normalize_text("Até quando posso mudar o regime de avaliação?"),
                _context(institution["id"]),
                top_k=5,
                official_only=True,
            )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.disabled = previous_disabled
        logging.disable(previous_disable)

    messages = " ".join(record.getMessage() for record in records)
    assert messages, "o retrieval deve registar metadados operacionais"
    assert "portuguese" in messages  # config FTS allowlisted é permitida
    for forbidden in ("mudar", "regime", "avaliacao", "novembro", "mudanca"):
        assert forbidden not in messages
