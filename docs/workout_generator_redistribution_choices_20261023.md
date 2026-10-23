# Code-owned redistribution choices — 2026-10-23

The retained continuation2 review requested one three-session redistribution over
six occurrences. The compiler partitions that list into exact recipes, preserving
each recipe's weekly set total. Two resulting recipes contain 14 sets each and
can spread over three sessions; two contain only two sets and cannot satisfy the
approved two-set occurrence floor over three sessions. The assessed operation was
unexecutable; this did not establish that the workout requirements are infeasible.

The owning change is at assessment selection. `repair_contract` now enumerates
exact recipe/spread objectives from the original submitted draft, approved set
bounds and aliased definition catalog. It uses the existing recipe grouping,
destination-count bounds and real redistribution compiler to exclude unsupported
operations (including mixed target modes and nonweekly source sessions).

`plan_review._context` supplies these code-owned choices. Assessment and
confirmation-only review use one shared selection schema: each objective must
name one complete exact recipe and one enumerated session count. An empty menu
allows only an empty objective array. Local semantic validation checks that same
menu. No recipe IDs, contract versions, quotas, set-credit changes, requirement
relaxations, or additional model calls were introduced. No prompt contract was
expanded. Existing destination selection, conservation checks, carried repair
protection and whole-plan solver remain in place.
Non-repair dispositions can emit only an empty objective array in both wire
schemas, matching the existing local validation rule.

The choice menu establishes local compiler support only. Multiple individually
supported choices may still conflict with session duration, coverage or other
whole-plan constraints. The solver and final exact-artifact review continue to
own those checks; menu membership is not approval of a repaired workout.

## Verification

Ten new focused checks cover the 14/14/2/2 case, exact tuple selection, invalid
mixed/small/unknown recipe objectives, empty-menu strict transport, both review
routes, recipe/set conservation, exact-target preservation, and unsupported
frequency/target-mode exclusions. Thirteen selected existing checks passed for
assessment, destination-only repair and confirmation behavior. Edited files
compile and scoped diff checks pass.

Controlled replay of the actual retained continuation2 response rejects the
original mixed objective, explicitly selects three-session spreads for the two
14-set recipes, and compiles those through `compile_coordinated_repair`.
Every recipe's weekly quantity and the two-set floor are preserved; original
conversation and backup hashes remain unchanged. Zero provider calls were made.

Evidence and runtime hashes:
`build/workout_joint_priority_solver_20261023/redistribution_choices_replay_20261023/result.json`.

No paid E2E, whole-plan feasibility claim, semantic approval or export is included
in this verification.

## Authorized live attempt

The attempted continuation reused the old unexecutable assessment and stopped
before making any provider call. A fresh generation then exercised current code.
Intake invented a six-set occurrence ceiling; source review caught it. Under the
existing delegated approval authority, the controller authorized only restoring
the approved maximum of 20. A before/after comparison confirmed that this was the
only changed requirement field.

The fresh campaign used 19 provider calls across intake and its isolated
continuation, 523.39 seconds of recorded run time, and an estimated $0.098837 in
model-token cost. All three session workers completed. The joint solver returned
`unproven` at its first active objective, `duration_balance`, with 2,204 recipe
options and 6,612 placement options. The stage uses the existing 30-second solver
budget and returned no feasible incumbent; it did not prove infeasibility.

No numerical audit, semantic review, repair or export was reached. Consequently
the redistribution choice fix remains verified offline, and was not exercised
by this fresh live run. No unchanged solver retry was made. Runtime source hashes
matched and retained conversations/inputs were unchanged.

Receipt and summary:
`build/workout_joint_priority_solver_20261023/fresh_redistribution_choices_generation_continuation1_20261023/validation_summary.json`.
