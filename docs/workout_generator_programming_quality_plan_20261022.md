# Workout generator programming quality implementation plan

Status: offline implementation and focused verification complete. Shared facts, current-candidate selection context and emphasis/practicality policy are implemented. Live semantic improvement remains unmeasured; production multi-candidate search is deferred and recovery-aware adaptation awaits source observations.

## Authority and purpose

This is an additive plan for improving exercise selection and allocation, requested after the retained generation exported successfully. Read `workout_generator_fix_brief_20261021.md` first. Its simplification and anti-compensation rules remain operative. This document does not claim that the earlier brief's remaining migrations are complete. `workout_generator_architecture.md` remains a historical journal.

Goal: choose better-supported allocations among feasible plans while preserving approved requirements, deterministic arithmetic, exact-artifact review and export, bounded execution, and resumability. Numerical acceptance is necessary but does not demonstrate optimal programming or personal tolerance.

The uncommitted worktree is the baseline. Preserve it, retained conversations and existing exports; do not commit unless asked. No runtime changes or paid calls are authorized merely by this document's existence. Apply the current conversation's authorization when executing it; earlier delegated approvals are recorded history, not new training preferences.

## Baseline and evidence

Retained acceptance case: `build/workout_fix_program_20261021/fresh_artifact_e2e_resume57/`.

- Export: `workouts/workout_plan_2026-10-22_043712.json`.
- Numerical report: matching `.audit.json`; guidance: matching `.guidance.md`.
- Export verification: `verified_export.json`; completion scope: `completion_audit.json`.
- Runtime provenance: `source_hashes.json`; rejection data: `stage_rejections.json`.
- Session working sets: 26 / 27 / 28; estimated minutes: 76.4 / 79.0 / 79.3.
- Weekly exercise exposures include 15 split-squat sets, 14 Nordic sets, 11 supported-row sets and 4 pull-up sets.
- Shoulder accounting: 6 direct sets plus 15 secondary credits; lateral raises: 2 sets. Calves and abs: 1 direct set each.
- These identify allocation questions, not proven fatigue violations or new minimums. Count secondary credits as already weighted values, not raw indirect set counts.
- This case is a resumed generation using the experimental two-pass review. It is not a fresh-start reliability benchmark.

Before each measured implementation checkpoint, compare current runtime files with the retained run's source hashes. Record differences; never attribute a snapshot's result to newer worktree code. Keep new evidence in a separate build directory, never overwrite the baseline.

## Alternatives and decision

1. Shared facts available during selection: lowest change surface, reuses current roles and calculations; judgment can still vary.
2. New numerical solver penalties: repeatable, but requires justified definitions and weights, and risks optimizing unsupported assumptions.
3. Multiple complete candidate plans: exposes trade-offs, but increases solve time, payload and potentially paid calls.

Start with option 1. Introduce a bounded baseline-versus-alternative comparison only if retained-case evidence establishes a benefit. Defer option 2. No general search framework, new reviewer role, overall quality score or extra mandatory LLM stage.

## Ownership and flow

Approved requirements + equipment/library + comparable history
-> existing menu selection
-> existing solver and numerical audit
-> shared programming facts from materialized prescriptions
-> existing selection/correction opportunity when needed
-> code rendering
-> independent review of exact final artifact and shared facts
-> existing approval/export path.

| Owner | Responsibility | Must not do |
| --- | --- | --- |
| Requirements intake | Preserve explicit priorities and clarify material ambiguity | Freeze candidate menu choices into user requirements |
| Library/history | Supply supported identity, execution and observed performance | Infer technique, regional stimulus or capacity from names or missing records |
| Audit/shared facts | Compute exposures, volume contributions, supported setup and time facts | Declare personal tolerance or invent fatigue scores |
| Selector | Choose suitable available movements and explain material allocation trade-offs | Construct precise arithmetic or silently change targets |
| Solver | Assign feasible prescriptions using approved objectives | Select recipes never offered or manufacture programming preferences |
| Reviewer | Judge exact artifact against original requirements and evidence | Turn preferred alternatives or missing personal data into automatic failures |
| Export | Preserve reviewed execution and guidance | Recompute a different plan after approval |

## Stage 1 — shared facts, behavior unchanged

Priority: foundation for concentration and contribution visibility.

Current source anchors: `plan_review.py` builds `programmingSummary` inside review context around lines 990–1015; `generation_audit.py::audit_workout_package` owns numerical reporting. Verify current symbols/callers before editing; line numbers are navigation hints.

- Extract summary computation into the existing audit layer, keeping review-specific evidence formatting in review. Reuse audit results and canonical plan/occurrence identity; avoid introducing a separate plan representation or import cycle.
- Initially preserve existing summary meaning and shape. Review remains tied to `finalArtifact`; planner consumption is added only in stage 2.
- Facts include exercise weekly/per-session doses, frequency, direct versus weighted secondary contributions, movement coverage, timing assumptions and unverified execution-time status.
- Reuse supplied unilateral and equipment metadata. Report unsupported details as unknown; absence must not become zero or a guessed classification.
- Keep occurrence identity for prescription differences even when exposures are grouped by library definition. Grouping must not erase distinct equipment or execution configurations.

Exit: retained artifact produces equivalent review facts, unchanged prescriptions/guidance, and unchanged export parity. One focused regression covers identity/configuration grouping and shared-summary parity. No live calls.

## Stage 2 — better selection with the same roles

Priority 1: assess concentration of repeated work. Priority 2: expose direct/indirect and supported regional emphasis.

Source anchors: `planner_context.py::_movement_selection_context`, `request_planning_state`; existing menu selection/compiler in `planning_tools.py`; `plan_review.py` exact-artifact context.

- Surface a compact projection of the shared summary in the existing planner request after a solved candidate exists. Before any candidate exists, use available library/history facts rather than fabricated allocation totals.
- Present repeated dose and session distribution as facts. Do not tag a movement as demanding eccentric or axially loaded unless existing typed metadata or explicit execution supports that statement.
- Keep aggregate approved muscle credits unchanged. Show regional information only when supported; state what is unknown. Do not restore removed `placementNotes` or local-guidance repair machinery.
- Reuse existing menu selection and compiled intents for a supported substitution/redistribution. Offer keeping the candidate as a valid decision. No mandatory diversity quota or extra review pass.
- Reuse existing request bounds; no new unbounded iteration. Unsupported or infeasible alternatives do not justify weakening the baseline constraints.

Exit: controlled saved cases demonstrate correct exposure facts and that selection can address a documented allocation concern without inventing constraints. Acceptable repeated exercise use and unequal push/pull counts remain acceptable. If judgment does not improve, do not add prompt clauses as compensation; inspect missing evidence and decision ownership first.

## Stage 3 — emphasis and practical execution

Priority 3: distinguish inclusion from intended emphasis. Priority 4: practical distribution beyond total duration.

Source anchors: `planning_tools.py` requirements intake and `requirement_accounting.py`; `programming_guidelines.py`; `joint_planning.py`; `generation_audit.py` timing.

- Use source-backed qualitative priorities already representable by intake/accounting. Clarify inclusion versus development emphasis only if unspecified and material to allocation; do not introduce mandatory priority fields for every muscle.
- One set may meet an inclusion requirement; it is not automatic evidence that a development priority was served. Conversely, do not invent numerical calf/ab or regional minimums.
- Reuse order rules, setup allowances, unilateral timing and approved `distribution` objective. The current sets-squared-per-occurrence objective spreads dose; it does not model physiological recovery or guarantee weekly variety.
- Expose known equipment transitions and time assumptions. Do not add time charges twice or equate similar durations with similar fatigue.
- New solver objectives, weights or exercise classifications require a separate evidenced proposal. This stage does not redesign the solver or add new mandatory balance ratios.

Exit: inclusion-only and development-priority variants lead to appropriately different assessments; missing regional data stays uncertain. Practical improvements preserve numerical limits, prescribed rest, equipment eligibility and reviewed-artifact parity.

## Stage 4 — bounded comparison, only if justified

Use the existing baseline plus at most one independently feasible alternative for the initial experiment. This is an offline evaluation design, not a new production candidate registry or automatic second generation.

- Hold requirements, equipment, history, accounting factors and timing assumptions fixed.
- Compare concentration, supported stimulus allocation, priorities, practical execution, feasibility and uncertainty. Record trade-offs in ordinary evidence; do not collapse them into a single score.
- The alternative need not win. Reject changes that merely make counts symmetrical, add cosmetic variety, hide work through credit changes or transfer problems to another session.
- If comparison is worth retaining, fit it into the existing selector/reviewer roles. Measure incremental tokens, calls, solve time and rejections before adopting it.

Exit: documented benefit on identified concerns without a false-rejection increase, new requirement violations or an extra recurring repair cycle. Otherwise retain the simpler facts-first implementation.

## Stage 5 — adaptation from observations

Priority 5 for first-plan work; potentially highest value for later personalization.

Source anchors: `training_history.py::compact_training_evidence`, `pool_execution_contexts` and existing planner history projections.

- Audit what completion, prescribed/performed dose, effort and measured duration data already exist before adding storage or UI.
- Reuse comparable observations with their execution/equipment context and recency. Missing RIR, recovery or timing is missing evidence, not a zero or inferred failure.
- An unfinished session does not establish failure of an individual exercise. Separate observed events from interpretation.
- Use observations to inform the existing selection and audited adjustment path. Recovery guidance continues to require re-audit before dose changes.
- If important observations are unavailable, document the gap and a narrowly scoped follow-up; do not expand this Python change into mobile/Wear collection work automatically.

Exit: saved examples distinguish actual comparable evidence, related-but-incomparable evidence and missing information. Adjustments remain feasible and source-compliant; unsupported personal conclusions are absent.

## Verification and measurement

Reuse retained artifacts and existing tests before adding new fixtures. Controlled variants live separately from retained conversations. Every case records its changed inputs and independently checked expected outcome; do not label a subjective preferred plan as the only correct answer.

Minimum case matrix:

| Case | Expected observation |
| --- | --- |
| Actual final export | Exact facts; concentrated work is visible, not automatically rejected |
| Dose redistributed within unchanged totals | Per-session exposures update; unrelated prescriptions remain stable |
| Same aggregate shoulder credits, different direct contribution | Difference visible; no invented regional target |
| Inclusion-only versus explicit development emphasis | Assessment follows source priority |
| Acceptable repetition / unequal push-pull totals | No automatic variety or equality complaint |
| Missing technique or capacity data | Unknown/qualified assessment rather than fabricated failure or approval |
| Changed final order or guidance | Reviewer sees the changed artifact; corrected ordering receives no stale complaint |
| Setup/unilateral timing variant | Supported time differences accounted once; assumptions disclosed |

Use the smallest relevant subsets of existing reviewer-facts, review-representation, planner-context, menu-selection, programming-audit, joint-prescription and history tests. Add only focused missing coverage. Run `py_compile` for edited Python files and `git diff --check` once per coherent checkpoint. No broad suites or Android builds for Python/docs-only changes.

Track numerical compliance, semantic findings/dispositions, false complaints on controls, model calls/tokens, request size, solver/total time, per-stage rejection counts, and final export parity. Deterministic replay proves plumbing; it does not prove a model will choose better. Any live judgment experiment must record actual responses and its limited scope.

Before a paid run: finish offline controls, report the concrete comparison and check current authorization/balance. Use Flash as requested; do not suggest Pro as a substitute for missing evidence or poor task design. At most one live E2E per migration checkpoint under the original brief unless the user explicitly authorizes more. Earlier permission to continue the prior export goal does not itself establish an unlimited new experiment budget.

## Completion and next action

Stage 1 completed before activating Stage 2 tests. Evidence lives under `build/workout_programming_quality_20261022/`; this does not replace the retained acceptance artifacts.

- [x] Stage 1: shared facts with retained parity (3 sessions, 14 definition groups, 27 occurrences); focused identity test passed.
- [x] Stage 2: compact selection context integrated into existing menu/edit/repair requests; existing compiled correction mechanisms retained. Three focused request/projection/stale-binding tests pass. No new correction stage.
- [x] Stage 3 implementation: shared policy distinguishes inclusion/emphasis and setup/unilateral practicality; nine existing policy/timing checks pass. Four qualitative-boundary checks pass after updating obsolete fixture references. Live assessment differences remain an open acceptance item.
- [x] Stage 4: production multi-candidate comparison deferred. `verify_controls.py` reproduces the baseline and numeric-only controls; those controls are not independently reviewed feasible alternatives or evidence of better judgment.
- [x] Stage 5: existing history integration audited and retained; eight focused checks pass. See `workout_generator_programming_history_20261022.md` for collection limits; recovery-aware adaptation is not implemented without observations.
- [ ] Final live acceptance: new semantic comparison and current-generation review/export parity remain pending. Offline verification is recorded in `verification.json`: 25 distinct focused checks pass, six edited runtime/test files compile, retained numeric audit and extracted summary parity pass. No paid calls or new generation-stage rejection observations were produced.

Do not claim this plan delivered better training outcomes. Completion establishes better-supported generator decisions on measured cases; real tolerance, session duration and adaptation require observations.

## Fresh E2E checkpoint

User-authorized fresh E2E with delegated approvals: `build/workout_programming_quality_20261022/fresh_e2e_20261022T081404/e2e_outcome.json`. One Flash attempt used 29 calls and 989,976 tokens (logged estimate $0.325846); it paused before export on unchanged coverage failures wrapped as `carried_repair_contract_changed`. Runtime hashes matched throughout. Initial intake needed repeated extraction/source review. Both candidate-menu expansion replies only reordered existing occurrences despite a feasible menu search. No passing final review/export or semantic improvement is claimed. Request-section metrics omit the new selection-facts key from their fixed measurement allowlist, so their absence does not establish payload absence; no semantic improvement was demonstrated before the stop. No new paid attempt was started.

### Subsequent retained-run investigation

Evidence is under `build/workout_programming_quality_goal_20261022/`. Later user authorization permits Flash continuations and delegated decisions without a total-call ceiling. These are continuations of the same fresh intake, not independent fresh successes. No new export has passed acceptance.

Shared fixes verified against retained evidence include canonical search-library identity (catalog identity was incorrectly compared with authority-array identity), removal of forced candidate discovery for semantic edit permissions, unchanged-draft qualification receipt preservation, progression-method qualification ownership, and final-membership-based superset repair credit. Atomic edits now permit updating an occurrence before removing it and project order constraints onto surviving occurrences. Unknown references and duplicate removals still fail. The exact retained order failure compiles with zero provider calls in `checkpoint5/atomic_order_result.json`.

The live loop was stopped after the user requested design fixes before further retries. `live_resume10/result.json` records the stopped attempt, matched runtime hashes, retained source integrity and partial billing evidence for one cancelled request. Its latest materialized candidate remains unaccepted; volume and coverage errors must still be resolved. Later offline fixes are newer than that runtime snapshot.

Do not misattribute model output to the advertised schema: assessment-bound repair already omits `numWorkSets`; legacy proposals can contain count seeds, which compilation discards. New focused coverage verifies this existing behavior. Likewise, the apparent 6.2 MB review context is mostly the original equipment photo encoded at the API boundary, not duplicated repair plans.

The distribution objective has a separate proven ownership defect: its recipe-level squared-set cost rewards splitting an unchanged same-session dose across variants. A controlled production-solver case returned four sets in one occurrence at cost 16, versus the identical dose in three occurrences at cost 6. The source asks to distribute work across sessions. Correct that shared objective and replay retained inputs before another paid test; do not compensate with an exercise quota or reviewer prompt.

Qualitative judgment remains distinct from code feasibility. Fourteen horizontal push sets versus ten pull sets does not alone establish violation of a requirement that permits nonidentical counts and supplies no tolerance. Repeated low-set squat exposures without capacity evidence do not establish excessive personal axial fatigue. Use the existing delegated human gate for those judgments; do not invent a numerical threshold or claim personal suitability.

### App-owned progression clarification

The user clarified that double progression belongs to the app, not generator-authored policy. Current app source confirms that `DOUBLE_PROGRESSION` and `AUTO_REGULATION` invoke the native rep/load helper; the latter additionally collects per-set RIR. Generator materialization already supplies `AUTO_REGULATION` for `WEIGHT` and `BODY_WEIGHT`. The app model/import fallback itself is `OFF`, so retain the native mode and execution inputs rather than omitting them.

Removed the generator-only `progressionMethod` model field, its qualification requirement, method-to-route coercion, generated rep/load algorithm prose, and reviewer projection/repair ownership. Existing saved full drafts drop that legacy field on read without rewriting their conversations. Typed equipment-ceiling/variant routes remain separate; timed progression is not assumed to use the ordinary rep/load helper. Materialized-audit ownership now compares canonical legacy-free drafts so this removal does not silently detach a saved candidate from its receipt.

The corrected distribution objective has eight focused checks; production stage deadlines have two additional checks. A zero-provider bounded retained-source replay returned 23 occurrences/91 sets with no numerical errors, but did not prove an optimum and saved aggregate evidence only. The subsequent pre-drafting continuation `live_resume11` produced a numerically passing 24-occurrence/87-set candidate with four one-set occurrences; its review still contained a row-workload finding. That run was stopped for this ownership correction, and no export is verified. Recipe/session ownership cleanup passed six focused checks; reviewer ownership passed two; native-mode preservation and legacy audit-owner checks also passed. These are scoped results, not a full-suite claim.

### Verified fresh-origin acceptance

The same fresh-origin generation now has a verified export in `build/workout_programming_quality_goal_20261022/live_resume17/workouts/workout_plan_2026-10-22_124652.json` (SHA-256 `5391e27435ed4714c51182eddbdd9c04561c6d11c22c7b1c859b0379d9bc9166`). `live_resume17/verified_export.json` records exact independently reviewed artifact parity, schema-v2 definition links, execution-schema validation, unique runtime UUIDs, unchanged equipment, recomputed volume/duration, unchanged source conversation and current runtime hashes. Export itself used zero model calls and 0.97 seconds of pipeline time. This is a continuation of the original fresh intake, not an independent fresh success.

Final prescriptions total 87 working sets across 24 occurrences: 29/28/30 per session, estimated 65.6/74.15/71.5 minutes. Effective weekly sets: chest 16, back 18, quads 15, hamstrings 17.5, glutes 16, shoulders 21, biceps 15, triceps 18. All original approved numerical targets remain in force. Every exported rep/load exercise retains native `AUTO_REGULATION`; no separate generator double-progression algorithm is required.

Delegated decisions are retained in the conversations/controller records: accept the disclosed absence of separate exercise-specific preparation protocols for unsupported unweighted configurations; keep general warm-up and supported app-generated ramps. Correct the stale Session C focus label, reduce the lateral-raise starting target from 15 to 12 reps at the same 14 kg within the original 12–20 range, and apply coordinated exercise ordering without changing exercise selection or set allocation. Recovery tolerance, Nordic eccentric demand, limited dedicated lateral work and actual execution time remain uncertain/advisory; this acceptance does not establish training outcomes or personal suitability.

Two further shared ownership defects were fixed rather than retried. A new instruction on a failed audited draft previously exposed raw full-plan JSON Patch because no typed edit task was created; the existing identity-based edit route now covers failed as well as passing drafts, without importing stale review verdicts. One focused regression and compile passed; `checkpoint7/typed_order_replay.json` proves 14 move operations preserve every prescription and session label with zero provider calls. Final export previously rebuilt review authority from its narrowed emission library, renumbering the same front-squat UUID from `LIBRARY_153` to `LIBRARY_5`. The pipeline now preserves the original review equipment snapshot separately. `checkpoint8/alias_identity_reproduction.json` records the retained proof; eight focused export checks and compile pass, including continued rejection of unreviewed order, set and note changes.

Attempt logs, source hashes, usage and per-stage rejection records are retained under each `live_resume*` directory. The final independent review in `live_resume16` used two calls with no validation rejections; `live_resume17` performed only deterministic export. No broad-suite or Android-build claim is made, and no changes were committed.

### Subsequent programming-quality comparison

The user requested a goal and subagent implementation for the stronger design approach. See `workout_generator_quality_comparison_20261022.md` and `build/workout_programming_quality_comparison_20261022/`. The verified export remains the baseline, not proof that its programming is best.

Two shared defects are fixed: identity substitutions no longer inherit unrelated loads, and progression-headroom cost is invariant to equivalent weekly-dose segmentation. Scoped tests and compilation passed. Library/menu and reviewer-boundary audits retained genuine requirements, numerical credits, findings and uncertainty. Historical controller instructions were not silently stripped from saved user turns.

One compiled 84-set alternative passes numerical/execution checks; one bounded solver comparison returned a different optimal 81-set allocation. One Flash advisory comparison modestly favored the exact 84-set alternative over the baseline while identifying trade-offs. This is limited semantic evidence, not a production independent-review receipt, fresh generation, new export or demonstrated training outcome. Native progression remains app-owned. Personal tolerance and execution-time evidence remain unavailable.

### Deterministic intake redesign

The next fresh E2E stopped at requirements intake (27 calls, 1,124 seconds), so it did not evaluate the programming-quality changes downstream. The user approved a deterministic intake redesign with subagents. See `workout_generator_deterministic_intake_20261022.md` and `build/workout_deterministic_intake_20261022/` for ownership, implementation and scoped offline evidence. New intake uses typed sparse updates, explicit numerical relaxation permissions and verbatim qualitative source blocks; source-review concerns stop at a human gate instead of automatically reconstructing requirements or repairing reviewer finding syntax. The user explicitly selected a fresh rerun instead of historical receipt compatibility. Existing retained conversations/exports remain untouched. Fresh E2E acceptance is still pending; no paid call was made for this implementation checkpoint.

The subsequent user-authorized supervised fresh-origin E2E completed. Evidence: `build/workout_deterministic_intake_fresh_e2e_20261022T145332/fresh_e2e_outcome.json`. Its verified 83-set export meets unchanged targets and matches the independently reviewed artifact. The 40 Flash calls include continuations after a shared fix separating rejected redistribution proposals from validated conservation authority. This is supervised acceptance, not an unattended or training-outcome claim; see the deterministic-intake document for metrics and remaining advisories.
