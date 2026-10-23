"""Identidade dos artefactos congelados e verificação do congelamento formal.

Oito artefactos, cada um com digest próprio no manifesto de congelamento:

- ``corpus`` — o ficheiro de casos (P2), com os casos ordenados por ``case_id``;
- ``manifest`` — o manifesto documental do corpus P2: o inventário de todos os
  documentos, versões e segmentos da instituição, exportado da base de dados
  (:mod:`app.evaluation.policy_v1.corpus_inventory`) e confrontado com ela pelo
  executor;
- ``labels`` — a adjudicação identificada;
- ``catalog`` — o snapshot canónico do catálogo institucional (âmbito D1 e
  serviços D6) com que a avaliação corre, validado pelas mesmas regras da
  publicação;
- ``policy``, ``schema``, ``prompts``, ``config`` — **gerados a partir do código**
  em execução, nunca lidos de ficheiros: assim, verificar o congelamento é
  verificar que o código que vai correr é o que foi congelado.

A verificação formal (:func:`verify_formal_freeze`) exige ainda que o
``code_commit`` do manifesto seja o ``HEAD`` atual e que a árvore de trabalho
esteja limpa: código não versionado não pertence a nenhum commit.
"""

import hashlib
import inspect
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from app.answering.prompts import SYSTEM_PROMPT as ANSWER_SYSTEM_PROMPT
from app.core.config import settings
from app.decision import messages as messages_module
from app.decision import policy as policy_module
from app.decision.definitions import (
    DECISION_RULES,
    DEFINITIONS_VERSION,
    DIMENSION_DEFINITIONS,
    RULES_VERSION,
)
from app.decision.estimators.prompts import (
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_SYSTEM_PROMPT,
    ASSESSMENT_PROMPT_VERSION,
    ASSESSMENT_SYSTEM_PROMPT,
)
from app.decision.messages import MESSAGE_VERSION
from app.decision.policy import POLICY_VERSION
from app.documents.retrievability import DOCUMENT_ACCESS_POLICY_VERSION
from app.evaluation.policy_v1.conditions import B1_PROMPT_VERSION, b1_system_prompt
from app.evaluation.policy_v1.config import EVALUATION_CONFIG
from app.evaluation.policy_v1.corpus_inventory import corpus_inventory_bytes
from app.evaluation.policy_v1.freeze import (
    REQUIRED_ARTIFACTS,
    FreezeError,
    FrozenArtifact,
    canonical_bytes,
    freeze_cases,
    sha256,
    verify_artifact,
)
from app.evaluation.policy_v1.labels import LabelSet, MessageRatingSet, label_set_bytes
from app.models.decision_catalog import InstitutionDecisionCatalog
from app.schemas.decision_catalog import DecisionCatalogWrite

#: Artefactos gerados a partir do código; não podem ser fornecidos como ficheiro.
CODE_ARTIFACTS: Final = ("policy", "schema", "prompts", "config")
#: Artefactos fornecidos como ficheiro.
FILE_ARTIFACTS: Final = ("corpus", "manifest", "labels", "catalog")


def _source_digest(module: object) -> str:
    return hashlib.sha256(inspect.getsource(module).encode("utf-8")).hexdigest()  # type: ignore[arg-type]


def policy_payload() -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "rules_version": RULES_VERSION,
        "definitions_version": DEFINITIONS_VERSION,
        "rules": DECISION_RULES,
        "definitions": DIMENSION_DEFINITIONS,
        "document_access_policy": DOCUMENT_ACCESS_POLICY_VERSION,
        # A implementação executável, e não apenas a sua versão declarada.
        "policy_source_sha256": _source_digest(policy_module),
    }


def schema_payload() -> dict[str, Any]:
    from app.evaluation.policy_v1.executor import EvaluationCaseSet

    return {
        "labels": LabelSet.model_json_schema(),
        "cases": EvaluationCaseSet.model_json_schema(),
        "message_ratings": MessageRatingSet.model_json_schema(),
    }


def prompts_payload() -> dict[str, Any]:
    return {
        "analysis": {"version": ANALYSIS_PROMPT_VERSION, "system": ANALYSIS_SYSTEM_PROMPT},
        "assessment": {"version": ASSESSMENT_PROMPT_VERSION, "system": ASSESSMENT_SYSTEM_PROMPT},
        "b1": {
            "version": B1_PROMPT_VERSION,
            "full": b1_system_prompt("full"),
            "composition": b1_system_prompt("composition"),
        },
        "answer_generator": {"system": ANSWER_SYSTEM_PROMPT},
        "messages": {
            "version": MESSAGE_VERSION,
            "source_sha256": _source_digest(messages_module),
        },
    }


def config_payload() -> dict[str, Any]:
    return {
        "evaluation": EVALUATION_CONFIG,
        "runtime": {
            "answer_generator_provider": settings.answer_generator_provider,
            "answer_model": settings.openai_model,
            "estimator_provider": settings.decision_estimator_provider,
            "estimator_model": settings.decision_estimator_model or settings.openai_model,
            "estimator_timeout_seconds": settings.decision_estimator_timeout_seconds,
            "estimator_max_attempts": settings.decision_estimator_max_attempts,
            "decision_retrieval_top_k": settings.decision_retrieval_top_k,
            "answering_default_top_k": settings.answering_default_top_k,
            "answering_max_context_chars": settings.answering_max_context_chars,
            "answering_max_answer_chars": settings.answering_max_answer_chars,
            "retrieval_min_relevance_score": settings.retrieval_min_relevance_score,
        },
    }


def code_artifacts() -> list[FrozenArtifact]:
    payloads = {
        "policy": (POLICY_VERSION, policy_payload()),
        "schema": ("policy_v1_schemas_1", schema_payload()),
        "prompts": (B1_PROMPT_VERSION, prompts_payload()),
        "config": (str(EVALUATION_CONFIG["version"]), config_payload()),
    }
    return [
        FrozenArtifact(name=name, version=version, data=canonical_bytes(payload))
        for name, (version, payload) in payloads.items()
    ]


def catalog_snapshot(catalog: InstitutionDecisionCatalog) -> dict[str, Any]:
    """Snapshot canónico da versão do catálogo usada numa avaliação."""
    return {
        "version": catalog.version,
        "scope_description": catalog.scope_description,
        "topics": list(catalog.topics),
        "services": list(catalog.services),
    }


def catalog_bytes(payload: Mapping[str, Any]) -> bytes:
    """Bytes congelados do catálogo, depois da validação da publicação.

    Exige exatamente ``version``, ``scope_description``, ``topics`` e
    ``services``; os contactos e os temas passam pelas mesmas regras de
    ``DecisionCatalogWrite`` (um serviço por tema, contactos válidos).
    """
    if set(payload) != {"version", "scope_description", "topics", "services"}:
        msg = "a catalog snapshot has exactly version, scope_description, topics, services"
        raise FreezeError(msg)
    version = payload["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        msg = "catalog version must be a positive integer"
        raise FreezeError(msg)
    validated = DecisionCatalogWrite.model_validate(
        {key: payload[key] for key in ("scope_description", "topics", "services")}
    )
    return canonical_bytes({"version": version, **validated.model_dump(mode="json")})


def corpus_bytes(payload: Mapping[str, Any]) -> bytes:
    """Bytes congelados do ficheiro de casos: casos ordenados por ``case_id``."""
    import json

    ordered = json.loads(freeze_cases(payload["cases"]).decode("utf-8"))
    return canonical_bytes({**payload, "cases": ordered})


def file_artifact_bytes(name: str, payload: Any) -> bytes:
    if name in CODE_ARTIFACTS:
        msg = f"artifact {name} is generated from the code and cannot be supplied as a file"
        raise FreezeError(msg)
    if name == "corpus":
        return corpus_bytes(payload)
    if name == "labels":
        return label_set_bytes(LabelSet.model_validate(payload))
    if name == "catalog":
        return catalog_bytes(payload)
    if name == "manifest":
        return corpus_inventory_bytes(payload)
    return canonical_bytes(payload)


def verify_code_artifacts(manifest: Mapping[str, Any]) -> None:
    for artifact in code_artifacts():
        verify_artifact(manifest, artifact.name, artifact.data)


def verify_formal_freeze(
    manifest: Mapping[str, Any],
    *,
    cases_payload: Mapping[str, Any],
    corpus_inventory_payload: Mapping[str, Any],
    adjudication: LabelSet,
    catalog_payload: Mapping[str, Any],
    commit: str,
    head_commit: str,
    working_tree_clean: bool,
) -> None:
    """Todos os artefactos, o commit e a árvore de trabalho — ou recusa.

    ``corpus_inventory_payload`` e ``catalog_payload`` vêm da base de dados no
    momento da execução, nunca de ficheiros: é a base que tem de ser a
    congelada.
    """
    if not manifest.get("complete"):
        msg = "the freeze manifest is incomplete"
        raise FreezeError(msg)
    missing = sorted(set(REQUIRED_ARTIFACTS) - set(manifest.get("artifacts", {})))
    if missing:
        msg = f"the freeze manifest lacks {missing}"
        raise FreezeError(msg)
    if not (manifest.get("code_commit") == commit == head_commit):
        msg = "the frozen code_commit, --commit and the current HEAD must be the same"
        raise FreezeError(msg)
    if not working_tree_clean:
        msg = "the working tree has uncommitted changes"
        raise FreezeError(msg)
    verify_artifact(manifest, "corpus", corpus_bytes(cases_payload))
    verify_artifact(manifest, "manifest", corpus_inventory_bytes(corpus_inventory_payload))
    verify_artifact(manifest, "labels", label_set_bytes(adjudication))
    verify_artifact(manifest, "catalog", catalog_bytes(catalog_payload))
    verify_code_artifacts(manifest)


def git_state(repository: Path) -> tuple[str | None, bool]:
    """``(HEAD, árvore limpa)`` do repositório; ``(None, False)`` sem Git."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None, False
    return head, not status.strip()


def artifact_digests() -> dict[str, str]:
    """Digests atuais dos artefactos gerados pelo código (para relatórios)."""
    return {artifact.name: sha256(artifact.data) for artifact in code_artifacts()}
