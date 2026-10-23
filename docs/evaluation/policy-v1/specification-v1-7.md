# Working specification v1.7: implementation correspondence

Source: `Politica_decisao_v1.7_e_protocolo_de_rotulagem.docx`, 1 October 2026,
sections 5 and 9.1–9.3, pages 8–9 and 14–15. This is a working research
specification, subject to calibration. This correspondence does not claim
supervisor approval, originality, or completed evaluation.

| Metric | Definition implemented |
| --- | --- |
| M1 | ANSWER when ANSWER is not acceptable; report numerator and denominator by family. |
| M2 | Non-ANSWER outside the acceptable set when ANSWER is acceptable. |
| M3 | Preferred action × produced action; strict/acceptable agreement and precision/recall per action. Technical failures are separate. |
| M4 | Non-ESCALATE among cases whose **preferred** action is ESCALATE. Other acceptable actions do not remove a case from this strict denominator. |
| M5 | Correct destination among acceptable produced escalations, and among all preferred-escalation cases with a destination. |
| M6 | Inadmissible citations resolved within each condition's own packet; retain documentary identity. |
| M7 | Human rubric: support/completeness, declared gap, material/covered clarification, temporal notice, and escalation without claiming transmission. N/A is distinct from failure. |
| M8 | Dimension estimation errors, uncertainty and disagreements against adjudication. |
| M9 | Frozen-input replay plus human inspection; multiple/indeterminate causes are allowed. Replay alone is not causal proof. |

Over-escalation remains a supplementary named indicator. It is not renamed M4.

| Principle | Mechanism | Implementation / evaluation |
| --- | --- | --- |
| DP1 | Decompose elementary judgments and combine by explicit rules before generation. | `pipeline.py`, `policy.py`; M1/M2, B1-plena and B1-composição. |
| DP2 | Admissibility first; permitted temporal diagnostic changes the message, not the action. | D0, R11/R12, `messages.py`; F02/F03, M6, H5b and M7. |
| DP3 | Clarify only material, user-distinguishable readings with admissible support. | D3, R06; F07/F08/F09 and separate F15. The conservative option can be rejected in calibration. |
| DP4 | Recommend a competent human service when it can advance the request. | D6, R02/R04/R07/R11; M4/M5 and over-escalation. E1 does not transmit the case. |
| DP5 | Answer supported parts and declare gaps, unless the partial answer misleads. | D4, R10/R11; F05 and the M7 gap criterion. |
| DP6 | Reconstruct decisions while separating protected audit, model context and public message. | `decision_records`, replay, protected provenance; completeness and expert appraisal. |

## Before human annotation

Cases have `family` (F01–F15), `source_kind` (`real` or `synthetic`) and
`expected_snapshot_id`. The snapshot exporter only binds human-authored cases
to corpus identity; it does not find answers or create labels. Each human
label has `trace`: family, source kind, snapshot, written rationale, items
with support and frozen **chunk IDs**, and material readings with evidence.
Conflicts include the item, evidence and shared application conditions.

Legacy technical fixtures may omit trace metadata. Formal evaluation refuses
missing or inconsistent trace. Existing human labels are never auto-migrated.
Adding optional fields changes the generated schema digest; regenerate the
schemas and freeze all new artefacts before a formal run.

F14 is always reported separately. Synthetic sources never enter the main
real-source aggregate. Cases of F06/F14 built synthetically must be identified
as such; their conclusions are limited accordingly.

## Analysis plan

H1/H1b compare M1 of P-e2e with B0, B1-plena and B1-composição using a
two-sided exact McNemar test and Holm adjustment over those three comparisons.
A supported improvement also requires a negative observed difference. H2
reports the paired M2 difference. The proposed 5 percentage-point margin is
not treated as justified merely because it is configured; power/precision
and practical relevance must be justified before a confirmatory claim.

H3 reports oracle agreement per rule. H4 is exploratory and compares excessive
clarification in F04/F08/F09; inspect F07 and F15 separately. H5 is descriptive
M6 in F02/F03. H5b measures the composer's temporal-notice flag in F02; it
does not measure usefulness. H6 reports under-/over-escalation and uncertainty.

The first pre-numbered run is primary. The three runs do not multiply N.
Freeze this plan and all runtime parameters before the held-out run. No
technical test or scripted fixture is a human annotation or a scientific
evaluation result.
