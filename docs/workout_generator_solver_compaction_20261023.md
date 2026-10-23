# Isolated joint-solver compaction — 2026-10-23

The user explicitly authorized investigating and implementing solver formulation
compaction after the fresh generation stopped with `joint_planning_unproven`.
This extends the earlier brief's solver scope for this bounded change; hard
requirements, approved priority order and final production validation remain
unchanged.

## Changes and preserved behavior

The first selected exercise determines the one-time setup deduction in the
duration equation. The old formulation used a row for every earlier/later block
pair to preserve stable topological first-block order. The replacement computes
block readiness from selected approved predecessors and uses a cumulative OR
prefix in stable source-rank order. It preserves the same selected first block
and exact setup arithmetic while avoiding quadratic source-order rows.

`allocation._milp_solve` retains its `(status, candidate)` return and accepts an
optional diagnostics dictionary. It records raw termination reason, incumbent
availability/validation, objective bound, gap, node count, matrix-build and solve
time, and the reason a candidate was accepted or rejected. Joint stage receipts
and alternative summaries retain these diagnostics. Diagnostics do not enter
mathematical constraints, fingerprints or acceptance decisions.

Feasible-incumbent retention already existed. Its focused regression passed, so
no duplicate fallback or retry machinery was added. A later optimization timeout
retains a previously validated candidate and reports nonoptimal status; the exact
production audit still determines whether that candidate can be returned.

An independent option audit found no safely removable duplicate emitted recipe
variants in the retained case. Placement options carry session/provenance and
preservation differences. No recipe options, movement choices, rest choices,
credits, quotas, requirements or approved priorities were removed or relaxed.
No model prompts, contract versions or dependencies were added.

## Controlled retained-case comparison

The isolated harness uses the exact saved unsolved submission, approved
requirements, equipment, history and messages. Each solver stage retains the
existing 30-second limit. The baseline snapshot's `joint_planning.py` matches the
failed live run's hash exactly. Of its 52 Python files, only `allocation.py`
differs from the live hashes: additive diagnostics instrumentation was already
present when the baseline was frozen. The baseline mathematical formulation is
unchanged.

| Measurement | Baseline | Compact formulation |
|---|---:|---:|
| Prescription recipes | 2,204 | 2,204 |
| Placement options | 6,612 | 6,612 |
| First-stage constraints | 8,723 | 2,357 |
| First-stage nonzero coefficients | 460,446 | 219,868 |
| Source-order constraints | 7,884 | 435 |
| First-stage result | Timeout, no incumbent | Timeout, valid incumbent |
| Final numerical result | Unproven | Feasible, not proven optimal |
| Exact production audit errors | No candidate to audit | 0 |

The compact model completed in 93.09 seconds including model preparation and a
second optimization stage. Its first solver stage took 30.51 seconds including
matrix construction; the next distribution stage took 32.25 seconds and found no
new incumbent. Existing retention returned the verified first-stage candidate.
The baseline stopped after 66.25 seconds without a candidate. These are time to
different outcomes, not a claim that total successful runtime decreased by a
particular percentage.

Session estimates were 5,277 / 5,276 / 5,271 seconds (87.95 / 87.93 / 87.85
minutes): all under 90 minutes, with a six-second range. These remain estimates,
not measured execution time. The later muscle-distribution objective was not
completed, so this result does not establish optimal muscle or demand balance.

All retained input and runtime hashes stayed unchanged during each replay.
Provider calls: **0**. No semantic review, approval or export was performed.
Evidence: `build/workout_joint_priority_solver_20261023/solver_compaction_validation_20261023/validation_summary.json`.

## Scoped verification

Fifteen focused checks passed across ordering equivalence/setup arithmetic,
termination diagnostics, stage/summary propagation and incumbent retention.
Ordering coverage includes every nonempty selection in a small case, agreement
with the production constructor, rejection of wrong first blocks, and an exact
300-second setup-deduction change under an approved reversed order. Edited files
compile and scoped diff checks pass.

Two old ordering fixtures inspected by a subagent failed before reaching the
solver because they still contain the removed `placementNotes` field. They were
not changed or used as evidence of this implementation's correctness. No broad
suite or paid E2E was run. One saved-case comparison is not a reliability proof
for every possible exercise menu.
