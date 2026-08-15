"""Identidade determinística do Evaluation Snapshot — testes puros.

Sem base de dados, sem ``TestClient``, sem rede: o sujeito é uma função pura
sobre valores construídos à mão, no estilo de
``test_evidence_retrievability_unit.py`` e ``test_decision_contracts.py``.

O que estes testes protegem é a propriedade que dá sentido ao snapshot:

    mesma configuração experimental material  → mesmo snapshot_id
    alteração material                        → snapshot_id diferente

Uma identidade que mudasse por acidente (ordem da consulta, ordem de um dict,
aleatorização do ``hash()``) tornaria duas execuções iguais indistinguíveis de
duas execuções diferentes, que é exatamente o erro que o snapshot existe para
impedir.
"""

import ast
import inspect
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.evaluation import snapshot as snapshot_module
from app.evaluation.results import canonical_json
from app.evaluation.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    ChunkIdentity,
    CorpusEntry,
    EvaluationSnapshot,
    RetrievalConfiguration,
    build_snapshot,
    canonical_corpus_payload,
    compute_chunk_digest,
    compute_corpus_digest,
    sort_corpus_entries,
)

INSTITUTION = UUID("11111111-1111-1111-1111-111111111111")
OTHER_INSTITUTION = UUID("22222222-2222-2222-2222-222222222222")
REFERENCE_DATE = date(2026, 8, 13)


def _chunk(index: int = 0, **overrides: Any) -> ChunkIdentity:
    base = ChunkIdentity(
        chunk_index=index,
        content_sha256=f"{index:064x}",
        normalized_content_sha256=f"{index + 500:064x}",
        section_title="Regime de avaliação",
        structure_type="paragraph",
    )
    return replace(base, **overrides)


def _entry(seed: int = 1, **overrides: Any) -> CorpusEntry:
    base = CorpusEntry(
        document_id=UUID(f"{seed:032x}"),
        document_version_id=UUID(f"{seed + 100:032x}"),
        document_title="Regulamento Académico",
        source_url="https://example.invalid/regulamento",
        language="pt",
        official_source=True,
        valid_from=date(2026, 1, 1),
        valid_until=None,
        checksum_sha256=f"{seed:064x}",
        chunk_count=2,
        chunk_digest=compute_chunk_digest((_chunk(0), _chunk(1))),
    )
    return replace(base, **overrides)


def _config(**overrides: Any) -> RetrievalConfiguration:
    base = RetrievalConfiguration(
        strategy="lexical",
        pipeline_version="lexical_pipeline_v1",
        scoring_version="lexical_composite_v1",
        score_kind="lexical_relevance",
        comparable_across_queries=False,
        language="pt",
        top_k=5,
        official_only=True,
        fts_config="portuguese",
        min_relevance_score=0.05,
        candidate_limit=25,
    )
    return replace(base, **overrides)


def _snapshot(
    entries: tuple[CorpusEntry, ...] | None = None,
    config: RetrievalConfiguration | None = None,
    reference_date: date = REFERENCE_DATE,
    institution: UUID = INSTITUTION,
) -> EvaluationSnapshot:
    return build_snapshot(
        institution_id=institution,
        reference_date=reference_date,
        entries=entries if entries is not None else (_entry(1), _entry(2)),
        retrieval=config if config is not None else _config(),
    )


# --- T1 · determinismo ----------------------------------------------------


def test_same_inputs_produce_the_same_snapshot_id() -> None:
    assert _snapshot().snapshot_id == _snapshot().snapshot_id
    assert _snapshot().corpus_digest == _snapshot().corpus_digest


def test_snapshot_id_is_a_sha256_hex_digest() -> None:
    """Identidade criptográfica, não um UUID aleatório nem um contador."""
    snapshot = _snapshot()

    assert len(snapshot.snapshot_id) == 64
    assert set(snapshot.snapshot_id) <= set("0123456789abcdef")
    assert snapshot.snapshot_id != snapshot.corpus_digest


# --- T2 · ordem acidental da base de dados --------------------------------


def test_corpus_entry_order_does_not_change_the_identity() -> None:
    """A ordem em que o PostgreSQL devolve linhas é acidental.

    Sem ``ORDER BY`` não há ordem garantida, e uma identidade que dependesse
    dela mudaria sozinha entre execuções sobre os mesmos dados.
    """
    entries = (_entry(1), _entry(2), _entry(3))
    reversed_entries = tuple(reversed(entries))
    shuffled = (entries[2], entries[0], entries[1])

    digests = {compute_corpus_digest(order) for order in (entries, reversed_entries, shuffled)}
    ids = {_snapshot(entries=order).snapshot_id for order in (entries, reversed_entries, shuffled)}

    assert len(digests) == 1
    assert len(ids) == 1


def test_chunk_order_does_not_change_the_chunk_digest() -> None:
    chunks = (_chunk(0), _chunk(1), _chunk(2))

    assert compute_chunk_digest(chunks) == compute_chunk_digest(tuple(reversed(chunks)))


def test_sort_corpus_entries_is_a_total_deterministic_order() -> None:
    entries = (_entry(3), _entry(1), _entry(2))

    ordered = sort_corpus_entries(entries)

    assert [entry.document_id for entry in ordered] == [
        _entry(1).document_id,
        _entry(2).document_id,
        _entry(3).document_id,
    ]


# --- T3/T4 · alterações materiais do corpus -------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"document_version_id": UUID(f"{999:032x}")}, id="outra-versao"),
        pytest.param({"document_title": "Outro Regulamento"}, id="titulo"),
        pytest.param({"source_url": "https://example.invalid/outro"}, id="source-url"),
        pytest.param({"source_url": None}, id="source-url-removido"),
        pytest.param({"language": "en"}, id="idioma"),
        pytest.param({"official_source": False}, id="oficialidade"),
        pytest.param({"valid_from": date(2026, 2, 1)}, id="valid-from"),
        pytest.param({"valid_until": date(2026, 12, 31)}, id="valid-until"),
        pytest.param({"checksum_sha256": "f" * 64}, id="checksum"),
        pytest.param({"chunk_count": 3}, id="numero-de-segmentos"),
        pytest.param(
            {"chunk_digest": compute_chunk_digest((_chunk(0, content_sha256="a" * 64),))},
            id="conteudo-dos-segmentos",
        ),
    ],
)
def test_material_version_change_alters_both_identities(overrides: dict) -> None:
    """Cada campo da entrada é material: se muda, a identidade tem de mudar."""
    baseline = (_entry(1), _entry(2))
    mutated = (_entry(1, **overrides), _entry(2))

    assert compute_corpus_digest(mutated) != compute_corpus_digest(baseline)
    assert _snapshot(entries=mutated).snapshot_id != _snapshot(entries=baseline).snapshot_id


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"section_title": "Outra secção"}, id="titulo-de-seccao"),
        pytest.param({"structure_type": "table_row"}, id="tipo-estrutural"),
        pytest.param({"content_sha256": "b" * 64}, id="conteudo"),
        pytest.param({"normalized_content_sha256": "c" * 64}, id="conteudo-normalizado"),
    ],
)
def test_chunk_signals_that_feed_ranking_change_the_chunk_digest(overrides: dict) -> None:
    """Resegmentar sem trocar o ficheiro muda o que a recuperação devolve.

    ``section_title`` e ``structure_type`` entram no ranking lexical, e
    ``normalized_content`` é o texto efetivamente pesquisado — é dele que a
    coluna gerada ``search_vector`` deriva. Ignorar qualquer um deles deixaria
    uma alteração material invisível para a identidade.
    """
    assert compute_chunk_digest((_chunk(0, **overrides),)) != compute_chunk_digest((_chunk(0),))


def test_page_number_is_deliberately_absent_from_the_chunk_identity() -> None:
    """Decisão explícita (M1): ``page_number`` não é material.

    É transportado pelo candidato lexical mas **nunca lido** por
    ``build_features``, e não viaja em ``Evidence``. Qualquer mudança de
    paginação que altere a recuperação altera também o conteúdo dos segmentos,
    que já é identificado. Incluí-lo produziria falsos positivos de "o corpus
    mudou" sobre execuções cientificamente equivalentes.
    """
    assert "page_number" not in _chunk(0).canonical()


def test_adding_or_removing_an_eligible_version_changes_the_corpus_digest() -> None:
    one = (_entry(1),)
    two = (_entry(1), _entry(2))

    assert compute_corpus_digest(one) != compute_corpus_digest(two)
    assert compute_corpus_digest(()) != compute_corpus_digest(one)


def test_empty_corpus_has_a_stable_identity() -> None:
    """Um corpus vazio é um estado legítimo, não um erro."""
    assert compute_corpus_digest(()) == compute_corpus_digest(())
    assert _snapshot(entries=()).corpus_digest == compute_corpus_digest(())


# --- T6/T7 · semântica da data de referência ------------------------------


def test_reference_date_always_participates_in_the_snapshot_id() -> None:
    """Decisão explícita (T7): a data é variável experimental, não detalhe.

    Mesmo quando o corpus observado coincide, duas medições com datas de
    referência diferentes **não** são a mesma experiência: a coincidência é
    contingente e deixaria de valer noutra data. O corpus continua comparável
    por ``corpus_digest``, que deliberadamente não inclui a data — é essa
    separação que permite afirmar "mesmo corpus, contexto diferente".
    """
    first = _snapshot(reference_date=date(2026, 8, 13))
    second = _snapshot(reference_date=date(2026, 8, 14))

    assert first.corpus_digest == second.corpus_digest
    assert first.snapshot_id != second.snapshot_id


def test_corpus_digest_ignores_the_reference_date_and_the_configuration() -> None:
    """As duas identidades respondem a perguntas diferentes."""
    baseline = _snapshot()
    other_config = _snapshot(config=_config(top_k=10))

    assert baseline.corpus_digest == other_config.corpus_digest
    assert baseline.snapshot_id != other_config.snapshot_id


# --- T8 · configuração de recuperação -------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"strategy": "dense"}, id="estrategia"),
        pytest.param({"pipeline_version": "lexical_pipeline_v2"}, id="versao-da-pipeline"),
        pytest.param({"scoring_version": "lexical_composite_v2"}, id="versao-do-scoring"),
        pytest.param({"score_kind": "synthetic"}, id="tipo-de-score"),
        pytest.param({"comparable_across_queries": True}, id="comparabilidade"),
        pytest.param({"language": "en"}, id="idioma"),
        pytest.param({"top_k": 10}, id="top-k"),
        pytest.param({"official_only": False}, id="official-only"),
        pytest.param({"fts_config": "english"}, id="fts-config"),
        pytest.param({"min_relevance_score": 0.10}, id="limiar"),
        pytest.param({"candidate_limit": 50}, id="orcamento-de-candidatos"),
    ],
)
def test_material_retrieval_parameter_changes_the_snapshot_id(overrides: dict) -> None:
    assert _snapshot(config=_config(**overrides)).snapshot_id != _snapshot().snapshot_id


def test_institution_participates_in_the_snapshot_id() -> None:
    """Isolamento: dois locatários nunca partilham identidade experimental."""
    assert _snapshot(institution=OTHER_INSTITUTION).snapshot_id != _snapshot().snapshot_id


def test_schema_version_participates_in_both_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uma mudança de formato tem de mudar a identidade, não colidir com ela.

    A prova é a mutação: fixar apenas a presença da chave no payload não
    demonstraria que ela participa nos digests.
    """
    assert canonical_corpus_payload((_entry(1),))["schema_version"] == SNAPSHOT_SCHEMA_VERSION

    baseline_corpus = compute_corpus_digest((_entry(1),))
    baseline_id = _snapshot(entries=(_entry(1),)).snapshot_id

    monkeypatch.setattr(snapshot_module, "SNAPSHOT_SCHEMA_VERSION", "999")

    assert compute_corpus_digest((_entry(1),)) != baseline_corpus
    assert _snapshot(entries=(_entry(1),)).snapshot_id != baseline_id


# --- T9 · o que não pertence à identidade ---------------------------------


def test_snapshot_payload_carries_no_content_paths_or_credentials() -> None:
    """Minimização: o digest não pode virar canal para conteúdo documental."""
    serialized = canonical_json(_snapshot().as_payload())

    for forbidden in ("storage_path", "extracted_text", "content", "password", "api_key", "token"):
        assert forbidden not in serialized

    # `content_sha256` vive apenas na entrada do chunk digest, nunca no payload.
    assert "content_sha256" not in serialized


def test_corpus_entry_declares_exactly_the_intended_fields() -> None:
    """Conjunto exato: acrescentar um campo à identidade é uma decisão.

    Fixado de propósito, como em ``test_decision_contracts.py``: um campo novo
    muda todos os digests históricos e não deve entrar por distração.
    """
    assert set(_entry(1).canonical()) == {
        "document_id",
        "document_version_id",
        "document_title",
        "source_url",
        "language",
        "official_source",
        "valid_from",
        "valid_until",
        "checksum_sha256",
        "chunk_count",
        "chunk_digest",
    }


def test_retrieval_configuration_declares_exactly_the_intended_fields() -> None:
    assert set(_config().canonical()) == {
        "strategy",
        "pipeline_version",
        "scoring_version",
        "score_kind",
        "comparable_across_queries",
        "language",
        "top_k",
        "official_only",
        "fts_config",
        "min_relevance_score",
        "candidate_limit",
    }


# --- T11 · representação estável dos valores ------------------------------


def test_uuid_representation_is_canonical_and_case_insensitive_on_input() -> None:
    """O mesmo UUID escrito de formas diferentes é a mesma identidade."""
    lowercase = _entry(1, document_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
    uppercase = _entry(1, document_id=UUID("AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"))

    assert lowercase.canonical()["document_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert compute_corpus_digest((lowercase,)) == compute_corpus_digest((uppercase,))


def test_dates_are_serialized_as_iso_and_absence_as_null() -> None:
    entry = _entry(1, valid_from=date(2026, 1, 2), valid_until=None)

    assert entry.canonical()["valid_from"] == "2026-01-02"
    assert entry.canonical()["valid_until"] is None


def test_canonical_json_is_sorted_and_compact() -> None:
    """A serialização de que sai o digest é fixada, não incidental."""
    serialized = canonical_json({"b": 1, "a": {"d": 2, "c": 3}})

    assert serialized == '{"a":{"c":3,"d":2},"b":1}'
    assert not serialized.endswith("\n")


# --- T10/T12 · estabilidade entre processos -------------------------------

_SUBPROCESS_PROBE = """
import sys
from datetime import date
from uuid import UUID

from app.evaluation.snapshot import (
    ChunkIdentity, CorpusEntry, RetrievalConfiguration, build_snapshot, compute_chunk_digest,
)

chunk_digest = compute_chunk_digest((
    ChunkIdentity(0, "0" * 64, "5" * 64, "Regime de avaliação", "paragraph"),
))
entry = CorpusEntry(
    document_id=UUID("00000000-0000-0000-0000-000000000001"),
    document_version_id=UUID("00000000-0000-0000-0000-000000000065"),
    document_title="Regulamento Académico",
    source_url="https://example.invalid/regulamento",
    language="pt",
    official_source=True,
    valid_from=date(2026, 1, 1),
    valid_until=None,
    checksum_sha256="0" * 64,
    chunk_count=1,
    chunk_digest=chunk_digest,
)
config = RetrievalConfiguration(
    strategy="lexical",
    pipeline_version="lexical_pipeline_v1",
    scoring_version="lexical_composite_v1",
    score_kind="lexical_relevance",
    comparable_across_queries=False,
    language="pt",
    top_k=5,
    official_only=True,
    fts_config="portuguese",
    min_relevance_score=0.05,
    candidate_limit=25,
)
snapshot = build_snapshot(
    institution_id=UUID("11111111-1111-1111-1111-111111111111"),
    reference_date=date(2026, 8, 13),
    entries=(entry,),
    retrieval=config,
)
print(snapshot.corpus_digest)
print(snapshot.snapshot_id)
"""


def _run_probe(hash_seed: str) -> tuple[str, str]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    completed = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_PROBE],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    corpus_digest, snapshot_id = completed.stdout.split()
    return corpus_digest, snapshot_id


def test_identity_is_stable_across_processes_and_hash_seeds() -> None:
    """A prova forte de que nada depende do ``hash()`` aleatorizado.

    O Python aleatoriza o hash de strings por processo (``PYTHONHASHSEED``).
    Uma identidade que dependesse da ordem de iteração de um ``set``/``dict``
    ou do ``hash()`` mudaria entre execuções — e passaria despercebida num
    único processo, onde a semente é constante.
    """
    first = _run_probe("0")
    second = _run_probe("12345")
    third = _run_probe("random")

    assert first == second == third


def test_snapshot_modules_never_call_the_builtin_hash() -> None:
    """Barreira estrutural: ``hash()`` não é identidade persistente."""
    tree = ast.parse(inspect.getsource(snapshot_module))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "hash" not in called


def test_snapshot_module_stays_free_of_sqlalchemy_and_settings() -> None:
    """Mantém a garantia de importação do pacote ``app.evaluation``.

    ``app/evaluation/__init__.py`` é executado ao importar
    ``app.evaluation.assets``, e um teste em subprocesso fixa que essa
    importação não carrega ``sqlalchemy`` nem as Settings. O módulo puro tem de
    continuar a poder viver desse lado da fronteira.
    """
    tree = ast.parse(inspect.getsource(snapshot_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            imported.add(node.module)

    forbidden = {
        name
        for name in imported
        if name.startswith(("sqlalchemy", "app.core.config", "app.models", "openai", "fastapi"))
    }
    assert forbidden == set()


# --- T15 · a baseline histórica do Momento 5 não muda ---------------------

MOMENT05_BASELINE = (
    Path(__file__).resolve().parents[2] / "docs" / "relatorios" / "moment-05-baseline-p1.json"
)
MOMENT05_EXPECTED_DIGEST = "75d936182d9b8a675b43da208f04e1e7168c439c1fdbace04a865283731dd345"


def test_moment05_baseline_artifact_is_unchanged() -> None:
    """O Momento 5 v1 é histórico: o snapshot novo é aditivo e paralelo.

    Fixa o valor declarado no artefacto versionado. Se esta asserção falhar, a
    resposta correta **nunca** é atualizar a constante: é investigar o que
    tocou num artefacto histórico.
    """
    payload = json.loads(MOMENT05_BASELINE.read_text(encoding="utf-8"))

    assert payload["report"]["result_digest"] == MOMENT05_EXPECTED_DIGEST
    assert payload["reproducibility"]["result_digest"] == MOMENT05_EXPECTED_DIGEST
