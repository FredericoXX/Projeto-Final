"""Política de admissibilidade da evidência documental (issue #24, Fase 1).

Uma lista concreta de condições nomeadas, com **dois adaptadores** — filtros
SQL para o PostgreSQL e veredicto explicado para Python — e **duas composições
nomeadas**. Não é um motor genérico de *specification objects*: não há registo
dinâmico, herança nem combinadores. O que existe é uma definição semântica
única por condição, servida em duas formas.

Estado nesta fase: o módulo existe e é testado, mas **nenhum consumidor o
usa**. A adoção por ``app.retrieval.lexical``,
``app.services.message_source_service`` e ``app.diagnostics.document_pipeline``
pertence às Fases 2 a 4 da issue #24.

Direção da dependência
----------------------

Este módulo **não importa nada de ``app.retrieval``**, e não deve passar a
importar. A dependência pretendida é ``retrieval -> documents.retrievability``,
para que uma estratégia de recuperação futura (densa, híbrida, outra) possa
reutilizar a mesma política sem a arrastar consigo. Depende apenas dos modelos
documentais, que são a sua matéria.

Colisão de vocabulário — leia antes de usar
-------------------------------------------

Já existe :mod:`app.retrieval.eligibility`, com ``decide_eligibility``,
``EligibilityDecision``, ``EligibilityBasis`` e ``ExclusionReason``. Esse módulo
trata de **elegibilidade lexical**: se o **conteúdo** de um candidato
corresponde suficientemente à pergunta para constituir evidência. É um conceito
**diferente** do deste módulo — e note-se que também lá a elegibilidade está
deliberadamente separada do ranking: o score composto ordena candidatos já
elegíveis, não decide quem o é.

Este módulo trata de **admissibilidade documental**: se um ``DocumentChunk``
pode, de todo, ser usado como evidência num dado contexto — instituição,
idioma, data de referência e restrição a fontes oficiais. Não sabe nada sobre a
pergunta nem sobre correspondência de conteúdo.

Nenhum dos nomes existentes é alterado, e este módulo nunca deve ser importado
com um alias chamado apenas ``eligibility``. Importe-o pelo nome do pacote
(``from app.documents import retrievability``) ou pelos nomes concretos das
políticas.

As duas políticas, e porque diferem
-----------------------------------

``RetrievalEligibility`` responde a "este chunk pode fundamentar uma resposta
**agora**". ``CitationPersistenceEligibility`` responde a "esta evidência foi
legitimamente usada para gerar **esta** resposta, e a sua proveniência deve ser
preservada".

Partilham :data:`BASE_CONDITIONS` — C1–C4 e C6–C11 — e divergem em exatamente
uma condição: :data:`LATEST_PROCESSED_VERSION` (C5), que pertence **apenas** à
primeira.

**Esta diferença é proveniência histórica intencional, não uma lacuna de
validação.** Se a versão N foi recuperada e usada para gerar uma resposta, o
processamento da versão N+1 antes da persistência do turno não deve invalidar a
fonte real dessa resposta. Registar N+1 como fonte seria factualmente falso;
recusar a persistência com conflito descartaria uma resposta legítima já gerada
por causa de um carregamento concorrente que nada tem que ver com ela. A fonte
correta é aquela que foi efetivamente usada.

Uma revisão futura que veja as duas políticas lado a lado será tentada a
fundi-las por parecerem duplicadas. **Não as funda.** A distinção está fixada
pelo teste de composição e pelo teste de proveniência histórica N → N+1 do
Momento 6. Acrescentar C5 a ``CitationPersistenceEligibility`` parte ambos.

Depois de persistido, um ``MessageSource`` nunca é reavaliado por nenhuma
política: a leitura devolve o snapshot tal como foi gravado.

Fora deste módulo
-----------------

- a correspondência lexical entre conteúdo e pergunta — mecanismo de pesquisa;
- a elegibilidade lexical do candidato — ver a colisão de vocabulário acima;
- a integridade do snapshot de uma citação (``content_sha256``, coerência de
  ``normalized_content``, metadados inalterados desde a geração) — deteta
  alterações ocorridas durante a geração, propósito distinto;
- a consistência de identificadores entre chunk, versão e documento — já
  garantida pela foreign key composta ``fk_document_chunks_version_document_institution``;
  permanece como defesa em profundidade nos consumidores;
- C12, "existe alguma versão processed" — não é condição sobre uma linha, é o
  resultado de um conjunto vazio; pertence à camada de seleção do diagnóstico.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.sql.selectable import Subquery

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion

PROCESSED_STATUS = "processed"


@dataclass(frozen=True)
class RetrievabilityContext:
    """O contexto em que a admissibilidade é avaliada.

    ``official_only`` afeta C11 de forma **assimétrica entre os adaptadores**,
    e é a única condição em que isso acontece: quando está desligado, o
    predicado desaparece do ``WHERE`` (``sql`` devolve ``None``, em vez de uma
    tautologia), mas o veredicto Python continua a **avaliar** C11 e a
    devolvê-la satisfeita pela disjunção. O conjunto de condições avaliadas por
    :meth:`EvidencePolicy.explain` nunca depende do contexto — só o SQL gerado
    depende.
    """

    institution_id: UUID
    language: str
    reference_date: date
    official_only: bool


@dataclass(frozen=True)
class RetrievabilitySubject:
    """Os dados de um chunk candidato, já extraídos das entidades ORM.

    Existe para que a avaliação **não faça consultas**: recebe dados, devolve
    veredicto, e é testável sem base de dados.

    ``effective_version_id`` é a assimetria deliberada de C5 — ver
    :data:`LATEST_PROCESSED_VERSION`. É resolvido pelo chamador antes da
    avaliação, porque depende do conjunto de versões do documento e não da
    linha. ``None`` significa "não existe versão processed", e nesse caso C5
    não se satisfaz.
    """

    chunk_id: UUID
    chunk_institution_id: UUID
    chunk_document_id: UUID
    chunk_document_version_id: UUID
    chunk_language: str
    document_id: UUID
    document_institution_id: UUID
    document_is_active: bool
    document_language: str
    document_official_source: bool
    document_valid_from: date | None
    document_valid_until: date | None
    version_id: UUID
    version_institution_id: UUID
    version_document_id: UUID
    version_processing_status: str
    effective_version_id: UUID | None = None

    @classmethod
    def from_entities(
        cls,
        *,
        chunk: DocumentChunk,
        document: Document,
        version: DocumentVersion,
        effective_version_id: UUID | None = None,
    ) -> "RetrievabilitySubject":
        """Constrói o sujeito a partir de entidades ORM **já carregadas**."""
        return cls(
            chunk_id=chunk.id,
            chunk_institution_id=chunk.institution_id,
            chunk_document_id=chunk.document_id,
            chunk_document_version_id=chunk.document_version_id,
            chunk_language=chunk.language,
            document_id=document.id,
            document_institution_id=document.institution_id,
            document_is_active=document.is_active,
            document_language=document.language,
            document_official_source=document.official_source,
            document_valid_from=document.valid_from,
            document_valid_until=document.valid_until,
            version_id=version.id,
            version_institution_id=version.institution_id,
            version_document_id=version.document_id,
            version_processing_status=version.processing_status,
            effective_version_id=effective_version_id,
        )


@dataclass(frozen=True)
class EvidenceCondition:
    """Uma condição nomeada, nas suas duas formas.

    ``sql`` devolve ``None`` quando a condição **não se aplica** ao contexto —
    é assim que C11 desaparece do ``WHERE`` quando ``official_only`` está
    desligado, em vez de virar uma tautologia. ``None`` nunca significa "sem
    tradução SQL possível", exceto no caso documentado de C5.
    """

    name: str
    sql: Callable[[RetrievabilityContext], ColumnElement[bool] | None]
    holds: Callable[[RetrievabilitySubject, RetrievabilityContext], bool]
    detail: Callable[[RetrievabilitySubject, RetrievabilityContext], str]


@dataclass(frozen=True)
class ConditionOutcome:
    name: str
    satisfied: bool
    detail: str


@dataclass(frozen=True)
class RetrievabilityVerdict:
    """Veredicto explicado: o que falhou, com o nome estável da condição."""

    policy: str
    eligible: bool
    conditions: tuple[ConditionOutcome, ...]

    @property
    def failed_condition_names(self) -> tuple[str, ...]:
        return tuple(
            outcome.name for outcome in self.conditions if not outcome.satisfied
        )


# ---------------------------------------------------------------------------
# C1–C3 — isolamento institucional
#
# Comparação de UUID nos dois lados; equivalência direta. O isolamento continua
# aplicado no PostgreSQL: estas condições existem como filtros SQL, não apenas
# como verificação em Python.
# ---------------------------------------------------------------------------

CHUNK_BELONGS_TO_INSTITUTION = EvidenceCondition(
    name="chunk_belongs_to_institution",
    sql=lambda context: DocumentChunk.institution_id == context.institution_id,
    holds=lambda subject, context: subject.chunk_institution_id == context.institution_id,
    detail=lambda subject, context: (
        f"chunk.institution_id={subject.chunk_institution_id} "
        f"context.institution_id={context.institution_id}."
    ),
)

DOCUMENT_BELONGS_TO_INSTITUTION = EvidenceCondition(
    name="document_belongs_to_institution",
    sql=lambda context: Document.institution_id == context.institution_id,
    holds=lambda subject, context: (
        subject.document_institution_id == context.institution_id
    ),
    detail=lambda subject, context: (
        f"document.institution_id={subject.document_institution_id} "
        f"context.institution_id={context.institution_id}."
    ),
)

VERSION_BELONGS_TO_INSTITUTION = EvidenceCondition(
    name="version_belongs_to_institution",
    sql=lambda context: DocumentVersion.institution_id == context.institution_id,
    holds=lambda subject, context: (
        subject.version_institution_id == context.institution_id
    ),
    detail=lambda subject, context: (
        f"version.institution_id={subject.version_institution_id} "
        f"context.institution_id={context.institution_id}."
    ),
)


# ---------------------------------------------------------------------------
# C4 — versão em estado processed
#
# O nome é o que o diagnóstico já usa, para que a Fase 4 seja delegação e não
# renomeação.
# ---------------------------------------------------------------------------

VERSION_PROCESSED = EvidenceCondition(
    name="version_processed",
    sql=lambda context: DocumentVersion.processing_status == PROCESSED_STATUS,
    holds=lambda subject, context: subject.version_processing_status == PROCESSED_STATUS,
    detail=lambda subject, context: (
        f"processing_status is '{subject.version_processing_status}'."
    ),
)


# ---------------------------------------------------------------------------
# C6 — documento ativo
#
# Não-equivalência tratada (Decisão 5): o SQL usa ``IS TRUE``, que exclui
# ``NULL``; o lado Python usa ``is True``, que exclui ``None`` pela mesma
# razão explícita. Deliberadamente **não** se usa avaliação de veracidade nem
# se depende da não-nulabilidade da coluna para a equivalência.
# ---------------------------------------------------------------------------

DOCUMENT_ACTIVE = EvidenceCondition(
    name="document_active",
    sql=lambda context: Document.is_active.is_(True),
    holds=lambda subject, context: subject.document_is_active is True,
    detail=lambda subject, context: f"is_active is {subject.document_is_active}.",
)


# ---------------------------------------------------------------------------
# C7, C8 — idioma do documento e idioma do chunk
#
# Não-equivalência analisada (Decisão 5): igualdade de strings sob a collation
# do PostgreSQL contra comparação por code point em Python. As duas formas
# divergiriam se a collation da base fosse **não determinística** (insensível a
# maiúsculas ou a acentos). Verificado no PostgreSQL da suite: a collation em
# uso é determinística, pelo que a igualdade é comparação byte a byte e
# coincide com Python — incluindo em etiquetas que diferem apenas em
# maiúsculas/minúsculas ('PT' != 'pt' em ambos os lados).
#
# Por isso **não** se introduz normalização aqui: normalizar mudaria o
# comportamento atual, o que esta fase não pode fazer. O teste de contrato
# cobre etiquetas que diferem só no case; se a base passar a usar uma collation
# não determinística, esse teste falha e a decisão volta a ser tomada
# explicitamente.
#
# C8 é hoje redundante face a C7, porque o idioma do chunk é herdado do
# documento na segmentação. Não é removível sem decisão explícita: linhas
# anteriores à invariante podem violá-la, e o Momento 6 fixou por teste o
# comportamento perante uma dessas linhas.
# ---------------------------------------------------------------------------

DOCUMENT_LANGUAGE_COMPATIBLE = EvidenceCondition(
    name="language_compatible",
    sql=lambda context: Document.language == context.language,
    holds=lambda subject, context: subject.document_language == context.language,
    detail=lambda subject, context: (
        f"document language '{subject.document_language}' vs context "
        f"language '{context.language}'."
    ),
)

CHUNK_LANGUAGE_COMPATIBLE = EvidenceCondition(
    name="chunk_language_compatible",
    sql=lambda context: DocumentChunk.language == context.language,
    holds=lambda subject, context: subject.chunk_language == context.language,
    detail=lambda subject, context: (
        f"chunk language '{subject.chunk_language}' vs context "
        f"language '{context.language}'."
    ),
)


# ---------------------------------------------------------------------------
# C9, C10 — validade
#
# Não-equivalência tratada (Decisão 5): comparar ``NULL`` com uma data devolve
# ``NULL`` em SQL, enquanto comparar ``None`` com uma data levanta
# ``TypeError`` em Python. As duas formas só são equivalentes porque o teste de
# nulidade é **explícito em ambas** — e é obrigatório que continue a ser.
# ---------------------------------------------------------------------------

VALID_FROM_COMPATIBLE = EvidenceCondition(
    name="valid_from_compatible",
    sql=lambda context: (
        (Document.valid_from.is_(None))
        | (Document.valid_from <= context.reference_date)
    ),
    holds=lambda subject, context: (
        subject.document_valid_from is None
        or subject.document_valid_from <= context.reference_date
    ),
    detail=lambda subject, context: (
        f"valid_from={subject.document_valid_from} "
        f"reference_date={context.reference_date}."
    ),
)

VALID_UNTIL_COMPATIBLE = EvidenceCondition(
    name="valid_until_compatible",
    sql=lambda context: (
        (Document.valid_until.is_(None))
        | (Document.valid_until >= context.reference_date)
    ),
    holds=lambda subject, context: (
        subject.document_valid_until is None
        or subject.document_valid_until >= context.reference_date
    ),
    detail=lambda subject, context: (
        f"valid_until={subject.document_valid_until} "
        f"reference_date={context.reference_date}."
    ),
)


# ---------------------------------------------------------------------------
# C11 — fonte oficial, apenas quando o contexto o exige
#
# Não-equivalência tratada (Decisão 5): o SQL **omite** a condição quando
# ``official_only`` está desligado (``sql`` devolve ``None``); o Python avalia
# a disjunção com a negação do flag e devolve verdadeiro. Formas diferentes,
# resultado igual.
# ---------------------------------------------------------------------------

OFFICIAL_SOURCE_COMPATIBLE = EvidenceCondition(
    name="official_source_compatible",
    sql=lambda context: (
        Document.official_source.is_(True) if context.official_only else None
    ),
    holds=lambda subject, context: (
        not context.official_only or subject.document_official_source is True
    ),
    detail=lambda subject, context: (
        f"official_only={context.official_only} "
        f"document.official_source={subject.document_official_source}."
    ),
)


# ---------------------------------------------------------------------------
# C5 — a exceção estrutural
#
# **Não é uma condição sobre uma linha isolada**: depende das outras versões do
# mesmo documento. Por isso os dois adaptadores não têm a mesma assinatura, e
# essa assimetria é deliberada:
#
# - do lado SQL, ``sql`` devolve ``None`` e a condição materializa-se pela
#   subquery de :func:`latest_processed_version_subquery`, na forma de window
#   function que a recuperação já usa — manter a forma preserva o plano de
#   execução esperado;
# - do lado Python, o sujeito transporta ``effective_version_id``, resolvido
#   pelo chamador a partir da mesma subquery.
#
# A condição mantém nome próprio e aparece no veredicto; muda apenas a forma
# como cada adaptador a obtém. É também, não por acaso, a única condição que
# distingue as duas políticas.
#
# Equivalência confirmada (D4 da issue #24): ``row_number()`` particionada por
# documento e ordenação descendente com limite 1 são equivalentes, porque a
# unique constraint ``uq_document_versions_document_id_version_number`` garante
# ausência de empates.
# ---------------------------------------------------------------------------

LATEST_PROCESSED_VERSION = EvidenceCondition(
    name="version_is_highest_processed",
    sql=lambda context: None,
    holds=lambda subject, context: (
        subject.effective_version_id is not None
        and subject.effective_version_id == subject.version_id
    ),
    detail=lambda subject, context: (
        "the retriever only considers the highest-numbered processed version "
        f"of the document; effective={subject.effective_version_id} "
        f"version={subject.version_id}."
    ),
)


def latest_processed_version_subquery(context: RetrievabilityContext) -> Subquery:
    """Versão ``processed`` de maior ``version_number`` por documento.

    Forma canónica de C5, partilhada pelos dois adaptadores: o lado SQL junta
    esta subquery e filtra ``rn == 1``; o lado Python usa-a para resolver o
    ``effective_version_id`` do sujeito. Existe uma única definição de "versão
    efetiva", e é esta.

    A window está restrita à instituição do contexto e a versões ``processed``,
    exatamente como a recuperação atual a constrói.
    """
    return (
        select(
            DocumentVersion.id.label("version_id"),
            DocumentVersion.document_id.label("document_id"),
            func.row_number()
            .over(
                partition_by=DocumentVersion.document_id,
                order_by=DocumentVersion.version_number.desc(),
            )
            .label("rn"),
        )
        .where(
            DocumentVersion.institution_id == context.institution_id,
            DocumentVersion.processing_status == PROCESSED_STATUS,
        )
        .subquery("latest_processed_versions")
    )


# ---------------------------------------------------------------------------
# Composições
# ---------------------------------------------------------------------------

#: C1–C4 e C6–C11: exatamente a extensão comum aos três consumidores.
BASE_CONDITIONS: tuple[EvidenceCondition, ...] = (
    CHUNK_BELONGS_TO_INSTITUTION,
    DOCUMENT_BELONGS_TO_INSTITUTION,
    VERSION_BELONGS_TO_INSTITUTION,
    VERSION_PROCESSED,
    DOCUMENT_ACTIVE,
    DOCUMENT_LANGUAGE_COMPATIBLE,
    CHUNK_LANGUAGE_COMPATIBLE,
    VALID_FROM_COMPATIBLE,
    VALID_UNTIL_COMPATIBLE,
    OFFICIAL_SOURCE_COMPATIBLE,
)


@dataclass(frozen=True)
class EvidencePolicy:
    """Uma composição nomeada de condições, com os dois adaptadores.

    As políticas **compõem**; nunca reescrevem nem reinterpretam uma condição.
    Acrescentar uma condição a uma política sem decidir se pertence à base
    parte o teste de composição.
    """

    name: str
    purpose: str
    conditions: tuple[EvidenceCondition, ...]

    @property
    def condition_names(self) -> tuple[str, ...]:
        return tuple(condition.name for condition in self.conditions)

    @property
    def requires_latest_processed_version(self) -> bool:
        """Se C5 faz parte desta política — a única diferença entre as duas."""
        return LATEST_PROCESSED_VERSION in self.conditions

    def as_sql_filters(self, context: RetrievabilityContext) -> tuple[ColumnElement[bool], ...]:
        """Predicados ao nível da linha, para um ``WHERE`` do PostgreSQL.

        C5 **não** vem aqui: não é um predicado de linha. Um consumidor que
        aplique esta política tem de juntar também
        :func:`latest_processed_version_subquery` quando
        :attr:`requires_latest_processed_version` for verdadeiro — é o que
        :meth:`select_eligible_chunk_ids` faz.
        """
        filters = []
        for condition in self.conditions:
            clause = condition.sql(context)
            if clause is not None:
                filters.append(clause)
        return tuple(filters)

    def select_eligible_chunk_ids(self, context: RetrievabilityContext) -> Select:
        """Seleção completa dos chunks admissíveis sob esta política.

        Reúne os dois lados de C5 numa única declaração, para que exista uma
        forma SQL **integral** da política — é sobre ela que o teste de
        contrato compara os dois adaptadores. Os consumidores das Fases 2 e 3
        continuarão a compor os filtros na sua própria consulta.
        """
        statement = (
            select(DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
            .where(*self.as_sql_filters(context))
        )
        if self.requires_latest_processed_version:
            latest = latest_processed_version_subquery(context)
            statement = statement.join(
                latest,
                (latest.c.version_id == DocumentChunk.document_version_id)
                & (latest.c.document_id == DocumentChunk.document_id),
            ).where(latest.c.rn == 1)
        return statement

    def explain(
        self, subject: RetrievabilitySubject, context: RetrievabilityContext
    ) -> RetrievabilityVerdict:
        """Veredicto explicado sobre um sujeito, sem tocar na base de dados."""
        outcomes = tuple(
            ConditionOutcome(
                name=condition.name,
                satisfied=condition.holds(subject, context),
                detail=condition.detail(subject, context),
            )
            for condition in self.conditions
        )
        return RetrievabilityVerdict(
            policy=self.name,
            eligible=all(outcome.satisfied for outcome in outcomes),
            conditions=outcomes,
        )


#: "Este chunk pode fundamentar uma resposta **agora**."
RetrievalEligibility = EvidencePolicy(
    name="RetrievalEligibility",
    purpose=(
        "Este chunk pode fundamentar uma resposta agora. Avaliada no instante "
        "da pesquisa, contra a data corrente; é uma propriedade do chunk face "
        "ao estado atual do sistema e não é armazenada."
    ),
    conditions=(*BASE_CONDITIONS, LATEST_PROCESSED_VERSION),
)

#: "Esta evidência foi legitimamente usada para gerar **esta** resposta."
CitationPersistenceEligibility = EvidencePolicy(
    name="CitationPersistenceEligibility",
    purpose=(
        "Esta evidência foi legitimamente usada para gerar esta resposta e a "
        "sua proveniência deve ser preservada. Avaliada uma única vez, no "
        "instante da persistência do turno. Não exige que a versão continue a "
        "ser a processed mais recente: ver a nota de proveniência histórica no "
        "topo do módulo."
    ),
    conditions=BASE_CONDITIONS,
)
