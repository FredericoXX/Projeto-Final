"""D4.10a — o painel independente, os digests e a barreira de pré-registo.

Nenhum teste precisa de base de dados, rede ou fornecedor: esta fase não executa
a experiência. As fixtures de base de dados do ``conftest`` são anuladas por isso
mesmo.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.d4_10_protocol import (
    ANSWERABLE,
    HUMAN_CONFIRMED,
    NO_EVIDENCE,
    NO_TARGET_DOCUMENT,
    REVIEW_STATUSES,
    ProtocolError,
    declared_identity,
    distribution,
    document_distribution,
    human_review_digest,
    human_review_summary,
    protocol_digest,
    question_set_digest,
    scenario_digest,
    scenario_distribution,
    validation_block_name,
    verify_declared_identity,
    verify_protocol_has_no_results,
    verify_question_set,
)
from scripts.seal_d4_10_protocol import build_protocol, load_json

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
QUESTION_SET_PATH = REPOSITORY_ROOT / "docs" / "evaluation" / "d4-10-question-set-v1.json"
PROTOCOL_PATH = REPOSITORY_ROOT / "docs" / "evaluation" / "d4-10-protocol-v1.json"

HISTORICAL_GROUND_TRUTH = (
    REPOSITORY_ROOT
    / "docs"
    / "evaluation"
    / "retrieval-ground-truth-p1-lexical-dense-repooled.json"
)
DENSE_ADMISSION_DATASET = (
    REPOSITORY_ROOT / "docs" / "evaluation" / "dense-admission-dataset-v1.json"
)


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


@pytest.fixture(scope="module")
def question_set() -> dict[str, Any]:
    return load_json(QUESTION_SET_PATH)


@pytest.fixture(scope="module")
def protocol() -> dict[str, Any]:
    return load_json(PROTOCOL_PATH)


@pytest.fixture(scope="module")
def snapshot_binding(protocol: dict[str, Any]) -> dict[str, Any]:
    """Binding versionado de S1; o snapshot operacional não existe no CI."""
    return {
        field: protocol[field]
        for field in ("snapshot_id", "corpus_digest", "reference_date")
    }


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def test_the_digests_are_deterministic(question_set: dict[str, Any]) -> None:
    questions = question_set["questions"]
    assert question_set_digest(questions) == question_set_digest(questions)
    assert scenario_digest(question_set) == scenario_digest(question_set)
    assert human_review_digest(questions) == human_review_digest(questions)


def test_the_three_digests_are_distinct(question_set: dict[str, Any]) -> None:
    """Cobrem coisas diferentes; se coincidissem, um deles seria decorativo."""
    questions = question_set["questions"]
    digests = {
        question_set_digest(questions),
        scenario_digest(question_set),
        human_review_digest(questions),
    }
    assert len(digests) == 3


def test_the_artefacts_declare_their_own_digests(
    question_set: dict[str, Any], protocol: dict[str, Any]
) -> None:
    questions = question_set["questions"]
    assert protocol["question_set_digest"] == question_set_digest(questions)
    assert protocol["scenario_digest"] == scenario_digest(question_set)
    assert protocol["human_review_digest"] == human_review_digest(questions)
    assert protocol["protocol_digest"] == protocol_digest(protocol)


def test_the_question_set_carries_its_own_identity(
    question_set: dict[str, Any], protocol: dict[str, Any]
) -> None:
    """O conjunto declara os digests e as distribuições, e são os do protocolo."""
    verify_declared_identity(question_set)
    for field in ("question_set_digest", "scenario_digest", "human_review_digest"):
        assert question_set[field] == protocol[field]
    assert question_set["scenario_distribution"] == protocol["scenario_distribution"]
    assert question_set["document_distribution"] == protocol["document_distribution"]


def test_a_question_set_whose_declared_identity_is_stale_is_refused(
    question_set: dict[str, Any],
) -> None:
    """Carimbo desatualizado é pior do que carimbo nenhum: descreve outro ficheiro."""
    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["question"] += " (editada)"
    with pytest.raises(ProtocolError, match="não corresponde ao conteúdo"):
        verify_declared_identity(tampered)


def test_a_question_set_without_declared_identity_is_refused(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    del tampered["human_review_digest"]
    with pytest.raises(ProtocolError, match="identidade declarada em falta"):
        verify_declared_identity(tampered)


def test_the_sealing_refuses_a_question_set_that_is_not_stamped(
    question_set: dict[str, Any],
) -> None:
    """A selagem não carimba: verifica. Caso contrário concordaria consigo própria."""
    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["question"] += " (editada)"
    verify_question_set(tampered)  # continua internamente válido
    with pytest.raises(ProtocolError, match="não corresponde ao conteúdo"):
        verify_declared_identity(tampered)


def test_editing_a_question_changes_the_question_set_digest(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set["questions"])
    tampered[0]["question"] += " (editada)"
    assert question_set_digest(tampered) != question_set_digest(question_set["questions"])


def test_moving_a_question_between_scenarios_changes_both_digests(
    question_set: dict[str, Any],
) -> None:
    """Mover uma paráfrase de família é leakage, e tem de ser visível."""
    tampered = copy.deepcopy(question_set)
    questions = tampered["questions"]
    other = next(q for q in questions if q["scenario_id"] != questions[0]["scenario_id"])
    questions[0]["scenario_id"] = other["scenario_id"]
    assert question_set_digest(questions) != question_set_digest(
        question_set["questions"]
    )
    assert scenario_digest(tampered) != scenario_digest(question_set)


def test_changing_a_label_changes_the_question_set_digest(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set["questions"])
    tampered[0]["answerability_intent"] = (
        NO_EVIDENCE if tampered[0]["answerability_intent"] == ANSWERABLE else ANSWERABLE
    )
    assert question_set_digest(tampered) != question_set_digest(question_set["questions"])


def test_removing_a_question_changes_the_digest(question_set: dict[str, Any]) -> None:
    tampered = question_set["questions"][:-1]
    assert question_set_digest(tampered) != question_set_digest(question_set["questions"])


def test_confirming_a_review_does_not_change_the_question_set_digest(
    question_set: dict[str, Any],
) -> None:
    """Um humano assinar uma validação não altera nenhuma pergunta.

    Se o digest cobrisse o `review_status`, a revisão humana invalidaria o
    conjunto que ela própria valida — e ninguém a faria.
    """
    reviewed = copy.deepcopy(question_set["questions"])
    for question in reviewed:
        question["review_status"] = HUMAN_CONFIRMED
    assert question_set_digest(reviewed) == question_set_digest(question_set["questions"])
    # Mas tem de ser visível em **algum** digest, senão a revisão não é selável.
    assert human_review_digest(reviewed) != human_review_digest(
        question_set["questions"]
    )


def _confirm(
    question_set: dict[str, Any], question_id: str, annotator: str
) -> dict[str, Any]:
    """Uma variante em que um humano nomeado confirmou uma pergunta."""
    variant = copy.deepcopy(question_set)
    for question in variant["questions"]:
        if question["question_id"] != question_id:
            continue
        question["review_status"] = HUMAN_CONFIRMED
        block = validation_block_name(question)
        question[block]["annotator"] = annotator
        question[block]["validation_status"] = HUMAN_CONFIRMED
    verify_question_set(variant)
    return variant


def test_who_validated_and_what_they_validated_are_covered_by_a_digest(
    question_set: dict[str, Any],
    protocol: dict[str, Any],
    snapshot_binding: dict[str, Any],
) -> None:
    """Duas revisões diferentes não podem produzir a mesma selagem.

    Este é o teste que o contrato anterior não passava: como nenhum digest
    cobria a revisão, confirmar `DX001` com um anotador ou `DX002` com outro
    dava exatamente os mesmos ``question_set_digest``, ``scenario_digest`` e
    ``protocol_digest``. Depois das cinquenta confirmações seria possível
    reescrever quem validou o quê sem invalidar nada.
    """
    first = _confirm(question_set, "DX001", "revisor-A")
    second = _confirm(question_set, "DX002", "revisor-B")

    # O conteúdo das perguntas é o mesmo nas duas variantes, e deve sê-lo.
    assert question_set_digest(first["questions"]) == question_set_digest(
        second["questions"]
    )
    assert scenario_digest(first) == scenario_digest(second)

    # A revisão não é, e a selagem tem de o refletir.
    assert human_review_digest(first["questions"]) != human_review_digest(
        second["questions"]
    )
    for variant in (first, second):
        variant.update(declared_identity(variant))
    assert (
        build_protocol(first, snapshot_binding)["protocol_digest"]
        != build_protocol(second, snapshot_binding)["protocol_digest"]
    )
    assert build_protocol(first, snapshot_binding)["protocol_digest"] != protocol[
        "protocol_digest"
    ]


def test_rewriting_recorded_evidence_changes_the_human_review_digest(
    question_set: dict[str, Any],
) -> None:
    """Trocar a âncora registada é trocar a prova de que a etiqueta assenta."""
    tampered = copy.deepcopy(question_set["questions"])
    target = next(q for q in tampered if q["answerability_intent"] == ANSWERABLE)
    target["answerable_validation"]["located_evidence"][0]["chunk_index"] += 1
    assert human_review_digest(tampered) != human_review_digest(
        question_set["questions"]
    )
    # E não muda o digest do conteúdo: são perguntas iguais, prova diferente.
    assert question_set_digest(tampered) == question_set_digest(
        question_set["questions"]
    )


def test_rewriting_the_rationale_changes_the_human_review_digest(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set["questions"])
    target = next(q for q in tampered if q["answerability_intent"] == ANSWERABLE)
    target["answerable_validation"]["rationale"] = "outra justificação"
    assert human_review_digest(tampered) != human_review_digest(
        question_set["questions"]
    )


def test_redefining_a_scenario_changes_the_scenario_digest(
    question_set: dict[str, Any],
) -> None:
    """Reetiquetar um cenário muda a leitura sem mudar uma única pergunta.

    Trocar `exact_institutional_terms` por `paraphrase_natural` mantém os
    identificadores e as contagens intactos: sem metadados no digest, a
    redefinição passaria despercebida à selagem.
    """
    for field, value in (
        ("scenario_type", "outro_tipo"),
        ("topic", "outro_topico"),
    ):
        tampered = copy.deepcopy(question_set)
        scenario = tampered["scenarios"][0]
        scenario[field] = value
        for question in tampered["questions"]:
            if question["scenario_id"] == scenario["scenario_id"]:
                question[field] = value
        verify_question_set(tampered)
        assert scenario_digest(tampered) != scenario_digest(question_set), field
        assert question_set_digest(tampered["questions"]) == question_set_digest(
            question_set["questions"]
        ), field


def test_a_question_that_contradicts_its_scenario_is_refused(
    question_set: dict[str, Any],
) -> None:
    """Metadados repetidos que não são verificados acabam por divergir."""
    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["scenario_type"] = "outro_tipo"
    with pytest.raises(ProtocolError, match="scenario_type diverge do cenário"):
        verify_question_set(tampered)

    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["target_document"] = "P1-DOC-999"
    with pytest.raises(ProtocolError, match="target_document diverge do cenário"):
        verify_question_set(tampered)


def test_changing_the_fusion_configuration_changes_the_protocol_digest(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["conditions"]["C2"]["k_rrf"] = 10
    assert protocol_digest(tampered) != protocol_digest(protocol)


def test_changing_the_metric_protocol_changes_the_protocol_digest(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["metric_protocol"]["primary_metric"] = "recall@5"
    assert protocol_digest(tampered) != protocol_digest(protocol)


def test_changing_the_bootstrap_seed_changes_the_protocol_digest(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["bootstrap_protocol"]["seed"] = 1
    assert protocol_digest(tampered) != protocol_digest(protocol)


# ---------------------------------------------------------------------------
# Independência do painel
# ---------------------------------------------------------------------------


def test_no_historical_question_id_is_reused(question_set: dict[str, Any]) -> None:
    historical = {
        q["question_id"] for q in load_json(HISTORICAL_GROUND_TRUTH)["questions"]
    }
    historical |= {
        q["question_id"] for q in load_json(DENSE_ADMISSION_DATASET)["questions"]
    }
    new = {q["question_id"] for q in question_set["questions"]}
    assert new & historical == set()
    assert all(qid.startswith("DX") for qid in new)


def test_a_historical_identifier_is_refused(question_set: dict[str, Any]) -> None:
    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["question_id"] = "Q001"
    with pytest.raises(ProtocolError, match="identificador histórico"):
        verify_question_set(tampered)


def test_no_question_text_is_reused_verbatim(question_set: dict[str, Any]) -> None:
    """Reutilizar o texto de uma pergunta histórica seria leakage direto."""

    def normalise(text: str) -> str:
        return " ".join(text.lower().split())

    historical = {
        normalise(q["question"])
        for q in load_json(HISTORICAL_GROUND_TRUTH)["questions"]
    }
    historical |= {
        normalise(q["question"]) for q in load_json(DENSE_ADMISSION_DATASET)["questions"]
    }
    new = {normalise(q["question"]) for q in question_set["questions"]}
    assert new & historical == set()


# ---------------------------------------------------------------------------
# Estrutura do painel
# ---------------------------------------------------------------------------


def test_every_question_has_a_scenario_and_a_review_status(
    question_set: dict[str, Any],
) -> None:
    for question in question_set["questions"]:
        assert question["scenario_id"]
        assert question["review_status"] in REVIEW_STATUSES


def test_no_scenario_is_empty_and_counts_match(question_set: dict[str, Any]) -> None:
    verify_question_set(question_set)
    for scenario in question_set["scenarios"]:
        assert scenario["question_count"] >= 1


def test_a_scenario_may_not_mix_answerability_intents(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    first = tampered["questions"][0]
    sibling = next(
        q
        for q in tampered["questions"]
        if q["scenario_id"] == first["scenario_id"] and q is not first
    )
    sibling["answerability_intent"] = NO_EVIDENCE
    sibling.pop("answerable_validation", None)
    sibling["no_evidence_validation"] = {
        "validation_method": "x",
        "terms_searched": ["x"],
    }
    with pytest.raises(ProtocolError, match="intenções mistas"):
        verify_question_set(tampered)


def test_an_answerable_question_needs_located_evidence(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    target = next(
        q for q in tampered["questions"] if q["answerability_intent"] == ANSWERABLE
    )
    target["answerable_validation"]["located_evidence"] = []
    with pytest.raises(ProtocolError, match="sem evidência localizada"):
        verify_question_set(tampered)


def test_a_no_evidence_question_needs_the_search_that_was_run(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    target = next(
        q for q in tampered["questions"] if q["answerability_intent"] == NO_EVIDENCE
    )
    target["no_evidence_validation"]["terms_searched"] = []
    with pytest.raises(ProtocolError, match="sem termos procurados"):
        verify_question_set(tampered)


def test_a_human_confirmation_needs_a_named_annotator(
    question_set: dict[str, Any],
) -> None:
    """A máquina localiza evidência; assinar por um humano é outra coisa."""
    tampered = copy.deepcopy(question_set)
    target = tampered["questions"][0]
    target["review_status"] = HUMAN_CONFIRMED
    target["answerable_validation"]["annotator"] = None
    with pytest.raises(ProtocolError, match="sem annotator"):
        verify_question_set(tampered)


def test_every_located_anchor_points_at_a_real_corpus_document(
    question_set: dict[str, Any],
) -> None:
    usable = set(question_set["usable_documents"])
    for question in question_set["questions"]:
        for anchor in question.get("answerable_validation", {}).get(
            "located_evidence", []
        ):
            assert anchor["corpus_item_id"] in usable
            assert isinstance(anchor["chunk_index"], int)


def test_the_panel_is_materially_larger_than_the_d4_9_one(
    question_set: dict[str, Any],
) -> None:
    """A D4.9 mediu 12 perguntas e o efeito só era observável em sete."""
    counts = distribution(question_set)
    assert counts["question_count"] > 12
    assert counts["scenario_count"] > 12
    assert counts["by_answerability_intent"][NO_EVIDENCE] >= 1


def test_the_document_distribution_reports_volume_and_semantic_type(
    question_set: dict[str, Any],
) -> None:
    """Contagem sozinha não distingue cobertura de repetição.

    Cinco perguntas sobre um documento todas do mesmo tipo não testam o que
    cinco perguntas repartidas por termos exatos, paráfrase e formulação
    indireta testam. As duas leituras têm de estar no mesmo sítio.
    """
    coverage = document_distribution(question_set)
    total = sum(entry["question_count"] for entry in coverage.values())
    assert total == len(question_set["questions"])
    for name, entry in coverage.items():
        assert entry["question_count"] >= 1, name
        assert entry["by_scenario_type"], name
        assert sum(entry["by_scenario_type"].values()) == entry["question_count"], name
        assert entry["scenario_count"] == len(entry["scenario_ids"]), name


def test_every_indexed_document_appears_in_the_distribution(
    question_set: dict[str, Any],
) -> None:
    coverage = document_distribution(question_set)
    assert set(question_set["usable_documents"]) <= set(coverage)


def test_the_no_evidence_questions_are_not_hidden_from_the_distribution(
    question_set: dict[str, Any],
) -> None:
    """Sem chave explícita, as oito NO_EVIDENCE desapareciam da contagem."""
    coverage = document_distribution(question_set)
    absent = coverage[NO_TARGET_DOCUMENT]
    assert absent["by_answerability_intent"] == {
        NO_EVIDENCE: distribution(question_set)["by_answerability_intent"][NO_EVIDENCE]
    }


def test_the_scenario_distribution_matches_the_declared_scenarios(
    question_set: dict[str, Any],
) -> None:
    composition = scenario_distribution(question_set)
    assert set(composition) == {s["scenario_id"] for s in question_set["scenarios"]}
    for scenario in question_set["scenarios"]:
        entry = composition[scenario["scenario_id"]]
        assert entry["question_count"] == len(entry["question_ids"])
        assert entry["question_count"] == scenario["question_count"]
        assert entry["scenario_type"] == scenario["scenario_type"]
        assert entry["topic"] == scenario["topic"]
        assert entry["target_document"] == scenario["target_document"]


# ---------------------------------------------------------------------------
# O protocolo é pré-registo, não resultado
# ---------------------------------------------------------------------------


def test_the_protocol_contains_no_experimental_result(
    protocol: dict[str, Any],
) -> None:
    verify_protocol_has_no_results(protocol)


def test_a_protocol_carrying_metrics_is_refused(protocol: dict[str, Any]) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["aggregate"] = {"C2": {"ndcg": {"5": 0.9}}}
    with pytest.raises(ProtocolError, match="campo de resultado"):
        verify_protocol_has_no_results(tampered)


def test_a_protocol_carrying_a_nested_ranking_is_refused(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["conditions"]["C2"]["ranking"] = [{"position": 1}]
    with pytest.raises(ProtocolError, match="campo de resultado"):
        verify_protocol_has_no_results(tampered)


def test_the_protocol_declares_no_magnitude_threshold(
    protocol: dict[str, Any],
) -> None:
    """A D4.9 criou um `MATERIAL_DELTA` contra a instrução da fase.

    Nenhum ramo da decisão pode depender de a magnitude ultrapassar um número:
    `A` exige que o intervalo de confiança não inclua zero, que é uma afirmação
    sobre o sinal e a incerteza, não sobre o tamanho do efeito.
    """
    decision = protocol["decision_protocol"]
    assert decision["magnitude_threshold"] is None
    assert "intervalo de confianca" in decision["A_EVIDENCE_FOR_HYBRID"]
    assert "NAO inclui zero" in decision["A_EVIDENCE_FOR_HYBRID"]


def test_the_frozen_conditions_match_the_phases_that_measured_them(
    protocol: dict[str, Any],
) -> None:
    from app.evaluation.hybrid_rrf import FINAL_TOP_K, K_RRF, SOURCE_DEPTH, TIE_BREAK

    c2 = protocol["conditions"]["C2"]
    assert c2["k_rrf"] == K_RRF
    assert c2["source_depth"] == SOURCE_DEPTH
    assert c2["final_top_k"] == FINAL_TOP_K
    assert c2["tie_break"] == list(TIE_BREAK)


def test_the_metric_protocol_matches_the_shared_constants(
    protocol: dict[str, Any],
) -> None:
    from app.evaluation.retrieval_metrics import (
        BINARY_RELEVANCE_THRESHOLD,
        K_VALUES,
        NDCG_GAIN_BY_GRADE,
        PRIMARY_K,
    )

    metric = protocol["metric_protocol"]
    assert metric["k_values"] == list(K_VALUES)
    assert metric["primary_k"] == PRIMARY_K
    assert metric["binary_relevance_threshold"] == BINARY_RELEVANCE_THRESHOLD
    assert metric["ndcg_gain_mapping"] == {
        str(k): v for k, v in NDCG_GAIN_BY_GRADE.items()
    }


def test_the_bootstrap_resamples_scenarios_not_questions(
    protocol: dict[str, Any],
) -> None:
    """Reamostrar paráfrases duplicaria evidência estatística inexistente."""
    bootstrap = protocol["bootstrap_protocol"]
    assert bootstrap["unit"] == "scenario_id"
    assert bootstrap["replicates"] == 10000
    assert bootstrap["confidence_interval"] == 0.95
    assert isinstance(bootstrap["seed"], int)


def test_the_decision_rule_is_declared_before_any_measurement(
    protocol: dict[str, Any],
) -> None:
    decision = protocol["decision_protocol"]
    for branch in ("A_EVIDENCE_FOR_HYBRID", "B_EVIDENCE_FOR_DENSE", "C_INCONCLUSIVE"):
        assert decision[branch]


def test_the_phase_is_not_frozen_while_human_review_is_pending(
    question_set: dict[str, Any], protocol: dict[str, Any]
) -> None:
    """O congelamento é uma afirmação sobre revisão humana, não sobre digests.

    Enquanto houver validações por confirmar, o que existe é uma proposta
    auditável. Declará-la congelada seria repetir, com outra roupagem, a
    afirmação que a D4.9 não podia provar.
    """
    summary = human_review_summary(question_set)
    assert summary == protocol["human_review"]
    assert summary["freeze_ready"] is (summary["pending_human_review"] == 0)


def test_the_d4_10b_preconditions_include_the_review_digest(
    protocol: dict[str, Any],
) -> None:
    """A D4.10b tem de recusar correr contra outra revisão, não só outro texto."""
    preconditions = " ".join(protocol["d4_10b_preconditions"])
    for digest in ("question_set_digest", "scenario_digest", "human_review_digest"):
        assert digest in preconditions
    assert "freeze_ready" in preconditions
    assert set(protocol["digest_scope"]) == {
        "question_set_digest",
        "scenario_digest",
        "human_review_digest",
    }


# ---------------------------------------------------------------------------
# A fase não executa nada
# ---------------------------------------------------------------------------


_PURITY_SNIPPET = """
import sys

import app.evaluation.d4_10_protocol
import scripts.seal_d4_10_protocol

for forbidden in ("sqlalchemy", "openai", "fastapi"):
    assert forbidden not in sys.modules, forbidden
print("ok")
"""


def test_the_phase_touches_no_database_no_provider_and_no_application() -> None:
    result = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [sys.executable, "-c", _PURITY_SNIPPET],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


@pytest.mark.parametrize(
    "script", ["seal_d4_10_protocol.py", "stamp_d4_10_question_set.py"]
)
def test_the_phase_commands_import_nothing_that_could_execute_the_experiment(
    script: str,
) -> None:
    """A garantia é sobre o que o módulo pode fazer, não sobre as palavras que usa.

    Procurar a cadeia ``embed`` no ficheiro apanharia o bloco que *pré-regista*
    o congelamento de embeddings — que é exatamente o que esta fase deve
    conter. O que não pode existir é a capacidade: sem importar retrievers,
    modelos de embeddings ou a fusão, o comando não tem como executar coisa
    nenhuma.
    """
    import ast

    tree = ast.parse((BACKEND_DIR / "scripts" / script).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "app.retrieval",
        "app.embeddings",
        "app.evaluation.hybrid_rrf",
        "app.evaluation.dense_baseline",
        "app.database",
        "openai",
        "sqlalchemy",
    )
    for module in imported:
        assert not module.startswith(forbidden), module


def test_no_relevance_grade_exists_anywhere_in_the_question_set(
    question_set: dict[str, Any],
) -> None:
    """Os graus 0/1/2 só existem depois de haver rankings para julgar."""
    payload = json.dumps(question_set, ensure_ascii=False)
    assert '"relevance"' not in payload
    assert '"judgments"' not in payload
    assert '"grade"' not in payload


def test_rebuilding_the_protocol_reproduces_its_digest(
    question_set: dict[str, Any],
    protocol: dict[str, Any],
    snapshot_binding: dict[str, Any],
) -> None:
    rebuilt = build_protocol(question_set, snapshot_binding)
    assert rebuilt["protocol_digest"] == protocol["protocol_digest"]


def test_production_retrieval_is_untouched() -> None:
    source = (BACKEND_DIR / "app" / "retrieval" / "dependencies.py").read_text(
        encoding="utf-8"
    )
    assert "PostgresLexicalRetriever()" in source
    assert "Hybrid" not in source
