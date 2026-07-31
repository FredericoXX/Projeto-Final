"""Testes da normalização lexical de retrieval e da configuração FTS.

Camada pura, sem base de dados (ver app.retrieval.lexical_normalization e
app.retrieval.fts_config). A camada recebe texto já normalizado por
``normalize_text`` e produz tokens canónicos, ordinais e intervalos; nunca
altera o texto de entrada.
"""

from app.core.text_normalization import normalize_text
from app.retrieval.fts_config import FtsConfiguration, resolve_fts_config
from app.retrieval.lexical_normalization import (
    TokenKind,
    build_lexical_representation,
)
from app.retrieval.reranking import informative_query_terms


def _canon(text: str, language: str = "pt") -> list[str]:
    return list(build_lexical_representation(normalize_text(text), language).canonical_stream)


def _positions(text: str, language: str = "pt") -> dict[str, int]:
    return build_lexical_representation(normalize_text(text), language).first_positions()


def _ordinals(text: str, language: str = "pt") -> list[int]:
    representation = build_lexical_representation(normalize_text(text), language)
    return [token.ordinal for token in representation.tokens if token.ordinal is not None]


def _ranges(text: str, language: str = "pt") -> list[str]:
    representation = build_lexical_representation(normalize_text(text), language)
    return [numeric_range.canonical for numeric_range in representation.ranges]


# --- 1-5: acentos, casefold, espaços, Unicode, pontuação ---------------------


def test_accents_are_removed_upstream() -> None:
    assert _canon("Avaliação") == ["avaliacao"]


def test_casefold_applied_upstream() -> None:
    assert _canon("REGIME De AVALIAÇÃO") == ["regime", "de", "avaliacao"]


def test_whitespace_is_collapsed() -> None:
    assert _canon("regime   \n  avaliacao") == ["regime", "avaliacao"]


def test_unicode_non_latin_is_preserved() -> None:
    assert _canon("Πανεπιστήμιο aulas") == ["πανεπιστημιο", "aulas"]


def test_punctuation_splits_tokens() -> None:
    assert _canon("aulas, exames; biblioteca!") == ["aulas", "exames", "biblioteca"]


# --- 6-12: idiomas e configuração FTS ----------------------------------------


def test_fts_config_portuguese_family() -> None:
    for code in ("pt", "pt-pt", "pt-br", "PT_pt"):
        assert resolve_fts_config(code) is FtsConfiguration.PORTUGUESE


def test_fts_config_english_family() -> None:
    for code in ("en", "en-gb", "en-us", "EN_US"):
        assert resolve_fts_config(code) is FtsConfiguration.ENGLISH


def test_fts_config_unknown_language_uses_simple() -> None:
    for code in ("fr", "de", "zz", "es-es"):
        assert resolve_fts_config(code) is FtsConfiguration.SIMPLE


def test_ordinal_family_applies_by_primary_subtag() -> None:
    assert _ordinals("primeira", "pt-pt") == [1]
    assert _ordinals("primeira", "pt-br") == [1]
    assert _ordinals("first", "en-gb") == [1]
    assert _ordinals("first", "en-us") == [1]
    # Idioma sem família não canoniza ordinais escritos.
    assert _ordinals("primeira", "fr") == []


# --- 13-27: ordinais padrão --------------------------------------------------


def test_numeric_ordinal_variants_pt() -> None:
    for text in ("1.º", "1º", "1.ª", "1ª", "1o", "1a"):
        assert _ordinals(text) == [1], text
    for text in ("2.º", "2º", "2.ª", "2ª", "2o", "2a"):
        assert _ordinals(text) == [2], text


def test_written_ordinal_variants_pt() -> None:
    assert _ordinals("primeiro") == [1]
    assert _ordinals("primeira") == [1]
    assert _ordinals("segundo") == [2]
    assert _ordinals("segunda") == [2]


def test_additional_written_ordinals_pt() -> None:
    expected = {
        "terceiro": 3, "quarta": 4, "quinto": 5, "sexta": 6,
        "setimo": 7, "oitava": 8, "nono": 9, "decima": 10,
    }
    for word, value in expected.items():
        assert _ordinals(word) == [value], word


def test_additional_written_ordinals_en() -> None:
    expected = {
        "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
        "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    }
    for word, value in expected.items():
        assert _ordinals(word, "en") == [value], word


def test_english_numeric_ordinals() -> None:
    assert _ordinals("1st", "en") == [1]
    assert _ordinals("2nd", "en") == [2]
    assert _ordinals("10th", "en") == [10]


def test_ordinal_canonical_matches_across_variants() -> None:
    # "1.ª" e "primeira" produzem a mesma forma canónica.
    numeric = build_lexical_representation(normalize_text("1.ª"), "pt").canonical_stream
    written = build_lexical_representation(normalize_text("primeira"), "pt").canonical_stream
    assert numeric == written == ("ord:1",)


# --- 28-30: cardinais nunca viram ordinais por suposição ---------------------


def test_cardinal_numbers_are_not_ordinals() -> None:
    assert _ordinals("12") == []
    assert _canon("12") == ["12"]


def test_twelve_does_not_mean_first() -> None:
    representation = build_lexical_representation(normalize_text("12 chamada"), "pt")
    assert [token.canonical for token in representation.tokens] == ["12", "chamada"]
    assert _ordinals("12 chamada") == []


def test_twentytwo_does_not_mean_second() -> None:
    assert _ordinals("22 de fevereiro") == []
    assert "22" in _canon("22 de fevereiro")


# --- 31-35: intervalos numéricos explícitos ----------------------------------


def test_explicit_range_no_spaces() -> None:
    assert _ranges("01a12") == ["rng:1-12"]


def test_explicit_range_with_preposition() -> None:
    assert _ranges("01 a 12") == ["rng:1-12"]


def test_explicit_range_with_hyphen_and_dash() -> None:
    assert _ranges("01-12") == ["rng:1-12"]
    assert _ranges("01–12") == ["rng:1-12"]


def test_number_run_without_separator_is_not_split() -> None:
    assert _ranges("0509") == []
    assert _canon("0509") == ["0509"]
    assert _ranges("2206") == []
    assert _canon("2206") == ["2206"]
    assert _ranges("20262027") == []
    assert _canon("20262027") == ["20262027"]


# --- Intervalo como unidade posicional única ---------------------------------


def test_range_is_a_single_unit_in_the_canonical_stream() -> None:
    # O marcador substitui o intervalo no stream: "período | 1 a 12 |
    # inscrições" tem exatamente três unidades informativas.
    assert _canon("periodo 1 a 12 inscricoes") == [
        "periodo",
        "rng:1-12",
        "inscricoes",
    ]


def test_all_range_forms_share_the_same_canonical_stream() -> None:
    streams = {
        tuple(_canon(f"periodo {form} inscricoes"))
        for form in ("01a12", "01 a 12", "01-12", "01–12", "1 a 12")
    }
    assert streams == {("periodo", "rng:1-12", "inscricoes")}


def test_range_marker_has_its_own_position() -> None:
    positions = _positions("periodo 1 a 12 inscricoes")
    assert positions["periodo"] == 0
    assert positions["rng:1-12"] == 1
    assert positions["inscricoes"] == 2


def test_range_endpoints_stay_available_without_taking_positions() -> None:
    """Os endpoints continuam a corresponder por superfície, mas herdam a
    posição do marcador: nunca separam o intervalo dos termos vizinhos."""
    representation = build_lexical_representation(
        normalize_text("periodo 1 a 12 inscricoes"), "pt"
    )
    assert {"1", "12", "rng:1-12"} <= representation.canonical_set()
    positions = representation.first_positions()
    assert positions["1"] == positions["12"] == positions["rng:1-12"] == 1


def test_range_zero_padding_does_not_change_equivalence() -> None:
    assert _canon("01a12") == _canon("1 a 12") == ["rng:1-12"]


def test_surface_tokens_preserve_the_original_form() -> None:
    representation = build_lexical_representation(normalize_text("de 01a12"), "pt")
    assert representation.surface_tokens == ("de", "01a12")


def test_ocr_letters_are_not_numbers() -> None:
    representation = build_lexical_representation(normalize_text("Ro de fevereiro"), "pt")
    assert representation.tokens[0].surface == "ro"
    assert representation.tokens[0].kind is TokenKind.WORD
    assert representation.ranges == ()


# --- 36-41: determinismo e robustez ------------------------------------------


def test_representation_is_deterministic() -> None:
    text = normalize_text("Exames da 1.ª chamada de 1 a 12 de fevereiro")
    first = build_lexical_representation(text, "pt")
    second = build_lexical_representation(text, "pt")
    assert first == second


def test_empty_text_yields_no_tokens() -> None:
    representation = build_lexical_representation("", "pt")
    assert representation.tokens == ()
    assert representation.ranges == ()
    assert representation.canonical_set() == frozenset()
    assert representation.first_positions() == {}


def test_whitespace_only_yields_no_tokens() -> None:
    assert build_lexical_representation(normalize_text("   \n\t "), "pt").tokens == ()


def test_symbols_only_yields_no_tokens() -> None:
    assert build_lexical_representation(normalize_text("!!! ... --- @@@"), "pt").tokens == ()


def test_long_query_is_handled() -> None:
    text = normalize_text(" ".join(f"termo{i}" for i in range(200)))
    representation = build_lexical_representation(text, "pt")
    assert len(representation.tokens) == 200


def test_input_text_is_not_mutated() -> None:
    original = normalize_text("Exames da 2.ª chamada")
    snapshot = str(original)
    build_lexical_representation(original, "pt")
    assert original == snapshot


# --- informative_query_terms (ligação com o reranking) -----------------------


def test_informative_terms_drop_functional_and_keep_ordinal() -> None:
    terms = informative_query_terms(normalize_text("Quando são os exames da 1.ª chamada?"), "pt")
    assert terms == ("exames", "ord:1", "chamada")


def test_informative_terms_written_and_numeric_ordinal_are_equal() -> None:
    written = informative_query_terms(normalize_text("exames da primeira chamada"), "pt")
    numeric = informative_query_terms(normalize_text("exames da 1.ª chamada"), "pt")
    assert written == numeric == ("exames", "ord:1", "chamada")


def test_informative_terms_deduplicate_by_canonical() -> None:
    terms = informative_query_terms(normalize_text("regime regime avaliacao"), "pt")
    assert terms == ("regime", "avaliacao")


def test_informative_terms_keep_range_marker_in_position() -> None:
    # O intervalo é um termo como outro qualquer e ocupa o seu lugar na
    # sequência — não é acrescentado no fim.
    terms = informative_query_terms(
        normalize_text("Qual é o período de inscrições de 01a12?"), "pt"
    )
    assert terms == ("periodo", "inscricoes", "rng:1-12")


def test_informative_terms_range_forms_are_equal() -> None:
    compact = informative_query_terms(normalize_text("periodo 01a12"), "pt")
    spaced = informative_query_terms(normalize_text("periodo 1 a 12"), "pt")
    hyphen = informative_query_terms(normalize_text("periodo 01-12"), "pt")
    assert compact == spaced == hyphen == ("periodo", "rng:1-12")
