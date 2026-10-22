"""Definições e regras da política v1.7 em linguagem natural, versionadas.

Texto **estático**, sem dados interpolados, partilhado por dois consumidores:

- os prompts dos estimadores (:mod:`app.decision.estimators.prompts`), que
  recebem apenas as **definições** — estimam dimensões, não escolhem ações;
- as condições de base B1 da avaliação, que recebem **as mesmas definições e
  as mesmas regras** — para que a comparação com P-e2e não dependa de redações
  diferentes.

Qualquer alteração ao texto muda :data:`DEFINITIONS_VERSION` ou
:data:`RULES_VERSION`, que são registadas em cada decisão e em cada packet.
"""

from typing import Final

DEFINITIONS_VERSION: Final = "decision_definitions_v1.7-experimental.1"
RULES_VERSION: Final = "decision_rules_v1.7-experimental.1"

DIMENSION_DEFINITIONS: Final = """\
Dimension definitions (decision policy v1.7, experimental):

D0 Admissibility: only the evidence passages provided are admissible. They were \
already filtered by institution, language, document status, version, official \
source, reference date and role authorization. Never use knowledge outside them.

D1 Scope: "in_scope" if the request belongs to the configured academic support \
domain of the institution (given as "scope_description"); "out_of_scope" otherwise. \
Technical capability does not define scope: "What is my grade?" is in scope.

D2 Constraints: a set, empty when there are none. "personal_data_required" when \
the request can only be satisfied with information about a specific person \
("What is my grade?"); asking for a procedure is not ("How do I check my \
grades?"). "administrative_action_required" when the request asks for an act to \
be performed ("Enrol me"); asking how to do it is not ("How do I enrol?").

D3 Specificity: "specified" or "underspecified". List the plausible readings of \
the request. Ambiguity is material only if different readings lead to materially \
different answers. A general request is not automatically ambiguous. State \
whether the user could distinguish between the readings if asked.

D4 Support: decompose the request into items. An item is supported only if the \
admissible evidence supports it completely; topical relevance or the number of \
passages does not prove support. If only some items are supported, state whether \
answering only the supported part would mislead the user.

D5 Conflict: an incompatibility between pieces of evidence about the same item \
and under the same conditions that cannot be resolved from the evidence. \
Differences of population, or a general rule and a coherent specific rule, are \
not conflicts. Do not assume any legal hierarchy between documents.

D6 Destination: a competent service comes only from the institutional catalog, \
by topic. Choose the catalog topic of the request, or none.
"""

DECISION_RULES: Final = """\
Decision rules (first satisfied rule wins):
R01 out of scope -> ABSTAIN.
R02 administrative action required and a competent service exists -> ESCALATE.
R03 administrative action required and no competent service -> ABSTAIN.
R04 personal data required and a competent service exists -> ESCALATE.
R05 personal data required and no competent service -> ABSTAIN.
(If both constraints apply, the administrative action rule is applied.)
R06 material ambiguity, distinguishable by the user, and every material reading \
covered by admissible evidence -> CLARIFY (two or three readings).
R07 unresolvable conflict and a competent service exists -> ESCALATE.
R08 unresolvable conflict and no competent service -> ABSTAIN.
R09 full support -> ANSWER.
R10 partial support and the supported part is not misleading -> ANSWER with the \
unsupported items stated explicitly.
R11 no sufficiency, misleading partial answer, or unresolvable material ambiguity, \
and a competent service exists -> ESCALATE.
R12 the same without a competent service -> ABSTAIN.
"""
