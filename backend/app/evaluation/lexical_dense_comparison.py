"""Comparação definitiva C0 (lexical) × C1 (denso) sobre o mesmo ground truth (D4.8.1).

Módulo **puro**: recebe rankings já produzidos e julgamentos já resolvidos, e
devolve estruturas. Não fala com a base de dados, não lê ficheiros e — como
``app.evaluation.dense_baseline``, ``retrieval_metrics``, ``repooling`` e
``ground_truth_identity`` — **não** é reexportado por ``app/evaluation/__init__.py``.

O que este módulo acrescenta ao ``dense_baseline``
--------------------------------------------------

O D4.8 mediu as duas condições contra um conjunto de julgamentos em que 31
resultados do top 5 — **todos de C1** — nunca tinham sido vistos por um
anotador. Sob ``ASSUMED_IRRELEVANT`` cada um contava grau 0, pelo que as
métricas de C1 eram provisórias por construção. Depois do repooling essa
ressalva desapareceu, e o que sobra é a pergunta que a fase existe para
responder: **as duas condições falham nos mesmos sítios, ou em sítios
diferentes?**

A distinção que dá sentido à resposta
--------------------------------------

Duas condições podem devolver conjuntos diferentes sem que isso signifique
nada. O que se mede aqui separa dois casos que uma taxa de sobreposição
confunde:

- **complementaridade real** — um alvo de grau 2 que entra no top 5 de *uma* das
  condições e não da outra. Uma condição encontra evidência julgada que a outra
  não encontra;
- **diferença de ranking** — um alvo de grau 2 que entra no top 5 das *duas*,
  em posições diferentes. Ambas encontram a mesma evidência; uma ordena-a
  melhor. Isto **não** é complementaridade, e contá-lo como tal inflacionaria o
  argumento a favor de uma arquitetura híbrida.

A segunda classe é reportada à parte precisamente porque é a que uma leitura
apressada dos agregados transformaria na primeira.

Os dois digests do artefacto
----------------------------

O fornecedor de embeddings não é bit a bit determinístico e C1 embebe a pergunta
a cada execução, pelo que duas execuções dão rankings, graus e métricas
idênticos e similaridades ligeiramente diferentes. O artefacto declara por isso
dois digests, e o **canónico descreve o resultado, não a execução**:
``result_digest`` sobre :func:`result_projection`, estável; ``execution_digest``
sobre :func:`execution_projection`, que muda com a deriva e é o que a torna
detetável. Ambos vêm de :func:`artefact_digests` — ver a discussão lá.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.evaluation.dense_baseline import (
    CONDITION_DENSE,
    CONDITION_LEXICAL,
    PoolItem,
)
from app.evaluation.results import canonical_json

#: Âmbito do ``result_digest``: a projeção de :func:`result_projection`, sem as
#: quantidades que o fornecedor não reproduz. Gravado no artefacto ao lado do
#: digest para que este se descreva a si próprio — a mesma convenção que
#: ``GROUND_TRUTH_DIGEST_SCOPE``.
RESULT_DIGEST_SCOPE: Final = "provider_independent_fields"

#: Âmbito do ``execution_digest``: o *payload* como foi escrito, tirando apenas
#: ``executed_at`` e o próprio campo.
EXECUTION_DIGEST_SCOPE: Final = "full_payload"

#: Chaves do bloco ``no_evidence_questions`` que transportam similaridade bruta.
_SIMILARITY_KEYS: Final = frozenset(
    {
        "similarity_top",
        "similarity_bottom",
        "other_questions_top_similarity_min",
        "other_questions_top_similarity_max",
    }
)

#: Campos do topo que descrevem a execução e não o resultado.
_RUN_KEYS: Final = frozenset({"executed_at", "result_digest", "execution_digest"})

#: Campos que o ``execution_digest`` não pode cobrir: o instante da execução, que
#: muda sempre, e ele próprio.
_EXECUTION_DIGEST_EXCLUDED: Final = frozenset({"executed_at", "execution_digest"})


#: Destino de um alvo de grau 2 na união dos dois top 5.
BOTH: Final = "both"
C0_ONLY: Final = "c0_only"
C1_ONLY: Final = "c1_only"
NEITHER: Final = "neither"

#: Classificação de uma pergunta medida. "Resolvida" é ter pelo menos um alvo de
#: grau 2 no top 5 — o mesmo critério que dá ``reciprocal_rank > 0``, e não
#: Recall@5 == 1, que exigiria recuperar *todos* os alvos e classificaria como
#: falhada uma pergunta cuja resposta foi encontrada.
SOLVED_BY_BOTH: Final = "solved_by_both"
SOLVED_BY_C0_ONLY: Final = "solved_by_c0_only"
SOLVED_BY_C1_ONLY: Final = "solved_by_c1_only"
SOLVED_BY_NEITHER: Final = "solved_by_neither"


@dataclass(frozen=True)
class TargetOutcome:
    """Onde um alvo de grau 2 caiu em cada condição.

    ``rank_c0``/``rank_c1`` são ``None`` quando a condição não o devolveu no top
    ``k``. O destino deriva dos dois, e não é declarado à parte, para que não
    possa divergir deles.
    """

    corpus_item_id: str
    chunk_index: int
    rank_c0: int | None
    rank_c1: int | None

    @property
    def destination(self) -> str:
        if self.rank_c0 is not None and self.rank_c1 is not None:
            return BOTH
        if self.rank_c0 is not None:
            return C0_ONLY
        if self.rank_c1 is not None:
            return C1_ONLY
        return NEITHER

    @property
    def is_real_complementarity(self) -> bool:
        """Recuperado por exatamente uma das condições."""
        return self.destination in (C0_ONLY, C1_ONLY)

    @property
    def is_ranking_difference(self) -> bool:
        """Recuperado por ambas, em posições diferentes.

        Deliberadamente **falso** quando o destino é exclusivo: um alvo que só
        uma condição devolve é complementaridade, não ordenação, e somar as duas
        contagens tem de dar a mesma coisa que contar os alvos uma vez.
        """
        return self.destination == BOTH and self.rank_c0 != self.rank_c1


def rank_of(item: PoolItem, pool: Sequence[PoolItem]) -> int | None:
    """Posição de ``item`` em ``pool``, 1-indexada, ou ``None`` se ausente."""
    for position, candidate in enumerate(pool, start=1):
        if candidate == item:
            return position
    return None


def target_outcomes(
    targets: Sequence[PoolItem],
    c0_pool: Sequence[PoolItem],
    c1_pool: Sequence[PoolItem],
) -> tuple[TargetOutcome, ...]:
    """Destino de cada alvo de grau 2, na ordem canónica dos alvos."""
    return tuple(
        TargetOutcome(
            corpus_item_id=target.corpus_item_id,
            chunk_index=target.chunk_index,
            rank_c0=rank_of(target, c0_pool),
            rank_c1=rank_of(target, c1_pool),
        )
        for target in sorted(targets)
    )


def classify_question(reciprocal_rank_c0: float, reciprocal_rank_c1: float) -> str:
    """Qual das condições resolveu a pergunta.

    Um ``reciprocal_rank`` positivo é, por definição do protocolo, a existência
    de um alvo de grau 2 no top ``k``.
    """
    solved_c0 = reciprocal_rank_c0 > 0.0
    solved_c1 = reciprocal_rank_c1 > 0.0
    if solved_c0 and solved_c1:
        return SOLVED_BY_BOTH
    if solved_c0:
        return SOLVED_BY_C0_ONLY
    if solved_c1:
        return SOLVED_BY_C1_ONLY
    return SOLVED_BY_NEITHER


def favoured_condition(
    metrics_c0: Mapping[str, Any], metrics_c1: Mapping[str, Any], primary_k: int
) -> str | None:
    """Condição favorecida numa pergunta, ou ``None`` se empatarem.

    Decide por nDCG@k primário, que é a única das três métricas do protocolo
    sensível **ao mesmo tempo** à recuperação e à ordenação: o Recall ignora a
    posição e o MRR ignora tudo o que venha depois do primeiro acerto. Uma
    pergunta em que as duas condições recuperam o mesmo alvo em posições
    diferentes tem de aparecer como favorecida por alguém, e só o nDCG o mostra.
    """
    ndcg_c0 = float(metrics_c0["ndcg"][str(primary_k)])
    ndcg_c1 = float(metrics_c1["ndcg"][str(primary_k)])
    if ndcg_c0 > ndcg_c1:
        return CONDITION_LEXICAL
    if ndcg_c1 > ndcg_c0:
        return CONDITION_DENSE
    return None


def grade_histogram(ranking: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Distribuição dos graus de um ranking, com todos os graus presentes.

    As três chaves existem sempre, mesmo a zero: um histograma que omite o grau
    ausente obriga quem lê o artefacto a distinguir «zero» de «não medido».
    """
    histogram = {"0": 0, "1": 0, "2": 0}
    for entry in ranking:
        histogram[str(int(entry["grade"]))] += 1
    return histogram


# ---------------------------------------------------------------------------
# Reprodutibilidade
# ---------------------------------------------------------------------------


def result_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Projeção de que se deriva o ``result_digest``: o resultado, sem a deriva.

    Porque é que esta projeção existe
    ---------------------------------

    O D4.8 mediu (§8.1) que embeber **o mesmo texto** com o mesmo modelo e a
    mesma configuração produz vetores diferentes, na ordem de 1e-4 na
    similaridade do cosseno. O mesmo vale para a pergunta, que C1 embebe a cada
    execução: duas execuções desta fase produzem rankings, graus e métricas
    idênticos e **similaridades ligeiramente diferentes**.

    Um digest calculado sobre o *payload* inteiro seria, por isso, instável
    entre execuções — não por defeito desta fase, mas por propriedade do
    fornecedor. Havia três saídas, e duas são inaceitáveis: arredondar mais o
    score esconderia a deriva, e retirá-lo do artefacto perderia informação que a
    análise de Q013 usa.

    A terceira é a implementada: **o `result_digest` descreve o resultado, não a
    execução.**

    - ``result_digest`` — esta projeção. É o digest canónico do artefacto e
      **tem** de ser idêntico entre execuções sobre o mesmo índice e o mesmo
      *ground truth*. É a ele que a afirmação «a experiência é reprodutível» se
      refere, e é ele que uma fase seguinte cita para dizer «medi contra este
      resultado»;
    - ``execution_digest`` — o *payload* como foi escrito, similaridades
      incluídas. **Muda** com a deriva do fornecedor, e é isso que o torna útil:
      é o que deteta que os vetores não são os mesmos. A deriva fica preservada
      e visível, em vez de arredondada para fora.

    O que a projeção retira, e o que deliberadamente mantém
    -------------------------------------------------------

    Retira apenas a **similaridade bruta de C1** — nos rankings e no bloco da
    pergunta sem evidência — e os campos que descrevem a execução
    (``executed_at`` e os dois digests).

    Mantém o score de **C0**: o ranking lexical corre inteiramente local e é
    determinístico, pelo que uma alteração nele é sinal e não ruído. Mantém
    também a **posição** de cada resultado de C1, o seu grau e todas as
    métricas: é sobre esses que a comparação se pronuncia.
    """
    projection = {key: value for key, value in payload.items() if key not in _RUN_KEYS}
    projection["question_results"] = [
        _project_question(record) for record in payload["question_results"]
    ]
    projection["no_evidence_questions"] = [
        {key: value for key, value in question.items() if key not in _SIMILARITY_KEYS}
        for question in payload["no_evidence_questions"]
    ]
    return projection


def execution_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Projeção de que se deriva o ``execution_digest``: tudo menos o instante.

    Existe como função, e não como um ``dict`` inline no runner, porque a
    verificação de integridade do artefacto tem de usar **a mesma** definição
    que o produziu. Um artefacto com dois digests não é verificável pela guarda
    genérica de digest único (``verify_baseline_integrity``), que assume a
    convenção de um só; quem consumir este artefacto tem de usar
    :func:`artefact_digests`.
    """
    return {
        key: value
        for key, value in payload.items()
        if key not in _EXECUTION_DIGEST_EXCLUDED
    }


def artefact_digests(payload: Mapping[str, Any]) -> tuple[str, str]:
    """``(result_digest, execution_digest)`` de um *payload* desta fase.

    Definição única, usada pelo runner para os produzir e por quem consome o
    artefacto para os verificar. Duas implementações paralelas da mesma regra é
    precisamente a forma de uma delas passar a descrever outra coisa.

    A ordem não é arbitrária
    ------------------------

    O ``execution_digest`` cobre o *payload* **como fica escrito**, e o
    ``result_digest`` é um dos campos escritos. Por isso ele é carimbado no
    *payload* **antes** de o segundo digest ser calculado.

    Sem este passo a função não seria idempotente: no runner correria sobre um
    *payload* ainda sem ``result_digest`` e na verificação sobre um que já o tem,
    e os dois valores nunca coincidiriam — um artefacto válido pareceria
    adulterado. Há teste que recalcula ambos a partir do ficheiro escrito.
    """
    result = hashlib.sha256(
        canonical_json(result_projection(payload)).encode("utf-8")
    ).hexdigest()
    stamped = {**payload, "result_digest": result}
    execution = hashlib.sha256(
        canonical_json(execution_projection(stamped)).encode("utf-8")
    ).hexdigest()
    return result, execution


def _project_question(record: Mapping[str, Any]) -> dict[str, Any]:
    conditions = dict(record["conditions"])
    dense = dict(conditions[CONDITION_DENSE])
    dense["ranking"] = [
        {key: value for key, value in entry.items() if key != "score"}
        for entry in dense["ranking"]
    ]
    conditions[CONDITION_DENSE] = dense
    return {**record, "conditions": conditions}
