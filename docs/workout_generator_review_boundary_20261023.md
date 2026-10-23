# Review boundary correction — 2026-10-23

The fresh concern-closure run stopped before adjudication because discovery returned
an extra `type: json_object` field. Its saved findings also contained contradictory
severity/basis pairs. These were review representation failures, not established
workout defects.

## Change

`plan_review._review_complete_draft` treats discovery as provisional. Its schema
continues to require meaningful finding fields, explicit concern identities,
known evidence references and complete source assessments. Non-authoritative
envelope/finding metadata is projected out. Discovery no longer requests severity;
Python derives it from basis. Valid citations are preserved and deduplicated.

Source corrections link to native concerns through a direct source citation or
shared validated current evidence. This avoids requiring discovery to repeat a
source citation in each concern. An unlinked correction still fails closed, and
adjudication must retain a linked correction as actionable or unresolved. No
synthetic finding is added.

The existing single-attempt adjudication remains the strict, non-thinking
`emit_result` boundary. Concern lifecycle, hard-blocker downgrade checks, evidence
requirements, local semantic validation and disputed-withdrawal confirmation are
preserved. No prompt expansion, contract version, model role or formatting-repair
call was added.

## Verification

23 focused checks passed, covering discovery projection, citation identity and
deduplication, severity ownership, strict provider transport/local validation,
source linkage, blocker protection and concern lifecycle. Edited Python files
compile.

The retained fresh-run response was replayed against its audited draft and source
context. FACT references were rebound by exact JSON path when reconstructing the
context. Five findings survived with citation counts 7/9/4/3/4 and canonical
severities blocking/warning/warning/blocking/blocking. The replay used two mocked
review responses and **zero provider calls**; adjudication dispositions were
controlled test inputs. Retained conversation, backup and raw response hashes were
unchanged. Evidence and runtime hashes:
`build/workout_joint_priority_solver_20261023/review_boundary_replay_20261023/result.json`.

The earlier eight-citation diagnosis came from the base schema; the active wire
schema already removed that bound. The proven live rejection was the extra `type`
field. Replay also exposed and corrected the redundant source-citation linkage.

No fresh paid E2E or export was performed. This establishes representation and
validation behavior; it does not validate the provisional semantic complaints or
prove generation reaches export.

## Soft-tradeoff continuation

The next fresh run passed numerical checks but stopped at a discovery-time
soft-tradeoff acceptance guard. Its valid citations pointed to an approved
requirement and an authorized decision instead of repeating original-source
citations. The acceptance check now runs after adjudication. It requires current
candidate evidence and either user-source evidence, approved requirement evidence,
or an active decision with extant source references including a user source.
Requirement approval and source review remain owned by intake and
`audit_workout_plan`'s `require_approved_requirements` boundary; the review helper
does not independently reinterpret or reapprove those fields. Decision provenance
is resolved from existing records, never reviewer-supplied authorization.

Carried closure still requires the same group's explicit terminal status and a
subset of its validated evidence. Hard findings cannot use soft closure. Review
errors use the existing evidence and confirmation path. No prompt text or version
was added. The exact saved response passes the offline controlled adjudication
replay with zero provider calls in
`build/workout_joint_priority_solver_20261023/soft_tradeoff_replay_20261023`.
Nineteen focused regression checks passed; runtime and tests compile.

The authorized paid continuation reached adjudication using two new provider
calls (16 campaign calls total), estimated model-token cost $0.018347. It stopped
without export: adjudication selected `advisory` for two blocking findings, a
combination permitted by its wire schema but forbidden by local semantic
validation. The blocker was preserved; no dismissal or repair was fabricated.
Runtime hashes matched, and the original conversation was unchanged. Evidence:
`build/workout_joint_priority_solver_20261023/fresh_review_boundary_continuation1_20261023/validation_summary.json`.
The next owning correction is to make per-finding structured disposition choices
match the existing validation rules, rather than offer forbidden choices and
reject them after a paid call. No additional paid retry was started.

## Legal disposition choices

`review_assessment` now derives each finding's structured disposition alternatives
from the same rule used by local validation. Blocking findings cannot select
`advisory`; advisory findings cannot select `repair` or `unresolved_capability`.
Proof-bearing withdrawal remains available and retains its existing validation and
confirmation requirements. No blocker is automatically downgraded or converted.

Nine focused checks passed, including the saved contradictory response rejected
by the new wire schema and controlled legal alternatives accepted by that schema.
The schema remains compatible with strict provider output. Runtime/tests compile.
The authorized continuation is recorded separately under
`build/workout_joint_priority_solver_20261023/fresh_review_boundary_continuation2_20261023`.

That continuation completed review in two new provider calls (18 campaign calls,
estimated new model-token cost $0.016089), with three repair dispositions and one
accepted advisory tradeoff. No review validation failure occurred. It stopped
before repair because the assessed redistribution requested three-session spread
for a list that includes small independent recipes; code partitions the list by
recipe and cannot split each one over three sessions. A controlled offline
expansion also rejected the assessed spread. This is a repair-intent/capability
boundary, not proof the workout requirements are infeasible. No repair or export
occurred, and no extra paid retry was started. Runtime hashes matched and the
previous retained conversation was unchanged; see continuation2's
`validation_summary.json`.
