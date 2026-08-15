"""Propriedades da projeção de termos usada pelo experimento D4.3.

Testes de unidade puros: não tocam na base de dados nem no retriever. O que
fixam é que a variante altera **apenas** o predicado de correspondência e que
não pode, por construção, perder correspondências que a baseline tinha.
"""

from uuid import uuid4

from app.core.text_normalization import normalize_text
from app.evaluation.lexical_variants import (
    MATCHING_EXACT_CANONICAL,
    MATCHING_STEM_NORMALIZED,
    TermProjection,
    identity_projection,
    project_terms,
    projected_content_set,
    projected_positions,
    variant_content_match,
)
from app.retrieval.eligibility import ContentMatch
from app.retrieval.lexical_normalization import (
    LexicalRepresentation,
    build_lexical_representation,
)
from app.retrieval.query_planning import LexicalQueryStrategy
from app.retrieval.reranking import LexicalCandidate, compute_content_match


def lexical_candidate(*, normalized_content: str) -> LexicalCandidate:
    """Candidato mínimo: só o conteúdo importa para estes testes."""
    return LexicalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        document_title="Documento",
        chunk_index=0,
        content=normalized_content,
        normalized_content=normalize_text(normalized_content),
        language="pt",
        official_source=True,
        source_url=None,
        valid_from=None,
        valid_until=None,
        page_number=None,
        section_title=None,
        structure_type=None,
        chunking_strategy=None,
        raw_score=0.05,
        strategy=LexicalQueryStrategy.REDUCED_OR,
    )


def _representation(text: str) -> LexicalRepresentation:
    return build_lexical_representation(text, "pt")


def test_identity_projection_maps_every_term_to_itself() -> None:
    projection = identity_projection()
    assert projection.name == MATCHING_EXACT_CANONICAL
    assert project_terms(("matricula", "prazo"), projection) == ("matricula", "prazo")


def test_projection_falls_back_to_the_term_when_absent_from_the_mapping() -> None:
    """Um termo desconhecido tem de continuar a corresponder por igualdade.

    É esta propriedade que garante que nenhuma variante pode perder uma
    correspondência que a baseline tinha: na pior das hipóteses comporta-se
    como a identidade.
    """
    projection = TermProjection(
        name=MATCHING_STEM_NORMALIZED,
        query_mapping={"aulas": "aul"},
        content_mapping={"aulas": "aul"},
    )
    assert projection.project_query("aulas") == "aul"
    assert projection.project_query("matricula") == "matricula"


def test_canonical_markers_are_never_projected() -> None:
    """``ord:2`` identifica um ordinal normalizado, não é palavra a radicalizar."""
    projection = TermProjection(
        name=MATCHING_STEM_NORMALIZED,
        query_mapping={"ord:2": "ord", "semestre": "semestr"},
        content_mapping={"ord:2": "ord", "semestre": "semestr"},
    )
    assert projection.project_query("ord:2") == "ord:2"
    assert projection.project_content("ord:2") == "ord:2"
    assert projection.project_content("semestre") == "semestr"


def test_projected_content_set_collapses_inflections() -> None:
    representation = _representation("as residencias estudantis da universidade")
    projection = TermProjection(
        name=MATCHING_STEM_NORMALIZED,
        query_mapping={"residencias": "residenc", "residencia": "residenc"},
        content_mapping={"residencias": "residenc", "residencia": "residenc"},
    )
    assert "residenc" in projected_content_set(representation, projection)
    assert "residencia" not in projected_content_set(representation, projection)


def test_projected_positions_keep_the_first_occurrence() -> None:
    representation = _representation("prazo de matricula e prazo de inscricao")
    projection = identity_projection()
    positions = projected_positions(representation, projection)
    assert positions["prazo"] == 0


def test_variant_match_recovers_an_inflected_term() -> None:
    """O caso Q009: a pergunta traz o singular, o segmento traz o plural."""
    candidate = lexical_candidate(
        normalized_content="a candidatura as residencias estudantis",
    )
    query_terms = ("candidato", "residencia")
    base = compute_content_match(query_terms, candidate)
    assert base.matched_terms == frozenset()

    projection = TermProjection(
        name=MATCHING_STEM_NORMALIZED,
        query_mapping={
            "residencia": "residenc",
            "residencias": "residenc",
            "candidato": "candidat",
            "candidatura": "candidatur",
        },
        content_mapping={
            "residencia": "residenc",
            "residencias": "residenc",
            "candidato": "candidat",
            "candidatura": "candidatur",
        },
    )
    match = variant_content_match(
        base=base,
        query_terms=query_terms,
        representation=_representation(candidate.normalized_content),
        projection=projection,
    )
    assert match.matched_terms == frozenset({"residencia"})
    assert match.coverage == 0.5


def test_variant_match_returns_terms_in_the_original_space() -> None:
    """``matched_terms`` tem de continuar comparável com ``query_terms``.

    ``decide_eligibility`` compara os dois conjuntos; devolver radicais faria a
    comparação falhar em silêncio em vez de dar erro.
    """
    candidate = lexical_candidate(normalized_content="as residencias estudantis")
    query_terms = ("residencia",)
    projection = TermProjection(
        name=MATCHING_STEM_NORMALIZED,
        query_mapping={"residencia": "residenc", "residencias": "residenc"},
        content_mapping={"residencia": "residenc", "residencias": "residenc"},
    )
    match = variant_content_match(
        base=compute_content_match(query_terms, candidate),
        query_terms=query_terms,
        representation=_representation(candidate.normalized_content),
        projection=projection,
    )
    assert match.matched_terms <= set(query_terms)


def test_identity_variant_reproduces_the_production_match() -> None:
    """A célula de controlo do experimento não pode divergir de produção."""
    candidate = lexical_candidate(
        normalized_content="o prazo de matricula termina em outubro",
    )
    query_terms = ("prazo", "matricula", "inscricao")
    base = compute_content_match(query_terms, candidate)
    match = variant_content_match(
        base=base,
        query_terms=query_terms,
        representation=_representation(candidate.normalized_content),
        projection=identity_projection(),
    )
    assert match.matched_terms == base.matched_terms
    assert match.coverage == base.coverage
    assert match.proximity == base.proximity
    assert match.compactness == base.compactness


def test_empty_query_returns_the_base_match_unchanged() -> None:
    candidate = lexical_candidate(normalized_content="texto qualquer")
    base = ContentMatch(
        coverage=0.0,
        matched_terms=frozenset(),
        exact_phrase=0.0,
        ordered=0.0,
        proximity=0.0,
        compactness=0.0,
    )
    match = variant_content_match(
        base=base,
        query_terms=(),
        representation=_representation(candidate.normalized_content),
        projection=identity_projection(),
    )
    assert match is base


def test_exact_phrase_and_ordered_are_held_constant() -> None:
    """Sinais deliberadamente não recalculados no espaço projetado.

    Recalculá-los faria uma variante ganhar por dois mecanismos ao mesmo tempo,
    e o experimento não conseguiria atribuir o efeito a um só.
    """
    candidate = lexical_candidate(normalized_content="as residencias estudantis")
    query_terms = ("residencia", "estudantil")
    base = compute_content_match(query_terms, candidate)
    projection = TermProjection(
        name=MATCHING_STEM_NORMALIZED,
        query_mapping={
            "residencia": "residenc",
            "residencias": "residenc",
            "estudantil": "estudant",
            "estudantis": "estudant",
        },
        content_mapping={
            "residencia": "residenc",
            "residencias": "residenc",
            "estudantil": "estudant",
            "estudantis": "estudant",
        },
    )
    match = variant_content_match(
        base=base,
        query_terms=query_terms,
        representation=_representation(candidate.normalized_content),
        projection=projection,
    )
    assert match.exact_phrase == base.exact_phrase
    assert match.ordered == base.ordered
    assert match.coverage > base.coverage
