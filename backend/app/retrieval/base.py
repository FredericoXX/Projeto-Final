"""Contratos neutros para estratégias substituíveis de retrieval.

``search`` devolve um :class:`RetrievalResult`: a evidência ordenada, um trace
mínimo e neutro, e a semântica do score. Antes devolvia apenas
``list[Evidence]``, e o trace que o retriever lexical já calculava era
descartado na linha seguinte — o diagnóstico tinha de o ir buscar por
introspeção (``getattr(retriever, "search_with_trace", None)``), o que fazia de
uma capacidade essencial um extra opcional descoberto por acaso.

Nada aqui interpreta o resultado. Não existe um "outcome" agregado: o consumidor
observa ``len(result.evidence)`` e as contagens do trace, e tira as suas
conclusões. Decidir se a evidência **chega** para responder é answerability, que
vive noutro nível e noutra fase.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class RetrievalContext:
    institution_id: UUID
    language: str
    reference_date: date


@dataclass(frozen=True)
class Evidence:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_index: int
    content: str
    score: float
    language: str
    official_source: bool
    source_url: str | None
    valid_from: date | None
    valid_until: date | None


class ScoreKind(StrEnum):
    """Que **família de quantidade** é o ``Evidence.score``.

    Identifica a semântica sem serializar a implementação: os pesos e o limiar
    continuam a viver no código, e duplicá-los aqui só criaria duas fontes de
    verdade. O que o consumidor precisa de saber é como interpretar o número —
    e, sobretudo, como **não** o interpretar.

    ``LEXICAL_RELEVANCE`` — relevância lexical composta e determinística,
    somatório ponderado de sinais de correspondência entre a pergunta e o
    conteúdo. **Não é** uma probabilidade, uma confiança, nem uma probabilidade
    de a resposta estar correta.

    ``DENSE_SIMILARITY`` — similaridade entre o vetor da pergunta e o vetor do
    segmento, sob a métrica declarada pelo modelo de embeddings. **Não é** uma
    probabilidade nem uma confiança, e sobretudo **não é comparável com
    ``LEXICAL_RELEVANCE``**: são quantidades de famílias diferentes, produzidas
    por processos diferentes, e um 0.62 de um lado não significa o mesmo que um
    0.62 do outro. Qualquer combinação das duas exige uma transformação
    explícita, e é por isso que esta família tem nome próprio em vez de reutilizar
    o valor lexical.

    ``SYNTHETIC`` — valor produzido por um duplo para satisfazer o contrato, sem
    significado de relevância. Existe para que um retriever falso não tenha de
    se declarar lexical, o que seria falso.
    """

    LEXICAL_RELEVANCE = "lexical_relevance"
    DENSE_SIMILARITY = "dense_similarity"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class ScoreSemantics:
    """Como interpretar o ``score`` das evidências deste resultado.

    ``version`` identifica a configuração que produziu os valores. Não é
    decorativa: alterar os pesos do ranking muda o significado quantitativo de
    todos os scores, e sem esta identidade a incomparabilidade entre execuções
    seria silenciosa.

    ``comparable_across_queries`` é declarado e não presumido. Para o score
    lexical atual é ``False``, e isso deriva do algoritmo: ``coverage`` é uma
    fração do número de termos **desta** pergunta, e ``exact_phrase``,
    ``ordered`` e ``proximity`` valem 1.0 por construção numa pergunta de um só
    termo. Comparar scores de perguntas diferentes compara sobretudo o
    comprimento das perguntas.

    Não existe um campo "comparável dentro do resultado": seria constante e
    verdadeiro em qualquer estratégia que ordene por score, e um campo que nunca
    varia não informa nada.
    """

    kind: ScoreKind
    version: str
    comparable_across_queries: bool


@dataclass(frozen=True)
class RetrievalTrace:
    """Contagens que qualquer estratégia de recuperação sabe produzir.

    Deliberadamente mínimo. Os motivos de exclusão do retriever lexical
    (``NO_CONTENT_MATCH``, ``INSUFFICIENT_COVERAGE``, ``BELOW_THRESHOLD``) e os
    seus sinais (cobertura, frase exata, proximidade) **não** estão aqui:
    "cobertura" é uma fração de termos correspondidos, e uma estratégia densa
    não tem termos. Promovê-los ao contrato neutro acoplá-lo-ia à estratégia
    atual. Vivem no trace especializado, que uma estratégia declara acrescentando
    campos a esta base.

    ``candidates_evaluated`` — candidatos distintos que chegaram à etapa de
    seleção e ordenação. Uma estratégia densa contaria os vizinhos recuperados;
    uma híbrida, a união dos candidatos das suas pernas.

    ``result_count_before_limit`` — quantos sobreviveram à seleção **antes** do
    corte por ``top_k``. A diferença para ``len(evidence)`` diz se o ``top_k``
    truncou, que de outro modo é indistinguível de não haver mais nada.

    Estas duas contagens são o que separa "nenhum candidato existiu" de "havia
    candidatos e nenhum sobreviveu" — uma distinção que a lista vazia sozinha
    não permite fazer.
    """

    candidates_evaluated: int
    result_count_before_limit: int


@dataclass(frozen=True)
class RetrievalResult:
    """Instantâneo imutável de uma pesquisa.

    ``evidence`` é uma tupla, e não uma lista, porque o resultado descreve uma
    pesquisa que já aconteceu: nada a jusante deve poder reordená-la ou
    acrescentar-lhe itens sem que isso seja visível.

    ``trace`` é sempre um :class:`RetrievalTrace`; uma estratégia pode devolver
    uma subclasse com mais detalhe, que um consumidor especializado estreita por
    ``isinstance``. O que **não** acontece é a capacidade ser opcional: o trace
    genérico está sempre presente.
    """

    evidence: tuple[Evidence, ...]
    trace: RetrievalTrace
    score_semantics: ScoreSemantics


class Retriever(Protocol):
    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> RetrievalResult: ...
