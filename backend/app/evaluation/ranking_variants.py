"""Variantes offline dos pesos do ranking lexical (D4.7).

Módulo **puro**: recebe sinais já calculados e devolve scores. Não fala com a
base de dados, não toca em ``compute_score`` e — como
``app.evaluation.candidate_budget``, ``app.evaluation.ground_truth_identity`` e
``app.evaluation.repooling`` — **não** é reexportado por
``app/evaluation/__init__.py``.

O que varia, e o que não varia
------------------------------

Varia **apenas o vetor de pesos** do somatório. Os sinais são calculados pelo
código de produção (``compute_content_match`` e ``build_features``), o conjunto
de candidatos é o mesmo, a elegibilidade é a mesma, o limiar é o mesmo e a chave
de ordenação é a mesma. Uma variante não pode criar evidência: só pode reordenar
o que a elegibilidade já admitiu.

Porque é que as variantes são renormalizadas
--------------------------------------------

``app.retrieval.reranking`` **exige** que os pesos somem 1,0 e levanta erro se
não somarem. Um vetor que não some 1,0 não é, portanto, uma configuração de
produção possível — testá-lo mediria algo que nunca poderia ser adotado.

Há uma segunda razão, mais importante para a validade do experimento. O limiar
mínimo de relevância é **absoluto** (``retrieval_min_relevance_score``). Zerar um
peso sem renormalizar encolheria todos os scores e poderia empurrar candidatos
para baixo do limiar — a variante passaria a alterar **quem é devolvido**, e não
apenas a ordem. O efeito medido deixaria de ser de ranking e passaria a ser uma
mistura de ranking com corte.

Renormalizar tem um custo que é preciso declarar: remover um sinal aumenta o peso
relativo de **todos** os outros. Uma ablação aqui responde a *"que peso relativo
deve este sinal ter face aos restantes?"*, e não a *"o que acontece se este
termo desaparecer do somatório sem mais nada mudar?"*. É a pergunta certa para
quem quer decidir uma configuração, e é a única que a produção aceitaria.

O que este módulo não faz
-------------------------

Não procura pesos. Não há otimização, nem pesquisa em grelha, nem ajuste por
tentativa e erro contra o *ground truth*: cada vetor é escrito à mão a partir de
uma hipótese nomeada, e o número de vetores é pequeno de propósito. Com doze
perguntas medidas, procurar pesos produziria sobreajustamento e não conhecimento.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.retrieval.reranking import (
    W_COVERAGE,
    W_EXACT_PHRASE,
    W_FTS,
    W_ORDER,
    W_PROXIMITY,
    W_SECTION,
    W_STRATEGY,
    W_STRUCTURE,
    W_TITLE,
    LexicalFeatures,
)

#: Nomes dos nove termos do somatório de ``compute_score``, na ordem em que o
#: código os soma. ``compactness`` e ``length_factor`` não estão aqui porque não
#: são parcelas: a primeira condiciona o bónus estrutural, a segunda multiplica
#: ``fts_norm`` dentro de ``fts_component``.
SIGNAL_NAMES: Final = (
    "coverage",
    "exact_phrase",
    "proximity",
    "ordered",
    "title_overlap",
    "structure_table_row",
    "section_overlap",
    "fts_component",
    "strategy_quality",
)

#: Os pesos de produção, **importados** e nunca copiados. Se algum mudar em
#: ``app.retrieval.reranking``, a baseline deste experimento muda com ele em vez
#: de continuar a descrever uma configuração que já não existe.
PRODUCTION_WEIGHTS: Final[Mapping[str, float]] = {
    "coverage": W_COVERAGE,
    "exact_phrase": W_EXACT_PHRASE,
    "proximity": W_PROXIMITY,
    "ordered": W_ORDER,
    "title_overlap": W_TITLE,
    "structure_table_row": W_STRUCTURE,
    "section_overlap": W_SECTION,
    "fts_component": W_FTS,
    "strategy_quality": W_STRATEGY,
}


class RankingVariantError(ValueError):
    """Vetor de pesos inadmissível. Falhar é obrigatório: um peso negativo ou um
    sinal desconhecido produziria um score plausível e sem significado."""


def signal_values(features: LexicalFeatures) -> dict[str, float]:
    """Valor de cada termo, na forma exata em que entra no somatório.

    ``fts_component`` já traz o amortecimento pelo comprimento, tal como em
    ``compute_score``; separá-los aqui daria ao comprimento um peso próprio que
    o código de produção não lhe dá.
    """
    return {
        "coverage": features.coverage,
        "exact_phrase": features.exact_phrase,
        "proximity": features.proximity,
        "ordered": features.ordered,
        "title_overlap": features.title_overlap,
        "structure_table_row": features.table_row_bonus,
        "section_overlap": features.section_overlap,
        "fts_component": features.fts_norm * features.length_factor,
        "strategy_quality": features.strategy_quality,
    }


def normalise_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Reescala para somar 1,0, que é o que ``reranking`` exige.

    Recusa pesos negativos: o experimento testa a **importância relativa** dos
    sinais, e um peso negativo transformaria um sinal de relevância num sinal de
    penalização — outra hipótese, que esta fase não formula.
    """
    unknown = sorted(set(weights) - set(SIGNAL_NAMES))
    if unknown:
        msg = f"unknown ranking signals: {unknown}"
        raise RankingVariantError(msg)
    negative = sorted(name for name, value in weights.items() if value < 0)
    if negative:
        msg = f"negative weights are out of scope: {negative}"
        raise RankingVariantError(msg)
    complete = {name: float(weights.get(name, 0.0)) for name in SIGNAL_NAMES}
    total = sum(complete.values())
    if total <= 0:
        msg = "the weight vector sums to zero; there would be nothing to rank by"
        raise RankingVariantError(msg)
    return {name: value / total for name, value in complete.items()}


@dataclass(frozen=True)
class RankingVariant:
    """Uma hipótese nomeada, com o vetor de pesos que a exprime."""

    variant_id: str
    label: str
    hypothesis: str
    weights: Mapping[str, float]

    @property
    def normalised(self) -> dict[str, float]:
        return normalise_weights(self.weights)

    def deltas_from_production(self) -> dict[str, float]:
        """Diferença face a produção, **depois** da renormalização.

        É esta a diferença que explica o comportamento observado. Comparar os
        pesos escritos à mão esconderia o efeito da renormalização sobre os
        sinais que a variante nem sequer menciona.
        """
        normalised = self.normalised
        return {
            name: round(normalised[name] - PRODUCTION_WEIGHTS[name], 6)
            for name in SIGNAL_NAMES
            if abs(normalised[name] - PRODUCTION_WEIGHTS[name]) > 1e-12
        }


def score_with(features: LexicalFeatures, weights: Mapping[str, float]) -> float:
    """Score composto sob um vetor de pesos arbitrário, em ``[0, 1]``.

    Com :data:`PRODUCTION_WEIGHTS` tem de devolver exatamente o que
    ``compute_score`` devolve — propriedade fixada por teste. Sem ela, a célula
    de controlo mediria uma reimplementação em vez do ranking de produção.
    """
    values = signal_values(features)
    score = sum(weights[name] * values[name] for name in SIGNAL_NAMES)
    return max(0.0, min(1.0, score))


def with_weight(base: Mapping[str, float], **changes: float) -> dict[str, float]:
    """Cópia de ``base`` com alguns pesos substituídos.

    Existe para que cada variante se leia como o que é — *"produção, mas com este
    sinal a zero"* — em vez de repetir nove números e deixar a diferença por
    encontrar.
    """
    unknown = sorted(set(changes) - set(SIGNAL_NAMES))
    if unknown:
        msg = f"unknown ranking signals: {unknown}"
        raise RankingVariantError(msg)
    return {**base, **changes}
