# Shared policy and validation boundary fixes

Implemented using the existing requirements, solver, audit, decisions and approval paths. No requirement minimum, muscle credit, exercise restriction, demand preference, call limit, or model tier was changed. No Nordic cap was activated. No contract version was added.

## Dose selection and explicit family bounds

Workload economy retains its approved place before family diversity. The diversity seam now preserves the workload objective and explicitly development-intent role doses, leaving incidental inclusion-role counts free to change. Solver receipts disclose locked development roles and unlocked inclusion roles; candidate comparison uses the same rule. This removes the arbitrary 13-Nordic incumbent lock without promising a particular Nordic count.

Optional `familySetBounds` requirements express an explicitly approved weekly family minimum/maximum; equal bounds express a target. The intake tool enumerates reviewed family identities from library evidence. Unknown families fail before the requirements preview. No bound is inferred from qualitative dissatisfaction. Counts include workout frequency and fixed workouts. The joint MILP, count allocator, exact candidate audit, reviewer artifact audit and pre-export audits enforce the same bounds. Selected exercises with unknown family membership cannot be assumed outside the bounded family. Singleton recipe screening does not apply whole-week floors to an isolated recipe.

## Decisions and human approval

The existing independently audited alternative approval gate remains the only path that accepts a numerical alternative. A focused regression confirms newer unresolved diagnoses cannot leave stale alternative approvals available. Existing source-backed decisions retain their current authority; scoped acceptance does not waive hard requirements or verify unknown capacity.

`/clear keep-requirements` starts a fresh conversation with approved requirement values and reusable source-backed choices. Ordinary `/clear` remains blank. Fresh policy carry excludes old plans, menus and candidate-specific acceptances. Matching library and approval context permit reuse; missing/changed library identity, removed alternative context or failed capability checks requires review and confirmation. Source references are remapped after filtered context, and alternative previews are not retained merely to preserve hashes. The existing regional-target representability checks remain in place; family bounds now receive the same approval-time validation. No separate policy database or capability ledger was introduced.

## Exact-artifact descriptions and bounded review correction

Generated session descriptions are neutral, code-owned text before prescription workers and the first semantic review. Full-body descriptions require the corresponding approved per-session coverage roles. Existing session names and fixed workouts remain intact. An assessed label-only repair exposes only name/description updates, not allocation, frequency, ordering or redistribution edits.

The latest review failure had a nested `anyOf` citation validation error. The shared detector now finds nested evidence-reference errors so the original judgment is retained and the existing single correction receives only citation/support fields. Advisory citation corrections are now applied instead of validated and discarded. This avoids turning a citation correction into a new semantic review; incompatible concern dispositions remain invalid. No additional model retry or prompt contract was added.

## Verification

Focused tests cover dose-lock/comparator agreement, fixed-plus-variable family exposure, current library UUID evidence, unknown evidence rejection, intake-to-audit bounds, label-only repair scope, safe fresh policy carry, alternative gates, generated descriptions and bounded citation correction. Runtime compilation and retained provider-free replay are recorded in the companion validation artifacts. No paid E2E was run for this implementation. A native feasible plan is not a new reviewed export or proof of personal suitability.


The retained production replay produced 88 weekly physical sets, with 12 Nordic and 3 RDL sets and no native audit errors, without a Nordic cap. Lateral-delt and vertical-pull development doses remained 6 sets each. Session estimates were 4297/4117/4199 seconds (180-second spread). The earlier approved objectives and role-placement stages proved optimal; final muscle distribution returned a validated feasible incumbent at its time limit. Rear-delt coverage changed from 6 to 2 sets, so the lower family score is not proof of superior overall programming. Nordic reliance remains substantial.

Final integration verification: 15 focused cases passed after the last policy/repair changes, alongside the earlier 22-case focused checkpoint, 8 solver/fixture checks and 2 corrected count-repair mocks. All 20 edited Python files compiled. Five old test mocks/fixtures were aligned with current explicit objectives, valid incumbent setup and count-only repair output; their behavioral assertions remain. No broad suite is claimed.

`build/workout_policy_boundary_fix_20261028/validation.json` records final source hashes and verification. The native replay's frozen sources matched at execution; the only subsequent runtime edits are policy-carry safeguards and label-only proof reuse in planning_decisions.py/interactive_shell.py. Solver/audit code is unchanged from the successful replay. A later reviewed reusable decision cannot silently be replaced with an older approval snapshot: policy carry asks for a refreshed approval first.


## Subsequent fresh live E2E

The fresh run in `build/workout_boundary_live_e2e_20261028/fresh_e2e_v2` reached a verified exact export: `workout_plan_2026-10-28_141758.json`. The initial launch in the separate `fresh_e2e` folder failed locally before any provider request because the new bounds schema used required-only anyOf branches that the strict adapter cannot project. The wire schema was simplified; the existing shared validator still requires at least one approved bound. Three focused cases and the full 311-definition intake-schema projection passed before restarting.

The successful run used 22 provider requests, 1,122,413 tokens and about 704 seconds of supervised wall time (model-token rate-card estimate USD0.159). It required clarification of the already approved sumo exclusion/back accounting and normal requirements/export confirmations. There was one final semantic review, one advisory and no repair call. Runtime hashes matched; retained source conversation, backup and image were unchanged. Export and guidance parity with the exact reviewed artifact passed.

The final export has 88 weekly sets, including 12 Nordic-family sets (7 unweighted,5 weighted-vest) plus3 dumbbell RDL sets. Lateral raises and vertical pulling have6 sets each. Session estimates are4605/4367/4326 seconds (279-second spread). This is a successful supervised generation, not evidence of unaided reliability. Nordic-family reliance and personal ability to perform loaded Nordics remain unverified; Session C contains both Nordic variants. One hammer-curl definition is family-unclassified, so its family-concentration score cannot establish full-menu diversity or be directly compared with a differently classified pool. Rear-delt coverage is2 sets; final muscle-distribution optimality remains unproven. See the run's `e2e_report.json`, `verified_export.json` and `stage_rejections.json`.
