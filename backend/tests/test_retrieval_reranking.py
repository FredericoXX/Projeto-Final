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


def test_ordinal_only_query_is_never_expanded_to_a_cardinal(
    client: TestClient,
) -> None:
    """Regressão negativa: "primeira", sozinha, não pode ser expandida para
    o dígito "1". Se fosse, recuperaria "Sala 1" — uma sala qualquer — como
    se fosse a primeira chamada."""
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "Sala 1 disponível para reuniões.", title="Salas")
    assert _search(client, headers, "primeira").json()["items"] == []


def test_second_ordinal_only_query_does_not_match_room_two(
    client: TestClient,
) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "Sala 2 disponível para reuniões.", title="Salas")
    assert _search(client, headers, "segunda").json()["items"] == []


def test_contextual_ordinal_query_still_retrieves_numeric_form(
    client: TestClient,
) -> None:
    """Com contexto, a relaxação canónica recupera a forma numérica: a
    pergunta usa "primeira", o documento usa "1.ª"."""
    _, headers, _ = _setup(client)
    _create_searchable(
        client, headers, "Exames da 1.ª chamada | 1 a 12 de fevereiro de 2031", title="Exames"
    )
    items = _search(client, headers, "exames primeira chamada").json()["items"]
    assert items
    assert "1.ª" in items[0]["content"]


def test_cardinal_twelve_never_matches_the_first_ordinal(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "Exames da 12 chamada | 3 de março", title="OCR")
    # O contexto ("exames", "chamada") pode recuperar a linha, mas nunca
    # porque "12" seria "primeira".
    items = _search(client, headers, "primeira").json()["items"]
    assert items == []


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


def test_candidate_pool_respects_the_global_budget(
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
    # Orçamento global = min(100, max(20, 5*5)) = 25, decidido antes das
    # consultas e repartido pelas variantes ativas.
    assert trace.global_candidate_limit == 25
    assert trace.global_candidate_limit <= CANDIDATE_MAX
    assert sum(variant.quota for variant in trace.variants) <= trace.global_candidate_limit
    assert trace.unique_after_dedup <= trace.global_candidate_limit


def test_four_variants_share_the_global_budget(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """Uma pergunta com ordinal planeia as quatro variantes: a soma das
    quotas — e das linhas devolvidas por SQL — nunca excede o orçamento."""
    institution, headers, _ = _setup(client)
    for index in range(40):
        _create_searchable(
            client, headers, f"Exames da 1.ª chamada numero {index} | detalhes"
        )
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        _evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("Quando são os exames da primeira chamada?"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    assert len(trace.planned_variants) == 4
    assert "canonical_relaxed_and" in trace.planned_variants
    quotas = [variant.quota for variant in trace.variants]
    assert sum(quotas) <= trace.global_candidate_limit
    assert all(quota > 0 for quota in quotas)
    for variant in trace.variants:
        assert variant.returned_count <= variant.quota
    assert trace.total_returned_before_dedup == sum(
        variant.returned_count for variant in trace.variants
    )
    assert trace.unique_after_dedup <= trace.global_candidate_limit


def test_total_rows_fetched_never_exceed_the_global_budget(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O orçamento é **global**, não por variante — a diferença observável.

    Cenário: 30 documentos que correspondem às **quatro** variantes, pelo
    que todas saturam a sua quota. Com `top_k=5` o orçamento global é 25 e
    as quotas somam 25, logo o SQL nunca devolve mais do que 25 linhas no
    total.

    Na arquitetura anterior cada variante recebia o limite inteiro
    (`candidate_limit = 25`), o que daria `4 × 25 = 100` linhas — abaixo do
    antigo teto global de 100, pelo que nem sequer seria cortado. É esta
    contagem, e não a presença de um candidato, que separa os dois desenhos.
    """
    institution, headers, _ = _setup(client)
    # O texto usa a forma escrita ("primeira") para que a variante exact e a
    # reduced_and também correspondam; sem isso só as relaxadas saturariam.
    for index in range(30):
        _create_searchable(
            client,
            headers,
            f"Exames da primeira chamada numero {index} | detalhes",
            title=f"Chamada {index}",
        )
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        # A pergunta evita stopwords acentuadas: normalize_text remove os
        # acentos, e "são" deixa de casar a stopword portuguesa, passando a
        # ser um termo obrigatório que nenhum documento contém — a variante
        # exact não recuperaria nada e não saturaria a quota.
        _evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("exames da primeira chamada"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    assert len(trace.variants) == 4
    assert trace.global_candidate_limit == 25
    # Todas as quotas ficam saturadas: os limites SQL estão mesmo a atuar.
    for variant in trace.variants:
        assert variant.returned_count == variant.quota, variant.strategy

    # A asserção decisiva: o total agregado respeita o orçamento global.
    assert trace.total_returned_before_dedup == 25
    assert trace.total_returned_before_dedup <= trace.global_candidate_limit
    # O desenho anterior teria trazido 4 × 25 = 100 linhas.
    old_per_variant_total = len(trace.variants) * trace.global_candidate_limit
    assert trace.total_returned_before_dedup < old_per_variant_total
    # E nada se perde entre o SQL e a avaliação.
    assert trace.candidates_evaluated == trace.unique_after_dedup


def test_exact_variant_quota_is_reserved_against_higher_fts_candidates(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """A quota da variante exact é **reservada**: um candidato exact com
    ts_rank_cd baixo não compete por espaço com candidatos de uma variante
    menos prioritária, por muito mais alto que seja o FTS destes.

    Antes, cada variante recebia o limite inteiro e o pool agregado era
    depois cortado por FTS cru — era aí que um exact fraco podia perder o
    lugar para um reduced_or forte.
    """
    institution, headers, _ = _setup(client)
    # Alvo: único documento que contém "especial", logo o único recuperado
    # pela variante exact. Conteúdo longo com uma só ocorrência de cada
    # termo ⇒ ts_rank_cd baixo.
    target, _ = _create_searchable(
        client,
        headers,
        "O periodo de exames especial decorre em janeiro. "
        + "Texto institucional de enchimento sem termos procurados. " * 40,
        title="Exames Especial",
    )
    # Concorrentes: só correspondem à variante disjuntiva, mas repetem os
    # termos em conteúdo curto ⇒ ts_rank_cd muito mais alto.
    for index in range(30):
        _create_searchable(
            client,
            headers,
            f"periodo periodo exames exames periodo exames {index}",
            title=f"Concorrente {index}",
        )
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        _evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("periodo exames especial"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    quotas = {variant.strategy: variant.quota for variant in trace.variants}
    assert quotas["exact"] > 0

    # O alvo foi avaliado e, com cobertura 3/3 contra 2/3, ficou em primeiro.
    assert trace.results, "o candidato exact tem de chegar ao reranker"
    assert trace.results[0].document_id == str(target["id"])
    assert trace.results[0].coverage == 1.0

    # E fê-lo apesar de ter o pior ts_rank_cd **entre os resultados
    # devolvidos** — `trace.results` está limitado ao top_k, por isso a
    # comparação não se estende a todos os avaliados. Basta para mostrar que
    # não foi a força do FTS que o pôs em primeiro.
    other_raw_scores = [result.raw_score for result in trace.results[1:]]
    assert other_raw_scores, "o cenário precisa de concorrentes devolvidos"
    assert trace.results[0].raw_score < min(other_raw_scores)

    # Nada desaparece entre o SQL e a avaliação: não há corte pós-agregação.
    assert trace.candidates_evaluated == trace.unique_after_dedup


def test_partial_coverage_candidate_is_excluded_by_coverage_not_threshold(
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
    # O documento de matrícula cobre 1 de 2 termos: é removido por cobertura
    # insuficiente — uma causa tipada, distinta do limiar.
    assert trace.excluded_insufficient_coverage >= 1
    assert any(
        excluded.reason == "insufficient_coverage" for excluded in trace.excluded
    )


def test_trace_counts_are_mathematically_consistent(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers = _setup_calendar(client)
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        _evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("Até quando posso mudar o regime de avaliação?"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    assert sum(variant.quota for variant in trace.variants) <= trace.global_candidate_limit
    assert trace.total_returned_before_dedup == sum(
        variant.returned_count for variant in trace.variants
    )
    assert trace.unique_after_dedup <= trace.total_returned_before_dedup
    assert trace.candidates_evaluated == trace.unique_after_dedup
    assert trace.candidates_evaluated == (
        trace.final_result_count
        + trace.excluded_no_content_match
        + trace.excluded_insufficient_coverage
        + trace.excluded_below_threshold
    )
    # O top_k não é uma exclusão de relevância.
    assert len(trace.results) <= trace.final_result_count


def test_trace_never_contains_document_content(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers = _setup_calendar(client)
    from app.core.text_normalization import normalize_text

    retriever = PostgresLexicalRetriever()
    with test_session_factory() as db:
        _evidence, trace = retriever.search_with_trace(
            db,
            normalize_text("Até quando posso mudar o regime de avaliação?"),
            _context(institution["id"]),
            top_k=5,
            official_only=True,
        )
    rendered = repr(trace)
    for forbidden in ("Mudança do regime", "novembro", "Calendário Institucional"):
        assert forbidden not in rendered


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


# --- Intervalos canónicos posicionais ----------------------------------------

RANGE_DOC = "Período de inscrições | 1 a 12 de outubro de 2030"
NEIGHBOUR_RANGE_DOC = "Período de inscrições | 1 a 13 de novembro de 2030"


def test_compact_range_query_retrieves_spaced_content(client: TestClient) -> None:
    """"01a12" na pergunta recupera "1 a 12" no conteúdo através do
    contexto (relaxação canónica) e do marcador canónico."""
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, RANGE_DOC, title="Inscrições")
    items = _search(client, headers, "Qual é o período de inscrições de 01a12?").json()[
        "items"
    ]
    assert items
    assert "1 a 12" in items[0]["content"]


def test_hyphen_range_query_retrieves_spaced_content(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, RANGE_DOC, title="Inscrições")
    items = _search(client, headers, "período de inscrições de 01-12").json()["items"]
    assert items
    assert "1 a 12" in items[0]["content"]


def test_correct_range_outranks_neighbouring_range(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    correct, _ = _create_searchable(client, headers, RANGE_DOC, title="Outubro")
    _create_searchable(client, headers, NEIGHBOUR_RANGE_DOC, title="Novembro")
    items = _search(client, headers, "período de inscrições de 01a12").json()["items"]
    assert items[0]["document_id"] == correct["id"]


def test_number_run_does_not_match_a_range_in_retrieval(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """"0509" continua ambíguo: nunca é lido como o intervalo 5 a 9."""
    institution, headers, _ = _setup(client)
    _create_searchable(
        client, headers, "Semana institucional | 5 a 9 de outubro de 2030", title="Semana"
    )
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
    assert trace.query_ranges == ()
    assert all("rng:5-9" not in result.matched_terms for result in trace.results)


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
