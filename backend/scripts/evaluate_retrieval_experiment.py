"""Experimento controlado da política de correspondência lexical (D4.3).

Uso (a partir de ``backend/``, com o virtual environment ativo):

    python -m scripts.evaluate_retrieval_experiment \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-seed.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --output ../docs/evaluation/retrieval-experiment-p1-s1.json \
        [--overwrite]

Não altera o retrieval de produção. Executa a mesma pesquisa em seis condições —
três políticas de correspondência × duas condições de conjunto de candidatos — e
compara os resultados com a baseline do D4.2.

Porque existem duas condições de conjunto, e não só variantes
--------------------------------------------------------------

O D4.2 mediu ``Recall@5 = 0`` em seis perguntas e atribuiu-as todas à cobertura
lexical. Mas quatro desses alvos foram classificados ``NEVER_A_CANDIDATE``, e um
alvo que nunca é avaliado não pode ser recuperado por nenhuma alteração à
política de elegibilidade. Sem separar as duas etapas, uma variante que não
melhore nada seria indistinguível de uma variante boa aplicada tarde demais.

``production_quota`` reproduz produção exatamente. ``unbounded`` executa as
mesmas consultas sem quota — não é uma proposta de sistema, é o contrafactual
que torna a atribuição de causa verificável.

Validação embutida
------------------

A célula ``exact_canonical`` × ``production_quota`` **tem** de reproduzir o
artefacto do D4.2 por inteiro — conjunto de perguntas, ranking posicional,
Recall, MRR, nDCG, contagens devolvidas e agregados — e o próprio artefacto do
D4.2 tem de coincidir com o seu ``result_digest``. Se algum destes pontos
falhar, nada é escrito: comparar variantes contra uma baseline mal replicada
produziria deltas que medem a replicação e não a variante.
"""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Text, bindparam, cast, func, literal_column, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.text_normalization import normalize_text
from app.documents.retrievability import (
    RetrievabilityContext,
    RetrievalEligibility,
    latest_processed_version_subquery,
)
from app.evaluation.lexical_variants import (
    MATCHING_EXACT_CANONICAL,
    MATCHING_STEM_NORMALIZED,
    MATCHING_VARIANTS,
    POOL_CONDITIONS,
    POOL_PRODUCTION_QUOTA,
    TermProjection,
    identity_projection,
    variant_content_match,
)
from app.evaluation.results import canonical_json
from app.evaluation.retrieval_metrics import (
    BINARY_RELEVANCE_THRESHOLD,
    K_VALUES,
    PRIMARY_K,
    UNJUDGED_GRADE,
    mean,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.evaluation.snapshot_builder import build_evaluation_snapshot
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.retrieval.eligibility import ExclusionReason, decide_eligibility
from app.retrieval.fts_config import resolve_fts_config
from app.retrieval.lexical import distribute_quotas, global_candidate_limit
from app.retrieval.lexical_normalization import build_lexical_representation
from app.retrieval.query_planning import (
    LexicalQueryStrategy,
    plan_lexical_query,
    uses_advanced_syntax,
)
from app.retrieval.reranking import (
    LexicalCandidate,
    build_features,
    compute_content_match,
    compute_score,
    informative_query_terms,
)

EXPERIMENT_SCHEMA_VERSION: Final = "1"
DIGEST_ALGORITHM: Final = "sha256"

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_SNAPSHOT_MISMATCH: Final = 3
EXIT_BASELINE_MISMATCH: Final = 4
EXIT_OUTPUT_EXISTS: Final = 5

#: Tokenização de palavras, idêntica à de ``lexical_normalization``. Usada só
#: para alinhar a forma acentuada do ``content`` com a forma sem acentos do
#: ``normalized_content``; a representação lexical continua a ser construída
#: pelo código de produção.
_WORD_RE: Final = re.compile(r"[^\W_]+")

#: Dicionário de radicais, na forma literal que ``ts_lexize`` exige: o primeiro
#: argumento é ``regdictionary`` e não texto. É uma constante do código — nunca
#: input — pelo que entra como literal sem risco de injeção.
PORTUGUESE_STEM_DICTIONARY: Final = "'portuguese_stem'::regdictionary"

#: Ordem de preferência entre estratégias quando o mesmo segmento é devolvido
#: por mais do que uma variante de consulta. Espelha ``_better_strategy`` de
#: ``app.retrieval.lexical``, cuja ordem vem de ``STRATEGY_PRIORITY``.
_STRATEGY_RANK: Final[Mapping[LexicalQueryStrategy, int]] = {
    LexicalQueryStrategy.EXACT: 4,
    LexicalQueryStrategy.REDUCED_AND: 3,
    LexicalQueryStrategy.CANONICAL_RELAXED_AND: 2,
    LexicalQueryStrategy.REDUCED_OR: 1,
}


class ExperimentError(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ExperimentError(f"file not found: {path}", EXIT_USAGE) from error
    except json.JSONDecodeError as error:
        raise ExperimentError(f"invalid JSON in {path}: {error}", EXIT_USAGE) from error


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


# ---------------------------------------------------------------------------
# Stemming: obtido do PostgreSQL, nunca reimplementado
# ---------------------------------------------------------------------------


def stem_words_batch(db: Session, words: Iterable[str]) -> dict[str, str]:
    """``palavra -> radical`` segundo ``portuguese_stem``, numa única consulta.

    É o *stemmer* que o próprio índice FTS usa. Uma segunda implementação em
    Python divergiria dele e mediria um sistema que não existe. Palavras que o
    dicionário reduza a nada — as *stopwords* — mapeiam-se em si mesmas, para
    que a projeção nunca colapse termos distintos num vazio comum.
    """
    unique = sorted({word for word in words if word})
    if not unique:
        return {}
    # O cast é obrigatório: ``unnest`` está sobrecarregado e o PostgreSQL não
    # consegue escolher a assinatura a partir de um parâmetro sem tipo.
    words_array = cast(bindparam("words", unique), ARRAY(Text))
    statement = select(
        func.unnest(words_array).label("word"),
        func.ts_lexize(
            literal_column(PORTUGUESE_STEM_DICTIONARY), func.unnest(words_array)
        ).label("lexemes"),
    )
    stems: dict[str, str] = {}
    for word, lexemes in db.execute(statement).all():
        stems[word] = lexemes[0] if lexemes else word
    return stems


def accent_map_for_text(text: str) -> dict[str, str]:
    """``forma sem acentos -> forma acentuada`` **deste texto e de mais nenhum**.

    ``normalized_content`` já perdeu os diacríticos, e é sobre ele que o
    ``search_vector`` e a cobertura trabalham. Para testar BUG-D4.2-01 é preciso
    recuperar a forma acentuada, que só existe no texto original.

    O mapa é **local por construção**. Um índice global do corpus faria um
    segmento herdar o acento de outro segmento onde a palavra por acaso
    aparecesse acentuada, e faria os termos da pergunta serem reacentuados com
    informação do corpus — mediria um corpus fundido em vez do texto corrente.

    A primeira forma acentuada observada **neste texto** vence, o que torna o
    resultado independente da ordem em que as linhas chegam da base. Formas que
    já não tinham diacríticos não entram: projetam-se em si mesmas.
    """
    accents: dict[str, str] = {}
    for token in _WORD_RE.findall(text.casefold()):
        plain = _strip_accents(token)
        if token != plain:
            accents.setdefault(plain, token)
    return accents


def corpus_accented_vocabulary(db: Session, institution_id: UUID) -> set[str]:
    """Todas as formas acentuadas do corpus, só para pedir os radicais de uma vez.

    Reunir o vocabulário **não** é o mesmo que construir o mapa de acentuação: o
    radical de uma palavra é função apenas dela, pelo que pode ser resolvido em
    lote sem que isso faça um segmento herdar informação de outro.
    """
    vocabulary: set[str] = set()
    rows = db.execute(
        select(DocumentChunk.content)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.institution_id == institution_id)
    ).all()
    for (content,) in rows:
        vocabulary.update(_WORD_RE.findall(content.casefold()))
    return vocabulary


def projection_for(
    variant: str,
    *,
    stems: Mapping[str, str],
    query_text: str,
    content_text: str,
) -> TermProjection:
    """A projeção de uma variante para **este** par pergunta/segmento.

    ``stems`` é o mapa global ``palavra -> radical``, que pode ser global sem
    prejuízo: o radical de uma palavra é função apenas dela. Já a **acentuação**
    é lida do texto corrente de cada lado — ver :func:`accent_map_for_text`.
    """
    if variant == MATCHING_EXACT_CANONICAL:
        return identity_projection()

    if variant == MATCHING_STEM_NORMALIZED:
        # Radicais sobre as formas sem acentos que o sistema já persiste: os
        # dois lados usam o mesmo mapa porque nenhum depende de acentuação.
        return TermProjection(
            name=variant, query_mapping=stems, content_mapping=stems
        )

    query_accents = accent_map_for_text(query_text)
    content_accents = accent_map_for_text(content_text)
    return TermProjection(
        name=variant,
        query_mapping={
            plain: stems.get(accented, accented)
            for plain, accented in query_accents.items()
        }
        | {
            word: stem
            for word, stem in stems.items()
            if word not in query_accents
        },
        content_mapping={
            plain: stems.get(accented, accented)
            for plain, accented in content_accents.items()
        }
        | {
            word: stem
            for word, stem in stems.items()
            if word not in content_accents
        },
    )


# ---------------------------------------------------------------------------
# Conjunto de candidatos
# ---------------------------------------------------------------------------


def _candidate_statement(
    ts_query: Any,
    context: RetrievabilityContext,
    quota: int | None,
):
    """Espelha ``PostgresLexicalRetriever._build_statement``.

    A admissibilidade documental continua a vir inteira de
    ``RetrievalEligibility``; o que muda entre condições é apenas o ``LIMIT``.
    """
    latest_processed = latest_processed_version_subquery(context)
    score = func.ts_rank_cd(DocumentChunk.search_vector, ts_query).label("score")
    statement = (
        select(
            DocumentChunk.id.label("chunk_id"),
            Document.id.label("document_id"),
            DocumentChunk.document_version_id.label("document_version_id"),
            Document.title.label("document_title"),
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            DocumentChunk.normalized_content,
            score,
            DocumentChunk.language,
            Document.official_source,
            Document.source_url,
            Document.valid_from,
            Document.valid_until,
            DocumentChunk.page_number,
            DocumentChunk.section_title,
            DocumentChunk.structure_type,
            DocumentChunk.chunking_strategy,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(
            latest_processed,
            (latest_processed.c.version_id == DocumentChunk.document_version_id)
            & (latest_processed.c.document_id == DocumentChunk.document_id),
        )
        .where(
            *RetrievalEligibility.as_sql_filters(context),
            latest_processed.c.rn == 1,
            DocumentChunk.search_vector.op("@@")(ts_query),
        )
        .order_by(
            score.desc(),
            Document.id.asc(),
            DocumentChunk.chunk_index.asc(),
            DocumentChunk.id.asc(),
        )
    )
    if quota is not None:
        statement = statement.limit(quota)
    return statement


def _row_to_candidate(row: Any, strategy: LexicalQueryStrategy) -> LexicalCandidate:
    return LexicalCandidate(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_version_id=row.document_version_id,
        document_title=row.document_title,
        chunk_index=row.chunk_index,
        content=row.content,
        normalized_content=row.normalized_content,
        language=row.language,
        official_source=row.official_source,
        source_url=row.source_url,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        page_number=row.page_number,
        section_title=row.section_title,
        structure_type=row.structure_type,
        chunking_strategy=row.chunking_strategy,
        raw_score=float(row.score),
        strategy=strategy,
    )


def collect_candidates(
    db: Session,
    *,
    normalized_query: str,
    context: RetrievabilityContext,
    language: str,
    top_k: int,
    pool: str,
) -> tuple[list[LexicalCandidate], list[dict[str, Any]]]:
    """Candidatos e o traço das variantes de consulta, para a condição pedida."""
    fts_config = resolve_fts_config(language)
    plan = plan_lexical_query(normalized_query, language)
    quotas: Sequence[int | None]
    if pool == POOL_PRODUCTION_QUOTA:
        quotas = distribute_quotas(global_candidate_limit(top_k), len(plan.variants))
    else:
        quotas = [None] * len(plan.variants)

    candidates: dict[Any, LexicalCandidate] = {}
    variant_trace: list[dict[str, Any]] = []
    for variant, quota in zip(plan.variants, quotas, strict=True):
        if quota == 0:
            variant_trace.append(
                {"strategy": variant.strategy.value, "quota": 0, "returned_count": 0}
            )
            continue
        ts_query = func.websearch_to_tsquery(fts_config.value, variant.websearch_input)
        rows = db.execute(_candidate_statement(ts_query, context, quota)).all()
        variant_trace.append(
            {
                "strategy": variant.strategy.value,
                "quota": quota,
                "returned_count": len(rows),
            }
        )
        for row in rows:
            existing = candidates.get(row.chunk_id)
            if existing is None:
                candidates[row.chunk_id] = _row_to_candidate(row, variant.strategy)
                continue
            better = (
                variant.strategy
                if _STRATEGY_RANK[variant.strategy] > _STRATEGY_RANK[existing.strategy]
                else existing.strategy
            )
            candidates[row.chunk_id] = LexicalCandidate(
                **{
                    **existing.__dict__,
                    "strategy": better,
                    "raw_score": max(existing.raw_score, float(row.score)),
                }
            )
    return list(candidates.values()), variant_trace


# ---------------------------------------------------------------------------
# Reranking com a variante injetada
# ---------------------------------------------------------------------------


def rank_with_variant(
    *,
    question_text: str,
    normalized_query: str,
    candidates: Sequence[LexicalCandidate],
    language: str,
    variant: str,
    stems: Mapping[str, str],
    top_k: int,
) -> tuple[list[LexicalCandidate], dict[str, int]]:
    """Aplica elegibilidade e ordenação de produção sobre a correspondência da variante.

    ``decide_eligibility``, ``build_features`` e ``compute_score`` são os de
    produção e não são tocados. A ordenação replica ``_ranking_key``.

    A projeção é construída **por candidato**, e não uma vez para toda a
    execução: a variante que restitui acentos tem de ler o texto acentuado
    daquele segmento, e não de um qualquer outro onde a palavra apareça.
    """
    query_terms = informative_query_terms(normalized_query, language)
    explicit_syntax = uses_advanced_syntax(normalized_query)
    excluded_counts = {reason.value: 0 for reason in ExclusionReason}

    scored: list[tuple[tuple[Any, ...], LexicalCandidate]] = []
    for candidate in candidates:
        base = compute_content_match(query_terms, candidate)
        representation = build_lexical_representation(
            candidate.normalized_content, candidate.language
        )
        projection = projection_for(
            variant,
            stems=stems,
            query_text=question_text,
            content_text=candidate.content,
        )
        match = variant_content_match(
            base=base,
            query_terms=query_terms,
            representation=representation,
            projection=projection,
        )
        decision = decide_eligibility(
            query_terms, match, candidate.strategy, explicit_syntax=explicit_syntax
        )
        if not decision.eligible:
            reason = decision.reason or ExclusionReason.NO_CONTENT_MATCH
            excluded_counts[reason.value] += 1
            continue
        features = build_features(query_terms, candidate, match)
        score = compute_score(features)
        if score < settings.retrieval_min_relevance_score:
            excluded_counts[ExclusionReason.BELOW_THRESHOLD.value] += 1
            continue
        key = (
            -score,
            -features.coverage,
            -features.strategy_quality,
            -candidate.raw_score,
            str(candidate.document_id),
            candidate.chunk_index,
            str(candidate.chunk_id),
        )
        scored.append((key, candidate))

    scored.sort(key=lambda item: item[0])
    return [candidate for _, candidate in scored[:top_k]], excluded_counts


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------


def judged_grade_index(
    question: Mapping[str, Any], document_index: Mapping[str, str]
) -> dict[tuple[str, int], int]:
    return {
        (document_index[judgment["corpus_item_id"]], judgment["chunk_index"]): judgment[
            "relevance"
        ]
        for judgment in question["evidence_judgments"]
    }


def evaluate_cell(
    db: Session,
    *,
    questions: Sequence[Mapping[str, Any]],
    document_index: Mapping[str, str],
    context: RetrievabilityContext,
    language: str,
    top_k: int,
    variant: str,
    stems: Mapping[str, str],
    pool: str,
) -> dict[str, Any]:
    """Uma célula do desenho: uma política de correspondência × uma condição de conjunto."""
    per_question: list[dict[str, Any]] = []
    recalls: dict[int, list[float]] = {k: [] for k in K_VALUES}
    ndcgs: dict[int, list[float]] = {k: [] for k in K_VALUES}
    reciprocal_ranks: list[float] = []

    for question in questions:
        normalized_query = normalize_text(question["question"])
        candidates, variant_trace = collect_candidates(
            db,
            normalized_query=normalized_query,
            context=context,
            language=language,
            top_k=top_k,
            pool=pool,
        )
        returned, excluded_counts = rank_with_variant(
            question_text=question["question"],
            normalized_query=normalized_query,
            candidates=candidates,
            language=language,
            variant=variant,
            stems=stems,
            top_k=top_k,
        )
        grades = judged_grade_index(question, document_index)
        retrieved_grades = [
            grades.get((str(candidate.document_id), candidate.chunk_index), UNJUDGED_GRADE)
            for candidate in returned
        ]
        judged_grades = [
            judgment["relevance"] for judgment in question["evidence_judgments"]
        ]
        total_relevant = sum(
            1 for grade in judged_grades if grade >= BINARY_RELEVANCE_THRESHOLD
        )
        distractors = sum(
            1
            for candidate in returned
            if grades.get((str(candidate.document_id), candidate.chunk_index)) == 0
        )
        unjudged = sum(
            1
            for candidate in returned
            if (str(candidate.document_id), candidate.chunk_index) not in grades
        )

        record: dict[str, Any] = {
            "question_id": question["question_id"],
            "candidates_evaluated": len(candidates),
            "variants": variant_trace,
            "excluded_counts": excluded_counts,
            "retrieved_count": len(returned),
            "retrieved_grades": retrieved_grades,
            "judged_distractors_returned": distractors,
            "unjudged_returned": unjudged,
            "ranking": [
                {
                    "position": position,
                    "corpus_item_id": _corpus_item_for(
                        str(candidate.document_id), document_index
                    ),
                    "chunk_index": candidate.chunk_index,
                    "grade": grades.get(
                        (str(candidate.document_id), candidate.chunk_index),
                        UNJUDGED_GRADE,
                    ),
                    "judged": (str(candidate.document_id), candidate.chunk_index)
                    in grades,
                }
                for position, candidate in enumerate(returned, start=1)
            ],
        }

        measurable = (
            not question["no_relevant_evidence"]
            and not question["excluded_from_metrics"]
            and total_relevant > 0
        )
        if measurable:
            record["recall"] = {
                str(k): round(recall_at_k(retrieved_grades, total_relevant, k), 6)
                for k in K_VALUES
            }
            record["reciprocal_rank"] = round(reciprocal_rank(retrieved_grades), 6)
            record["ndcg"] = {
                str(k): round(ndcg_at_k(retrieved_grades, judged_grades, k), 6)
                for k in K_VALUES
            }
            for k in K_VALUES:
                recalls[k].append(recall_at_k(retrieved_grades, total_relevant, k))
                ndcgs[k].append(ndcg_at_k(retrieved_grades, judged_grades, k))
            reciprocal_ranks.append(reciprocal_rank(retrieved_grades))
        else:
            record["measured"] = False
        per_question.append(record)

    aggregate = {
        "questions_measured": len(reciprocal_ranks),
        "recall": {str(k): round(mean(recalls[k]), 6) for k in K_VALUES},
        "mrr": round(mean(reciprocal_ranks), 6),
        "ndcg": {str(k): round(mean(ndcgs[k]), 6) for k in K_VALUES},
    }
    return {
        "matching_variant": variant,
        "pool_condition": pool,
        "aggregate": aggregate,
        "question_results": per_question,
    }


def _corpus_item_for(document_id: str, document_index: Mapping[str, str]) -> str | None:
    for item, identifier in document_index.items():
        if identifier == document_id:
            return item
    return None


def verify_snapshot(
    db: Session,
    *,
    ground_truth: Mapping[str, Any],
    binding: Mapping[str, Any],
    language: str,
    top_k: int,
    official_only: bool,
) -> None:
    snapshot = build_evaluation_snapshot(
        db,
        institution_id=UUID(binding["institution_id"]),
        language=language,
        reference_date=date.fromisoformat(ground_truth["reference_date"]),
        top_k=top_k,
        official_only=official_only,
    )
    problems = []
    if snapshot.snapshot_id != ground_truth["snapshot_id"]:
        problems.append(f"snapshot_id {snapshot.snapshot_id}")
    if snapshot.corpus_digest != ground_truth["corpus_digest"]:
        problems.append(f"corpus_digest {snapshot.corpus_digest}")
    if problems:
        raise ExperimentError(
            "the corpus no longer matches S1; the experiment would not be "
            "comparable with the D4.2 baseline: " + "; ".join(problems),
            EXIT_SNAPSHOT_MISMATCH,
        )


def _close(got: float, want: float) -> bool:
    return abs(got - want) <= 1e-9


def _ranking_signature(entries: Sequence[Mapping[str, Any]]) -> list[tuple[Any, ...]]:
    """Identidade posicional do resultado, para comparação entre execuções."""
    return [
        (entry["position"], entry["corpus_item_id"], entry["chunk_index"])
        for entry in entries
    ]


def verify_baseline_replication(
    cell: Mapping[str, Any], baseline: Mapping[str, Any]
) -> list[str]:
    """A célula de controlo tem de reproduzir o D4.2 — **inteiro**.

    Uma versão anterior desta guarda comparava apenas o Recall das perguntas que
    ambos os lados tivessem medido. Isso deixava passar uma célula vazia, uma
    célula sem perguntas, ou uma célula com ranking, MRR e nDCG adulterados: o
    conjunto de comparação era ele próprio derivado do que a célula continha.

    A guarda compara agora o **conjunto** de perguntas, o **ranking** posicional,
    as três métricas por pergunta e o número de resultados devolvidos — incluindo
    das perguntas sem métrica, como a que não tem evidência relevante. Uma
    diferença em qualquer um destes pontos invalida a comparação com as
    variantes, porque os deltas passariam a medir a replicação e não a variante.
    """
    problems: list[str] = []

    # O D4.2 separa em duas listas: as perguntas medidas e as que só produzem
    # observações (sem evidência relevante, ou excluídas das métricas). Aqui
    # convivem numa só, e a guarda tem de cobrir ambas — foi precisamente por
    # ignorar a segunda que a versão anterior deixava passar células vazias.
    reference_by_id = {
        result["question_id"]: result
        for result in [*baseline["question_results"], *baseline.get("observed_only", [])]
    }
    cell_by_id = {result["question_id"]: result for result in cell["question_results"]}

    missing = sorted(set(reference_by_id) - set(cell_by_id))
    extra = sorted(set(cell_by_id) - set(reference_by_id))
    if missing:
        problems.append(f"questions missing from the control cell: {missing}")
    if extra:
        problems.append(f"questions absent from the baseline: {extra}")

    for question_id in sorted(set(reference_by_id) & set(cell_by_id)):
        reference = reference_by_id[question_id]
        result = cell_by_id[question_id]

        if result["retrieved_count"] != reference["retrieved_count"]:
            problems.append(
                f"{question_id} retrieved_count {result['retrieved_count']} "
                f"!= baseline {reference['retrieved_count']}"
            )

        got_ranking = _ranking_signature(result["ranking"])
        want_ranking = _ranking_signature(reference["ranking"])
        if got_ranking != want_ranking:
            problems.append(f"{question_id} ranking {got_ranking} != baseline {want_ranking}")

        measured_here = "recall" in result
        measured_there = "recall" in reference
        if measured_here != measured_there:
            problems.append(
                f"{question_id} measured={measured_here} but baseline "
                f"measured={measured_there}"
            )
            continue
        if not measured_here:
            continue

        for k in K_VALUES:
            for metric in ("recall", "ndcg"):
                got = result[metric][str(k)]
                want = reference[metric][str(k)]
                if not _close(got, want):
                    problems.append(
                        f"{question_id} {metric}@{k} {got} != baseline {want}"
                    )
        if not _close(result["reciprocal_rank"], reference["reciprocal_rank"]):
            problems.append(
                f"{question_id} reciprocal_rank {result['reciprocal_rank']} "
                f"!= baseline {reference['reciprocal_rank']}"
            )

    aggregate = cell["aggregate"]
    reference_aggregate = baseline["aggregate"]
    if aggregate["questions_measured"] != reference_aggregate["questions_measured"]:
        problems.append(
            f"questions_measured {aggregate['questions_measured']} "
            f"!= baseline {reference_aggregate['questions_measured']}"
        )
    if not _close(aggregate["mrr"], reference_aggregate["mrr"]):
        problems.append(
            f"aggregate mrr {aggregate['mrr']} != baseline {reference_aggregate['mrr']}"
        )
    for k in K_VALUES:
        for metric in ("recall", "ndcg"):
            got = aggregate[metric][str(k)]
            want = reference_aggregate[metric][str(k)]
            if not _close(got, want):
                problems.append(
                    f"aggregate {metric}@{k} {got} != baseline {want}"
                )
    return problems


def verify_baseline_integrity(baseline: dict[str, Any]) -> None:
    """O artefacto do D4.2 tem de ser aquele que o seu próprio digest declara.

    Sem isto, a guarda de replicação compararia contra um ficheiro possivelmente
    editado à mão — e passaria, porque ambos os lados estariam errados da mesma
    maneira.
    """
    declared = baseline.get("result_digest")
    if not declared:
        raise ExperimentError(
            "the baseline artefact has no result_digest", EXIT_BASELINE_MISMATCH
        )
    payload = {
        key: value
        for key, value in baseline.items()
        if key not in {"result_digest", "executed_at"}
    }
    recomputed = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    if recomputed != declared:
        raise ExperimentError(
            "the baseline artefact does not match its own result_digest "
            f"(declared {declared}, recomputed {recomputed}); it was modified "
            "after being produced and cannot serve as a reference",
            EXIT_BASELINE_MISMATCH,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except ExperimentError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code


def _run(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        raise ExperimentError(
            f"refusing to overwrite {args.output} without --overwrite", EXIT_OUTPUT_EXISTS
        )

    ground_truth = _load_json(args.ground_truth)
    binding = _load_json(args.binding)
    baseline = _load_json(args.baseline)
    verify_baseline_integrity(baseline)

    retrieval = baseline["retrieval"]
    language = retrieval["language"]
    top_k = retrieval["top_k"]
    official_only = retrieval["official_only"]
    institution_id = UUID(binding["institution_id"])

    document_index = {
        item["corpus_item_id"]: item["document_id"]
        for item in binding["items"]
        if item.get("in_corpus")
    }
    questions = ground_truth["questions"]

    with SessionLocalFactory() as db:
        verify_snapshot(
            db,
            ground_truth=ground_truth,
            binding=binding,
            language=language,
            top_k=top_k,
            official_only=official_only,
        )
        context = RetrievabilityContext(
            institution_id=institution_id,
            language=language,
            reference_date=date.fromisoformat(ground_truth["reference_date"]),
            official_only=official_only,
        )

        # Vocabulário só para pedir radicais em lote. Inclui as formas com e sem
        # acentos, da pergunta e do corpus; qual delas é usada de cada lado é
        # decidido depois, por texto, em ``projection_for``.
        vocabulary: set[str] = corpus_accented_vocabulary(db, institution_id)
        rows = db.execute(
            select(DocumentChunk.normalized_content)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.institution_id == institution_id)
        ).all()
        for (normalized,) in rows:
            vocabulary.update(_WORD_RE.findall(normalized))
        for question in questions:
            vocabulary.update(_WORD_RE.findall(question["question"].casefold()))
            vocabulary.update(_WORD_RE.findall(normalize_text(question["question"])))

        stems = stem_words_batch(db, vocabulary)

        cells = [
            evaluate_cell(
                db,
                questions=questions,
                document_index=document_index,
                context=context,
                language=language,
                top_k=top_k,
                variant=variant,
                stems=stems,
                pool=pool,
            )
            for pool in POOL_CONDITIONS
            for variant in MATCHING_VARIANTS
        ]

    control = next(
        cell
        for cell in cells
        if cell["matching_variant"] == MATCHING_EXACT_CANONICAL
        and cell["pool_condition"] == POOL_PRODUCTION_QUOTA
    )
    replication_problems = verify_baseline_replication(control, baseline)
    if replication_problems:
        raise ExperimentError(
            "the control cell does not reproduce the D4.2 baseline: "
            + "; ".join(replication_problems),
            EXIT_BASELINE_MISMATCH,
        )

    payload: dict[str, Any] = {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "corpus_id": ground_truth["corpus_id"],
        "snapshot_id": ground_truth["snapshot_id"],
        "corpus_digest": ground_truth["corpus_digest"],
        "reference_date": ground_truth["reference_date"],
        "baseline_result_digest": baseline["result_digest"],
        "control_reproduces_baseline": True,
        "retrieval": retrieval,
        "matching_variants": list(MATCHING_VARIANTS),
        "pool_conditions": list(POOL_CONDITIONS),
        "primary_k": PRIMARY_K,
        "cells": cells,
    }
    payload["result_digest"] = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    payload["executed_at"] = datetime.now(UTC).isoformat()

    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for cell in cells:
        aggregate = cell["aggregate"]
        print(
            f"{cell['matching_variant']:18s} {cell['pool_condition']:17s} "
            f"R@5={aggregate['recall']['5']:.4f} MRR={aggregate['mrr']:.4f} "
            f"nDCG@5={aggregate['ndcg']['5']:.4f}"
        )
    print(f"result_digest : {payload['result_digest']}")
    print(f"written       : {args.output}")
    return EXIT_OK


def SessionLocalFactory() -> Session:  # noqa: N802 - fábrica, mantida injetável
    from app.database.session import SessionLocal

    return SessionLocal()


if __name__ == "__main__":
    sys.exit(main())
