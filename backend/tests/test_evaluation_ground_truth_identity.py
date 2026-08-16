"""Identidade do *ground truth* e controlo do pareamento (D4.4).

Dois contratos distintos, e a diferença entre eles é o assunto de metade destes
testes:

- o **digest** identifica o que a medição lê, para responder a *"estes dois
  ficheiros mediriam o mesmo?"*;
- o **pareamento** prova que a versão com diacríticos é a original com acentos
  restituídos e mais nada.

Testes puros: não tocam na base de dados. Os dois últimos leem os artefactos
reais versionados, porque a afirmação central da fase — *o par é mesmo um par* —
não vale nada se só for verdadeira sobre fixtures.
"""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.text_normalization import normalize_text
from app.evaluation.ground_truth_identity import (
    JUDGMENT_FIELDS,
    PROTOCOL_FIELDS,
    QUESTION_FIELDS,
    GroundTruthIdentityError,
    canonical_ground_truth,
    ground_truth_digest,
    strip_diacritics,
    verify_pairing,
)
from app.evaluation.results import canonical_json
from scripts.evaluate_retrieval_experiment import _strip_accents

DOCS = Path(__file__).resolve().parents[2] / "docs" / "evaluation"
SEED_PATH = DOCS / "retrieval-ground-truth-p1-seed.json"
PAIRED_PATH = DOCS / "retrieval-ground-truth-p1-diacritics.json"


def _question(
    question_id: str = "Q001",
    *,
    text: str = "Ate quando posso pedir a anulacao?",
    excluded: bool = False,
    no_evidence: bool = False,
    judgments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question": text,
        "language": "pt",
        "question_origin": "constructed_from_public_documents",
        "temporal_scope": "2025/2026",
        "difficulty_types": ["date_deadline"],
        "no_relevant_evidence": no_evidence,
        "excluded_from_metrics": excluded,
        "exclusion_reason": None,
        "evidence_judgments": judgments
        if judgments is not None
        else [
            {"corpus_item_id": "P1-DOC-002", "chunk_index": 24, "relevance": 2, "note": "x"},
            {"corpus_item_id": "P1-DOC-003", "chunk_index": 25, "relevance": 0, "note": "y"},
        ],
        "document_level_relevance": [{"corpus_item_id": "P1-DOC-002", "relevance": 2}],
        "annotation": {"annotator_1": "author"},
        "notes": None,
    }


def _ground_truth(questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "2",
        "contract": "retrieval_ground_truth",
        "corpus_id": "P1",
        "snapshot_id": "a" * 64,
        "corpus_digest": "b" * 64,
        "reference_date": "2026-08-15",
        "scope_note": "prosa",
        "metric_protocol": {
            "note": "prosa",
            "k_values": [1, 3, 5],
            "primary_k": 5,
            "binary_relevance_threshold": 2,
            "ndcg_gain_mapping": {"0": 0, "1": 1, "2": 3},
            "unjudged_chunk_treatment": "ASSUMED_IRRELEVANT",
        },
        "questions": questions if questions is not None else [_question()],
    }


def _paired_question(
    original: dict[str, Any],
    *,
    text: str,
    restored: list[list[str]],
    paired_id: str | None = None,
) -> dict[str, Any]:
    paired = copy.deepcopy(original)
    paired["question_id"] = paired_id or f"{original['question_id']}-diacritics"
    paired["paired_question_id"] = original["question_id"]
    paired["question"] = text
    paired["diacritics_restored"] = restored
    return paired


def _paired_set(
    original: dict[str, Any], questions: list[dict[str, Any]]
) -> dict[str, Any]:
    paired = copy.deepcopy(original)
    paired["questions"] = questions
    return paired


def _valid_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    original = _ground_truth()
    paired = _paired_set(
        original,
        [
            _paired_question(
                original["questions"][0],
                text="Até quando posso pedir a anulação?",
                restored=[["ate", "até"], ["anulacao", "anulação"]],
            )
        ],
    )
    return original, paired


# ---------------------------------------------------------------------------
# Digest: determinismo e âmbito
# ---------------------------------------------------------------------------


def test_digest_is_a_sha256_of_the_canonical_projection() -> None:
    """Nunca ``hash()`` do Python, que é aleatorizado por processo."""
    ground_truth = _ground_truth()
    expected = hashlib.sha256(
        canonical_json(canonical_ground_truth(ground_truth)).encode("utf-8")
    ).hexdigest()
    assert ground_truth_digest(ground_truth) == expected
    assert len(expected) == 64


def test_same_input_gives_the_same_digest() -> None:
    assert ground_truth_digest(_ground_truth()) == ground_truth_digest(_ground_truth())


def test_digest_ignores_the_order_of_the_questions() -> None:
    """Reordenar o ficheiro não muda número nenhum: a agregação é macro-média."""
    first, second = _question("Q001"), _question("Q002")
    assert ground_truth_digest(_ground_truth([first, second])) == ground_truth_digest(
        _ground_truth([second, first])
    )


def test_digest_ignores_the_order_of_the_judgments() -> None:
    judgments = [
        {"corpus_item_id": "P1-DOC-002", "chunk_index": 24, "relevance": 2},
        {"corpus_item_id": "P1-DOC-003", "chunk_index": 25, "relevance": 0},
    ]
    forward = _ground_truth([_question(judgments=judgments)])
    backward = _ground_truth([_question(judgments=list(reversed(judgments)))])
    assert ground_truth_digest(forward) == ground_truth_digest(backward)


@pytest.mark.parametrize(
    "field",
    ["notes", "difficulty_types", "temporal_scope", "question_origin", "annotation"],
)
def test_digest_ignores_question_prose_and_provenance(field: str) -> None:
    """O digest não é um hash do ficheiro, e diz isso de forma verificável."""
    changed = _ground_truth()
    changed["questions"][0][field] = "outra coisa"
    assert ground_truth_digest(changed) == ground_truth_digest(_ground_truth())


@pytest.mark.parametrize("field", ["snapshot_id", "corpus_digest", "reference_date"])
def test_digest_ignores_corpus_identity(field: str) -> None:
    """Identificam o corpus, não as perguntas.

    Se entrassem, dois conjuntos de perguntas diferentes sobre o mesmo corpus
    partilhariam digest — exatamente o buraco que o D4.3 registou no
    ``snapshot_id``.
    """
    changed = _ground_truth()
    changed[field] = "z" * 64
    assert ground_truth_digest(changed) == ground_truth_digest(_ground_truth())


def test_digest_ignores_a_judgment_note() -> None:
    changed = _ground_truth()
    changed["questions"][0]["evidence_judgments"][0]["note"] = "reescrita"
    assert ground_truth_digest(changed) == ground_truth_digest(_ground_truth())


def test_digest_changes_when_the_question_text_changes() -> None:
    changed = _ground_truth([_question(text="Até quando posso pedir a anulação?")])
    assert ground_truth_digest(changed) != ground_truth_digest(_ground_truth())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("question_id", "Q999"),
        ("language", "en"),
        ("no_relevant_evidence", True),
        ("excluded_from_metrics", True),
    ],
)
def test_digest_changes_with_any_measurement_relevant_question_field(
    field: str, value: object
) -> None:
    changed = _ground_truth()
    changed["questions"][0][field] = value
    assert ground_truth_digest(changed) != ground_truth_digest(_ground_truth())


def test_digest_changes_when_a_relevance_grade_changes() -> None:
    changed = _ground_truth()
    changed["questions"][0]["evidence_judgments"][1]["relevance"] = 2
    assert ground_truth_digest(changed) != ground_truth_digest(_ground_truth())


def test_digest_changes_when_a_judgment_is_removed() -> None:
    changed = _ground_truth()
    changed["questions"][0]["evidence_judgments"].pop()
    assert ground_truth_digest(changed) != ground_truth_digest(_ground_truth())


def test_digest_changes_when_a_question_is_added() -> None:
    changed = _ground_truth([_question("Q001"), _question("Q002")])
    assert ground_truth_digest(changed) != ground_truth_digest(_ground_truth())


@pytest.mark.parametrize("field", PROTOCOL_FIELDS)
def test_digest_changes_with_any_operative_protocol_field(field: str) -> None:
    changed = _ground_truth()
    changed["metric_protocol"][field] = "alterado"
    assert ground_truth_digest(changed) != ground_truth_digest(_ground_truth())


def test_digest_ignores_protocol_prose() -> None:
    changed = _ground_truth()
    changed["metric_protocol"]["note"] = "outra justificacao"
    assert ground_truth_digest(changed) == ground_truth_digest(_ground_truth())


def test_canonical_projection_covers_exactly_the_declared_fields() -> None:
    """Alargar ou estreitar a projeção tem de ser um ato deliberado.

    Sem esta afirmação, acrescentar um campo à projeção mudaria todos os digests
    já publicados sem que nada o assinalasse.
    """
    canonical = canonical_ground_truth(_ground_truth())
    assert set(canonical) == {
        "schema_version",
        "contract",
        "corpus_id",
        "metric_protocol",
        "questions",
    }
    assert set(canonical["metric_protocol"]) == set(PROTOCOL_FIELDS)
    question = canonical["questions"][0]
    assert set(question) == {*QUESTION_FIELDS, "evidence_judgments"}
    assert set(question["evidence_judgments"][0]) == set(JUDGMENT_FIELDS)


@pytest.mark.parametrize(
    "removed", ["schema_version", "contract", "corpus_id", "metric_protocol", "questions"]
)
def test_a_malformed_file_fails_instead_of_producing_a_plausible_digest(
    removed: str,
) -> None:
    ground_truth = _ground_truth()
    del ground_truth[removed]
    with pytest.raises(GroundTruthIdentityError, match="missing required field"):
        ground_truth_digest(ground_truth)


def test_a_missing_judgment_field_fails() -> None:
    ground_truth = _ground_truth()
    del ground_truth["questions"][0]["evidence_judgments"][0]["relevance"]
    with pytest.raises(GroundTruthIdentityError, match="relevance"):
        ground_truth_digest(ground_truth)


def test_duplicate_question_ids_fail() -> None:
    ground_truth = _ground_truth([_question("Q001"), _question("Q001")])
    with pytest.raises(GroundTruthIdentityError, match="duplicate question_id"):
        ground_truth_digest(ground_truth)


# ---------------------------------------------------------------------------
# strip_diacritics
# ---------------------------------------------------------------------------


def test_strip_diacritics_agrees_with_the_d43_helper() -> None:
    """Duas implementações da mesma remoção não podem divergir em silêncio."""
    for text in (
        "prorrogação",
        "cerimónia",
        "PRESENÇA",
        "período  e\nmatrícula",
        "sem acentos",
        "",
    ):
        assert strip_diacritics(text) == _strip_accents(text)


def test_strip_diacritics_is_narrower_than_the_production_normalizer() -> None:
    """``normalize_text`` também descarta maiúsculas e espaçamento.

    O pareamento tem de rejeitar essas duas alterações, e por isso não pode
    apoiar-se nela.
    """
    text = "Até  Quando"
    assert strip_diacritics(text) == "Ate  Quando"
    assert normalize_text(text) == "ate quando"


def test_strip_diacritics_handles_the_cedilla() -> None:
    assert strip_diacritics("anulação") == "anulacao"


# ---------------------------------------------------------------------------
# Pareamento
# ---------------------------------------------------------------------------


def test_a_valid_pair_is_accepted() -> None:
    report = verify_pairing(*_valid_pair())
    assert report.valid, report.problems
    assert report.restored_pairs == ("Q001",)
    assert report.identical_pairs == ()


def test_a_question_without_diacritics_is_an_identity_pair() -> None:
    original = _ground_truth([_question(text="Quando foi o primeiro dia de aulas?")])
    paired = _paired_set(
        original,
        [
            _paired_question(
                original["questions"][0],
                text="Quando foi o primeiro dia de aulas?",
                restored=[],
            )
        ],
    )
    report = verify_pairing(original, paired)
    assert report.valid, report.problems
    assert report.identical_pairs == ("Q001",)


def test_a_reformulated_question_is_rejected() -> None:
    """O caso que o enunciado manda reportar em vez de incluir."""
    original = _ground_truth()
    paired = _paired_set(
        original,
        [
            _paired_question(
                original["questions"][0],
                text="Até quando é que posso pedir a anulação?",
                restored=[["ate", "até"], ["anulacao", "anulação"]],
            )
        ],
    )
    report = verify_pairing(original, paired)
    assert not report.valid
    assert any("reformulation" in problem for problem in report.problems)


def test_a_changed_capitalisation_is_rejected() -> None:
    original = _ground_truth()
    paired = _paired_set(
        original,
        [
            _paired_question(
                original["questions"][0],
                text="ATÉ quando posso pedir a anulação?",
                restored=[["ate", "até"], ["anulacao", "anulação"]],
            )
        ],
    )
    assert not verify_pairing(original, paired).valid


def test_changed_judgments_are_rejected() -> None:
    original, paired = _valid_pair()
    paired["questions"][0]["evidence_judgments"][0]["relevance"] = 1
    report = verify_pairing(original, paired)
    assert any("evidence_judgments differ" in problem for problem in report.problems)


def test_an_added_judgment_is_rejected() -> None:
    original, paired = _valid_pair()
    paired["questions"][0]["evidence_judgments"].append(
        {"corpus_item_id": "P1-DOC-004", "chunk_index": 7, "relevance": 2}
    )
    assert any(
        "evidence_judgments differ" in problem
        for problem in verify_pairing(original, paired).problems
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temporal_scope", "2023/2024"),
        ("excluded_from_metrics", True),
        ("no_relevant_evidence", True),
        ("language", "en"),
        ("difficulty_types", ["synonym"]),
        ("exclusion_reason", "outra"),
        ("document_level_relevance", []),
    ],
)
def test_any_annotation_change_is_rejected(field: str, value: object) -> None:
    """Mais estrito do que o digest, e de propósito.

    ``temporal_scope`` e ``document_level_relevance`` não entram em métrica
    nenhuma, mas alterá-los faria do par outra pergunta.
    """
    original, paired = _valid_pair()
    paired["questions"][0][field] = value
    report = verify_pairing(original, paired)
    assert any(field in problem for problem in report.problems)


def test_a_missing_pair_is_rejected() -> None:
    original = _ground_truth([_question("Q001"), _question("Q002")])
    paired = _paired_set(
        original,
        [
            _paired_question(
                original["questions"][0],
                text="Até quando posso pedir a anulação?",
                restored=[["ate", "até"], ["anulacao", "anulação"]],
            )
        ],
    )
    report = verify_pairing(original, paired)
    assert any("without a pair" in problem for problem in report.problems)


def test_a_pair_pointing_at_an_unknown_question_is_rejected() -> None:
    original, paired = _valid_pair()
    paired["questions"][0]["paired_question_id"] = "Q999"
    paired["questions"][0]["question_id"] = "Q999-diacritics"
    report = verify_pairing(original, paired)
    assert any("absent from the original set" in problem for problem in report.problems)


def test_two_pairs_claiming_the_same_original_are_rejected() -> None:
    original, paired = _valid_pair()
    paired["questions"].append(copy.deepcopy(paired["questions"][0]))
    report = verify_pairing(original, paired)
    assert any("claimed by both" in problem for problem in report.problems)


def test_an_identifier_that_does_not_derive_from_the_original_is_rejected() -> None:
    original, paired = _valid_pair()
    paired["questions"][0]["question_id"] = "Q001b"
    report = verify_pairing(original, paired)
    assert any("is not Q001-diacritics" in problem for problem in report.problems)


def test_a_missing_paired_question_id_is_rejected() -> None:
    original, paired = _valid_pair()
    del paired["questions"][0]["paired_question_id"]
    report = verify_pairing(original, paired)
    assert any("no paired_question_id" in problem for problem in report.problems)


def test_an_incomplete_restoration_list_is_rejected() -> None:
    """A lista tem de ser completa, não apenas sólida.

    Uma lista que se esquece de uma palavra acentuada é documentação que passou a
    mentir, e é exatamente o tipo de coisa que ninguém volta a ler.
    """
    original, paired = _valid_pair()
    paired["questions"][0]["diacritics_restored"] = [["ate", "até"]]
    report = verify_pairing(original, paired)
    assert any("absent from diacritics_restored" in problem for problem in report.problems)


def test_an_unsound_restoration_claim_is_rejected() -> None:
    original, paired = _valid_pair()
    paired["questions"][0]["diacritics_restored"] = [
        ["ate", "até"],
        ["anulacao", "anulacão"],
    ]
    report = verify_pairing(original, paired)
    assert any("does not occur in the paired" in problem for problem in report.problems)


def test_a_restoration_claim_naming_a_word_absent_from_the_original_is_rejected() -> None:
    original, paired = _valid_pair()
    paired["questions"][0]["diacritics_restored"] = [
        ["ate", "até"],
        ["anulacao", "anulação"],
        ["periodo", "período"],
    ]
    report = verify_pairing(original, paired)
    assert any("does not occur in the original" in problem for problem in report.problems)


def test_question_sets_disagreeing_on_the_corpus_are_rejected() -> None:
    original, paired = _valid_pair()
    paired["corpus_digest"] = "z" * 64
    report = verify_pairing(original, paired)
    assert any("disagree on corpus_digest" in problem for problem in report.problems)


def test_question_sets_disagreeing_on_the_protocol_are_rejected() -> None:
    original, paired = _valid_pair()
    paired["metric_protocol"]["primary_k"] = 3
    report = verify_pairing(original, paired)
    assert any("metric_protocol.primary_k" in problem for problem in report.problems)


# ---------------------------------------------------------------------------
# Os artefactos reais
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_versioned_question_sets_form_a_valid_pair() -> None:
    report = verify_pairing(_load(SEED_PATH), _load(PAIRED_PATH))
    assert report.valid, report.problems
    assert len(report.pairs) == 14
    assert report.identical_pairs == ("Q010", "Q011", "Q013")


def test_the_historical_question_set_still_has_no_diacritics() -> None:
    """A premissa do D4.3 §6.2, verificada e não recordada.

    Se deixasse de ser verdade, o conjunto histórico teria sido alterado e o
    emparelhamento perderia o significado.
    """
    for question in _load(SEED_PATH)["questions"]:
        assert strip_diacritics(question["question"]) == question["question"]


def test_the_two_versioned_question_sets_have_different_digests() -> None:
    original, paired = _load(SEED_PATH), _load(PAIRED_PATH)
    assert ground_truth_digest(original) != ground_truth_digest(paired)
