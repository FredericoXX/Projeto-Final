"""Identidade determinística de um conjunto de perguntas, e controlo do pareamento (D4.4).

Módulo **puro**: recebe dicionários já lidos de JSON e devolve digests, projeções
e problemas. Não fala com a base de dados, não lê ficheiros e não é reexportado
por ``app/evaluation/__init__.py`` — pela mesma razão que
``app.evaluation.retrieval_metrics``: manter fora do ``__init__`` o que importa
dependências pesadas torna estrutural uma garantia que de outro modo dependeria
de disciplina.

Porque é que este módulo existe
-------------------------------

O D4.3 (§8) registou um buraco de identidade: o ``snapshot_id`` cobre corpus,
instituição, data de referência e configuração de recuperação — **não** o
conjunto de perguntas. Nenhum artefacto guardava um digest do *ground truth*,
pelo que a afirmação "estes resultados foram medidos com estas perguntas" era
convencional e não verificável. Com duas versões das perguntas em circulação —
a histórica e a pareada com diacríticos — a convenção deixa de bastar.

O que o digest cobre, e o que deliberadamente não cobre
-------------------------------------------------------

O digest responde a **uma** pergunta:

    Duas execuções sobre estes dois ficheiros produziriam os mesmos números,
    dado o mesmo corpus e a mesma configuração de recuperação?

Daí o âmbito :data:`GROUND_TRUTH_DIGEST_SCOPE`: entram exatamente os campos que
a medição **lê**, e mais nenhum. Qualquer inclusão mais larga faria o digest
mudar por razões que não afetam a comparabilidade — que é precisamente o que ele
existe para detetar; qualquer inclusão mais estreita deixaria passar uma
alteração material.

A consequência tem de ser dita sem rodeios: **isto não é um hash do ficheiro.**
Alterar ``notes``, ``difficulty_types``, ``temporal_scope``, ``exclusion_reason``,
``question_origin``, ``annotation`` ou ``document_level_relevance`` **não** muda o
digest, porque nenhum deles entra no cálculo de qualquer métrica. São anotação de
desenho, não conteúdo medido. Quem quiser integridade ao nível do ficheiro
precisa de um hash do ficheiro, que é outra coisa e teria outro nome.

Também **não** entram ``snapshot_id``, ``corpus_digest`` nem ``reference_date``:
descrevem o **estado do corpus**, não o conjunto de perguntas. Deixá-los de fora
mantém o digest desacoplado desse estado — o mesmo conjunto de perguntas conserva
a sua identidade quando o corpus é reprocessado ou a data de referência muda, e é
por isso que se pode dizer "esta versão das perguntas" independentemente do
snapshot contra o qual foi medida. Incluí-los não criaria colisões — as perguntas
participam no hash e conjuntos diferentes continuariam a ter digests diferentes —
mas acoplaria duas identidades que o projeto separa de propósito, e obrigaria a
reemitir o digest do *ground truth* de cada vez que S1 fosse substituído.

``corpus_id``, esse, **entra**: é o rótulo estável da população anotada, não um
estado do corpus, e um conjunto de perguntas dirigido a outra população é outro
conjunto de perguntas.

Invariâncias garantidas
-----------------------

A representação canónica ordena perguntas por ``question_id`` e julgamentos pela
sua chave completa. Reordenar o ficheiro não muda o digest, porque não muda
número nenhum: as métricas indexam julgamentos por ``(documento, segmento)`` e a
agregação é uma macro-média, ambas independentes da ordem.

O pareamento é mais estrito do que o digest
--------------------------------------------

:func:`verify_pairing` verifica igualdade de campos que o digest ignora —
``temporal_scope``, ``exclusion_reason``, ``document_level_relevance``. A
assimetria é deliberada e as duas perguntas são diferentes: o digest pergunta
*"mediria o mesmo?"*, o pareamento pergunta *"é a mesma pergunta com os acentos
restituídos?"*. A segunda é uma afirmação sobre significado, e nesta fase é ela
que impede que uma reformulação silenciosa passe por um diacrítico.
"""

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.evaluation.results import canonical_json

GROUND_TRUTH_DIGEST_ALGORITHM: Final = "sha256"

#: Nome do critério de âmbito, gravado nos artefactos ao lado do digest para que
#: este se descreva a si próprio. Um digest cujo âmbito não está declarado
#: convida exatamente ao erro que o D4.3 apanhou no ``snapshot_id``.
GROUND_TRUTH_DIGEST_SCOPE: Final = "measurement_relevant_fields"

#: Sufixo que deriva o identificador pareado do original. Não é decoração: com
#: identificadores iguais nos dois ficheiros, um artefacto que os misturasse
#: ficaria ambíguo e nada o detetaria.
PAIRED_ID_SUFFIX: Final = "-diacritics"

#: Campos do protocolo de métricas que a medição lê. Os restantes campos de
#: ``metric_protocol`` são justificação em prosa.
PROTOCOL_FIELDS: Final = (
    "k_values",
    "primary_k",
    "binary_relevance_threshold",
    "ndcg_gain_mapping",
    "unjudged_chunk_treatment",
)

#: Campos de cada pergunta que a medição lê, fora dos julgamentos.
#:
#: - ``question`` determina a consulta;
#: - ``language`` determina a configuração FTS e a tokenização;
#: - ``question_id`` identifica a linha do resultado;
#: - ``no_relevant_evidence`` e ``excluded_from_metrics`` determinam **quais**
#:   perguntas entram nas médias.
QUESTION_FIELDS: Final = (
    "question_id",
    "question",
    "language",
    "no_relevant_evidence",
    "excluded_from_metrics",
)

#: Campos de cada julgamento que a medição lê. ``note`` é prosa.
JUDGMENT_FIELDS: Final = ("corpus_item_id", "chunk_index", "relevance")

#: Campos cuja igualdade o **pareamento** exige mas o digest ignora. Existem
#: aqui, e não em :data:`QUESTION_FIELDS`, porque descrevem o significado da
#: anotação sem entrar em nenhum cálculo.
PAIRED_INVARIANT_FIELDS: Final = (
    "temporal_scope",
    "question_origin",
    "difficulty_types",
    "exclusion_reason",
    "document_level_relevance",
)

_WORD_RE: Final = re.compile(r"[^\W_]+")


class GroundTruthIdentityError(ValueError):
    """Ficheiro malformado. Falhar é obrigatório: um digest calculado sobre um
    ficheiro incompleto seria plausível e errado, que é a pior combinação."""


def strip_diacritics(text: str) -> str:
    """Remove marcas combinantes, **sem** ``casefold`` nem colapso de espaços.

    Deliberadamente mais estreito do que ``app.core.text_normalization.normalize_text``:
    a prova de pareamento tem de rejeitar uma alteração de maiúsculas ou de
    espaçamento, e ``normalize_text`` deixaria ambas passar por também as
    descartar. A relação entre os dois está fixada por teste.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _require(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        msg = f"{context}: missing required field {key!r}"
        raise GroundTruthIdentityError(msg)
    return mapping[key]


def _canonical_judgment(judgment: Mapping[str, Any], context: str) -> dict[str, Any]:
    return {field: _require(judgment, field, context) for field in JUDGMENT_FIELDS}


def _judgment_sort_key(judgment: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(judgment[field] for field in JUDGMENT_FIELDS)


def _canonical_question(question: Mapping[str, Any]) -> dict[str, Any]:
    question_id = _require(question, "question_id", "question")
    context = f"question {question_id}"
    canonical: dict[str, Any] = {
        field: _require(question, field, context) for field in QUESTION_FIELDS
    }
    judgments = _require(question, "evidence_judgments", context)
    canonical["evidence_judgments"] = sorted(
        (_canonical_judgment(judgment, context) for judgment in judgments),
        key=_judgment_sort_key,
    )
    return canonical


def canonical_ground_truth(ground_truth: Mapping[str, Any]) -> dict[str, Any]:
    """Projeção canónica de que se deriva o digest.

    Devolvida como estrutura, e não como texto, para que os testes possam
    afirmar o que entra e o que fica de fora sem depender da serialização.
    """
    protocol = _require(ground_truth, "metric_protocol", "ground truth")
    questions = _require(ground_truth, "questions", "ground truth")
    duplicates = _duplicate_ids(questions)
    if duplicates:
        msg = f"ground truth: duplicate question_id {duplicates}"
        raise GroundTruthIdentityError(msg)
    return {
        "schema_version": _require(ground_truth, "schema_version", "ground truth"),
        "contract": _require(ground_truth, "contract", "ground truth"),
        "corpus_id": _require(ground_truth, "corpus_id", "ground truth"),
        "metric_protocol": {
            field: _require(protocol, field, "metric_protocol")
            for field in PROTOCOL_FIELDS
        },
        "questions": sorted(
            (_canonical_question(question) for question in questions),
            key=lambda question: str(question["question_id"]),
        ),
    }


def _duplicate_ids(questions: Sequence[Mapping[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for question in questions:
        identifier = str(_require(question, "question_id", "question"))
        if identifier in seen:
            duplicated.add(identifier)
        seen.add(identifier)
    return sorted(duplicated)


def ground_truth_digest(ground_truth: Mapping[str, Any]) -> str:
    """SHA-256 da serialização canónica da projeção.

    Usa ``canonical_json`` — a serialização única do projeto — e nunca ``hash()``
    do Python, que é aleatorizado por processo e portanto não é identidade
    nenhuma entre execuções.
    """
    payload = canonical_json(canonical_ground_truth(ground_truth)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Pareamento
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PairedQuestion:
    """Um par verificado. ``identical`` marca as perguntas que não tinham
    diacríticos a restituir — controlos nulos internos, que **têm** de medir o
    mesmo nas duas condições."""

    original_id: str
    paired_id: str
    original_question: str
    paired_question: str
    restored: tuple[tuple[str, str], ...]

    @property
    def identical(self) -> bool:
        return self.original_question == self.paired_question


@dataclass(frozen=True)
class PairingReport:
    pairs: tuple[PairedQuestion, ...]
    problems: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.problems

    @property
    def identical_pairs(self) -> tuple[str, ...]:
        return tuple(pair.original_id for pair in self.pairs if pair.identical)

    @property
    def restored_pairs(self) -> tuple[str, ...]:
        return tuple(pair.original_id for pair in self.pairs if not pair.identical)


def _accented_tokens(text: str) -> set[str]:
    """Tokens do texto que carregam alguma marca combinante."""
    return {
        token
        for token in _WORD_RE.findall(text.casefold())
        if token != strip_diacritics(token)
    }


def _check_restoration_claims(
    question_id: str,
    original_text: str,
    paired_text: str,
    claims: Sequence[Sequence[str]],
) -> list[str]:
    """Verifica a lista ``diacritics_restored``: sólida **e** completa.

    Sólida: cada par declarado é mesmo uma restituição de acentos, e ambas as
    formas ocorrem no respetivo texto. Completa: não há no texto pareado nenhuma
    palavra acentuada que a lista não declare. Sem a segunda metade, a lista
    seria documentação que se pode esquecer de atualizar — e passaria a mentir em
    silêncio.
    """
    problems: list[str] = []
    original_tokens = set(_WORD_RE.findall(original_text.casefold()))
    paired_tokens = set(_WORD_RE.findall(paired_text.casefold()))
    declared_accented: set[str] = set()

    for claim in claims:
        if len(claim) != 2:
            problems.append(f"{question_id}: malformed diacritics_restored entry {claim!r}")
            continue
        plain, accented = claim[0], claim[1]
        declared_accented.add(accented)
        if strip_diacritics(accented) != plain:
            problems.append(
                f"{question_id}: {accented!r} is not {plain!r} with diacritics restored"
            )
        if plain == accented:
            problems.append(f"{question_id}: {plain!r} declares no restoration")
        if plain not in original_tokens:
            problems.append(f"{question_id}: {plain!r} does not occur in the original")
        if accented not in paired_tokens:
            problems.append(f"{question_id}: {accented!r} does not occur in the paired")

    undeclared = sorted(_accented_tokens(paired_text) - declared_accented)
    if undeclared:
        problems.append(
            f"{question_id}: accented tokens absent from diacritics_restored: {undeclared}"
        )
    return problems


def _check_invariant_fields(
    question_id: str,
    original: Mapping[str, Any],
    paired: Mapping[str, Any],
) -> list[str]:
    problems: list[str] = []
    for field in (*QUESTION_FIELDS, *PAIRED_INVARIANT_FIELDS):
        if field == "question_id" or field == "question":
            continue
        if original.get(field) != paired.get(field):
            problems.append(
                f"{question_id}: {field} differs between the original and the pair"
            )
    original_judgments = sorted(
        (_canonical_judgment(item, question_id) for item in original["evidence_judgments"]),
        key=_judgment_sort_key,
    )
    paired_judgments = sorted(
        (_canonical_judgment(item, question_id) for item in paired["evidence_judgments"]),
        key=_judgment_sort_key,
    )
    if original_judgments != paired_judgments:
        problems.append(
            f"{question_id}: evidence_judgments differ between the original and the pair"
        )
    return problems


def verify_pairing(
    original: Mapping[str, Any], paired: Mapping[str, Any]
) -> PairingReport:
    """Prova que o conjunto pareado difere do original **apenas** em diacríticos.

    A prova central é uma igualdade exata de cadeias:

        ``strip_diacritics(pergunta_pareada) == pergunta_original``

    Como o conjunto original não tem diacrítico nenhum, isto diz que o par é o
    original com marcas acrescentadas e nada mais — nem uma palavra trocada, nem
    uma vírgula, nem uma maiúscula. Uma pergunta que exigisse reformulação para
    receber acentos falha aqui, e é reportada em vez de ser incluída.

    O que a verificação **não** prova é que os acentos restituídos sejam os
    linguisticamente corretos: ``mátricula`` passaria. Isso é um juízo humano do
    anotador, e dizer o contrário seria vender uma garantia que o código não dá.
    """
    problems: list[str] = []

    for field in ("schema_version", "corpus_id", "snapshot_id", "corpus_digest"):
        if original.get(field) != paired.get(field):
            problems.append(f"question sets disagree on {field}")
    original_protocol = original.get("metric_protocol") or {}
    paired_protocol = paired.get("metric_protocol") or {}
    for field in PROTOCOL_FIELDS:
        if original_protocol.get(field) != paired_protocol.get(field):
            problems.append(f"question sets disagree on metric_protocol.{field}")

    originals = {str(question["question_id"]): question for question in original["questions"]}
    pairs: list[PairedQuestion] = []
    claimed: dict[str, str] = {}

    for question in paired["questions"]:
        paired_id = str(_require(question, "question_id", "paired question"))
        original_id = question.get("paired_question_id")
        if not original_id:
            problems.append(f"{paired_id}: no paired_question_id")
            continue
        if paired_id != f"{original_id}{PAIRED_ID_SUFFIX}":
            problems.append(
                f"{paired_id}: identifier is not {original_id}{PAIRED_ID_SUFFIX}"
            )
        if original_id in claimed:
            problems.append(
                f"{original_id} is claimed by both {claimed[original_id]} and {paired_id}"
            )
            continue
        claimed[original_id] = paired_id
        source = originals.get(original_id)
        if source is None:
            problems.append(f"{paired_id}: {original_id} is absent from the original set")
            continue

        original_text = str(source["question"])
        paired_text = str(question["question"])
        if strip_diacritics(paired_text) != original_text:
            problems.append(
                f"{paired_id}: differs from the original beyond diacritics; it would "
                "require reformulation and is not admissible as a pair"
            )
            continue

        problems.extend(_check_invariant_fields(paired_id, source, question))
        claims = question.get("diacritics_restored", [])
        problems.extend(
            _check_restoration_claims(paired_id, original_text, paired_text, claims)
        )
        pairs.append(
            PairedQuestion(
                original_id=original_id,
                paired_id=paired_id,
                original_question=original_text,
                paired_question=paired_text,
                restored=tuple((claim[0], claim[1]) for claim in claims if len(claim) == 2),
            )
        )

    unpaired = sorted(set(originals) - set(claimed))
    if unpaired:
        problems.append(f"original questions without a pair: {unpaired}")

    return PairingReport(pairs=tuple(pairs), problems=tuple(problems))
