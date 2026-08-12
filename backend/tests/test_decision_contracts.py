"""A2.1 — os contratos mínimos de decisão são exatamente os aprovados pela A2.0.

Testes puros: sem PostgreSQL, sem ``TestClient``, sem fornecedor, sem fixtures
institucionais. O estilo segue o prior art de
``test_evidence_retrievability_unit.py``, que testa contratos de domínio sobre
sujeitos construídos à mão.

Ao contrário da maioria dos testes do projeto, estes fixam **o conjunto exato de
membros** de cada enumeração. Normalmente isso seria excesso de rigidez; aqui é
o próprio objeto do teste, porque o conjunto de categorias *é* o contrato que a
A2.0 estabilizou. Acrescentar um valor sem passar por uma decisão de modelação
deve partir um teste.

Os testes que verificam **ausências** — ``NONE``, ``AMBIGUOUS``,
``INSUFFICIENT_EVIDENCE`` — são redundantes face às asserções de conjunto exato,
e essa duplicação é deliberada: cada um documenta uma decisão explícita da A2.0
e falha com uma mensagem que a nomeia.

Não se testa aqui qualquer associação entre contratos. ``PERSONAL_DATA_REQUIRED``
não "leva a" ``ESCALATE``, ``NOT_ANSWERABLE`` não "leva a" ``ABSTAIN``: essas
decisões estão em aberto, e um teste que as afirmasse fixaria uma resposta que a
investigação ainda não deu.
"""

import ast
import inspect
import sys

import pytest

from app.decision import contracts
from app.decision.contracts import (
    AnswerabilityClass,
    DecisionOutcome,
    RequestConstraint,
    ScopeClass,
)

_MODULE_TREE = ast.parse(inspect.getsource(contracts))


def test_scope_class_has_exactly_the_two_approved_members() -> None:
    assert {member.name: member.value for member in ScopeClass} == {
        "IN_SCOPE": "in_scope",
        "OUT_OF_SCOPE": "out_of_scope",
    }


@pytest.mark.parametrize("name", ["PARTIALLY_IN_SCOPE", "UNKNOWN", "UNDETERMINED"])
def test_scope_class_has_no_intermediate_or_unknown_member(name: str) -> None:
    """A A2.0 rejeitou graus intermédios de âmbito e um valor "não sei"."""
    assert name not in ScopeClass.__members__


def test_request_constraint_has_exactly_the_single_approved_member() -> None:
    assert {member.name: member.value for member in RequestConstraint} == {
        "PERSONAL_DATA_REQUIRED": "personal_data_required",
    }


def test_request_constraint_has_no_none_member() -> None:
    """``NONE`` seria um valor artificial dentro do conjunto de restrições."""
    assert "NONE" not in RequestConstraint.__members__


def test_absence_of_constraints_is_the_empty_collection() -> None:
    """A ausência de restrições representa-se por ``frozenset()``.

    A anotação de tipo é parte da asserção: é o ``mypy`` que confirma que a
    coleção vazia é uma representação válida, sem precisar de um membro do enum
    nem de um alias que ainda não tem consumidor.
    """
    unconstrained: frozenset[RequestConstraint] = frozenset()

    assert not unconstrained
    assert RequestConstraint.PERSONAL_DATA_REQUIRED not in unconstrained


@pytest.mark.parametrize(
    "name",
    [
        "AUTH_REQUIRED",
        "ADMINISTRATIVE_ACTION_REQUIRED",
        "HUMAN_REQUIRED",
        "HUMAN_HANDOFF_REQUESTED",
        "TRANSACTION_REQUIRED",
        "SENSITIVE_DATA",
    ],
)
def test_request_constraint_has_no_speculative_member(name: str) -> None:
    """Valores candidatos que a A2.0 adiou por não mudarem nenhuma decisão."""
    assert name not in RequestConstraint.__members__


def test_answerability_class_has_exactly_the_three_approved_members() -> None:
    assert {member.name: member.value for member in AnswerabilityClass} == {
        "FULLY_ANSWERABLE": "fully_answerable",
        "PARTIALLY_ANSWERABLE": "partially_answerable",
        "NOT_ANSWERABLE": "not_answerable",
    }


def test_answerability_class_has_no_ambiguous_member() -> None:
    """Subespecificação é ortogonal à cobertura da evidência, não um valor dela."""
    assert "AMBIGUOUS" not in AnswerabilityClass.__members__


def test_answerability_class_does_not_reuse_the_insufficient_evidence_name() -> None:
    """O nome está ocupado pelo estado público do answering; ver ``NOT_ANSWERABLE``."""
    assert "INSUFFICIENT_EVIDENCE" not in AnswerabilityClass.__members__
    assert "insufficient_evidence" not in {member.value for member in AnswerabilityClass}


@pytest.mark.parametrize("name", ["UNKNOWN", "UNANSWERABLE"])
def test_answerability_class_has_no_extra_member(name: str) -> None:
    assert name not in AnswerabilityClass.__members__


def test_decision_outcome_has_exactly_the_four_approved_members() -> None:
    assert {member.name: member.value for member in DecisionOutcome} == {
        "ANSWER": "answer",
        "CLARIFY": "clarify",
        "ABSTAIN": "abstain",
        "ESCALATE": "escalate",
    }


@pytest.mark.parametrize(
    "name",
    ["RETRIEVE", "REJECT", "ERROR", "SEARCH_AGAIN", "WAIT", "HANDOFF"],
)
def test_decision_outcome_has_no_extra_member(name: str) -> None:
    """Etapas internas e falhas técnicas não são desfechos de decisão."""
    assert name not in DecisionOutcome.__members__


@pytest.mark.parametrize(
    "enumeration",
    [ScopeClass, RequestConstraint, AnswerabilityClass, DecisionOutcome],
)
def test_values_are_stable_explicit_snake_case_strings(
    enumeration: type[ScopeClass | RequestConstraint | AnswerabilityClass | DecisionOutcome],
) -> None:
    """Sem consumidores hoje, mas um valor implícito seria uma migração amanhã."""
    for member in enumeration:
        assert isinstance(member, str)
        assert member.value == member.name.lower()


@pytest.mark.parametrize(
    "name",
    ["RequestSpecificity", "DecisionReason", "DecisionPolicy", "RetrievalOutcome"],
)
def test_deferred_contracts_are_not_defined(name: str) -> None:
    """Contratos que a A2.0 deixou por estabilizar não têm placeholder."""
    assert not hasattr(contracts, name)


def test_module_imports_only_from_the_standard_library() -> None:
    """O módulo é independente de retrieval, answering, ORM e framework HTTP."""
    imported_roots: set[str] = set()
    for node in ast.walk(_MODULE_TREE):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "sem imports relativos"
            assert node.module is not None
            imported_roots.add(node.module.split(".")[0])

    assert imported_roots <= set(sys.stdlib_module_names)


def test_module_declares_only_the_four_enumerations() -> None:
    declarations = [
        node.name
        for node in _MODULE_TREE.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    ]

    assert declarations == [
        "ScopeClass",
        "RequestConstraint",
        "AnswerabilityClass",
        "DecisionOutcome",
    ]


def test_module_contains_no_policy() -> None:
    """Sem funções, sem ramificações, sem matriz: só declarações de valores.

    É esta asserção que impede que a próxima alteração acrescente
    discretamente um ``decide()``, um ``match`` sobre os contratos ou um mapa
    ``constraint -> outcome`` enquanto O1–O6 continuam abertas.
    """
    forbidden = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Lambda,
        ast.If,
        ast.IfExp,
        ast.Match,
        ast.For,
        ast.While,
        ast.Dict,
        ast.DictComp,
    )

    offenders = [
        type(node).__name__ for node in ast.walk(_MODULE_TREE) if isinstance(node, forbidden)
    ]

    assert offenders == []
