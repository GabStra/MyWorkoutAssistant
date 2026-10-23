# Workout selection concern investigation — 2026-10-23

This records the retained-run evidence for the reviewer’s exercise-selection and duplicate Clean Pull findings. The operative implementation brief remains `docs/workout_generator_fix_brief_20261021.md`.

## Verified selection and duplication path

Evidence is the retained conversation `build/workout_joint_priority_solver_20261023/incumbent_handoff_e2e_20261023/workouts/conversation_sessions/2ce00164-8d7e-409c-a1d7-5fdf14589e70/messages.json` and its `terminal_receipt.json`. The run’s `validation_summary.json` reports `runtimeHashesMatch: true`; the original transcript and receipts were not changed.

- The model’s initial `prepare_workout_sessions` call (message 23) selected Barbell Clean in Session A and Barbell Clean Pull in Session C. It did not initially select two Clean Pull occurrences in Session C.
- `session_drafting._movement_pool` (currently `workout_generator_pkg/session_drafting.py:639`) unions definition IDs across proposed sessions and makes the pooled definitions available in each session. The failed preparation receipt (message 24) shows Clean and Clean Pull in the expanded per-session candidate lists.
- In its preparation repair (message 25), the model kept Session C’s Clean Pull at `/sessions/2/exercises/2` and replaced the Clean at `/sessions/2/exercises/10` with another Clean Pull. The compiled `recipeSessions` and subsequent worker result (messages 26 and 31) therefore already contain two distinct Clean Pull occurrences in Session C: one grouped and one standalone.
- The final `automaticAllocation.occurrenceLineage` maps those two Session C Clean Pulls to source positions `[2,2]` and `[2,10]`. The final audited prescription has three sets in the superset occurrence and two in the standalone occurrence. This artifact does not show the solver duplicating one source occurrence across two recipe variants; it shows two source occurrences created before the solver. The solver preserves their distinct identities.

The final artifact also contains Barbell Clean and Clean Pull in each session. This follows from the pooled candidate menu and the solver’s movement selection and placement. The approved source requires stable exercises that support high muscular effort and practical overload, and says to avoid unnecessary spinal loading and redundant exercises. It does not categorically ban either movement.

## What the current data can establish

The library entries describe Clean and Clean Pull as `HEAVY_COMPOUND` and assign broad primary/secondary muscle groups. Their candidate `programmingDemandFacts` are unknown for unsupported trunk demand, axial loading, and eccentric emphasis. `recipe_contracts.qualify_recipe_contracts` (`workout_generator_pkg/recipe_contracts.py:90`) qualifies approved coverage roles; it does not score hypertrophy suitability, technical skill, or stability. Those exercise properties therefore cannot be inferred deterministically from the current candidate facts.

The reviewer’s suitability concern is consistent with the source’s qualitative selection principles, while its physiological conclusion is not independently machine-verifiable from these library fields. This evidence does not justify exercise-name exclusions, a universal fatigue score, or a universal duplicate threshold. The exact duplicate in Session C is a concrete selection-review concern; the retained run does not establish that every repeated definition is always invalid.

## Run status and follow-up

The retained run stopped before export at `independent_findings_assessment`: the response used `advisory` for a material-uncertainty finding, which the active schema rejected. It made two provider calls (estimated $0.03721). This investigation made no provider calls and changed no runtime code. The plan has not passed semantic adjudication or exported.

### Root implementation updates

The latest audit has horizontal-push coverage of 3/4/8 working sets across A/B/C, versus four horizontal-pull sets across the week. Eight sets is within the approved 2-20 range. The source supports broad balance, but supplies no numeric ratio or per-session cap. Demand distribution remains unavailable because reviewed input properties are missing. Duration, muscle-distribution and source-balance solves returned feasible incumbents without proving optimality. This evidence supports investigation and semantic repair, not a new hard quota or a claim that the imbalance is unavoidable.

A separate shared defect is proven: the final receipt records muscle distribution as 321479, while the exact same final audit computes to 224 using the existing scaled session-deviation objective. Earlier objective stages can leave unused deviation/peak variables with arbitrary slack. Recording and locking those values did not preserve the selected plan's actual attained score.

`joint_planning._canonicalize_objective_epigraphs` now tightens the existing objective helpers to the values implied by the selected options before recording, locking, and passing the candidate to the next solve. It preserves physical choices and revalidates every existing constraint. Coverage-balance deviations, muscle deviations, duration maximum/minimum, demand peaks and redistribution peaks use the same bounded calculation. No priority order, muscle credit, target or set limit changes.

The retained-model check `build/workout_joint_priority_solver_20261023/semantic_owner_investigation_20261023/epigraph_canonicalization_result.json` validates the captured 7294-variable, 2358-row model. Only its 24 distribution auxiliaries changed: slack score 1103520 became exact score 336; source inputs and all constraints remained intact. This is the earlier captured model, not the latest final plan's 224 score. Fifteen scoped tests passed, including a solve-stage regression that inflates prior-stage slack and verifies exact incumbent handoff and final audit score. Edited solver/test files compile. No provider call or full new generation was made for this fix. Improved plan quality and optimality are not established by canonicalization alone.


## Provisional timing-uncertainty adjudication

The retained failure was not simply a schema/validator disagreement: both correctly rejected advisory disposition for a finding already marked blocking. The deeper ownership error was freezing discovery's provisional materiality before assessment. The existing review authority treats estimate uncertainty as advisory; discovery may still overstate that uncertainty as material.

The single-attempt assessment can now adjudicate only a fresh `NEW_*` material-uncertainty concern as advisory when its own evidence includes structured `programmingSummary.sessions.<n>.timingComponents`, the summary states `executionTimeVerified: false`, and the assessor explicitly cites both the code-owned review authority and matching current timing evidence through existing FACT references. Missing or unrelated references fail closed. The existing `uncertainty` / warning / advisory vocabulary is committed only after source-correction and withdrawal gates pass; cache findings and assessment hashes stay aligned. Carried `ISSUE_*` blockers and established violations are not eligible. No new disposition, contract version or retry path was added.

This is evidence-bounded semantic adjudication, not a mechanical proof that every timing-related concern is harmless. The assessor still judges the meaning of the cited evidence. Explicit source corrections remain actionable, and actual execution duration remains unverified. Selection/suitability repairs and a successful review/export continuation remain pending; this investigation has made zero provider calls.

Final scoped verification: 15 solver checks and 5 uncertainty-adjudication checks passed. The latter hydrates the exact retained review context and FACT map from the original log, preserving its actual finding citations. All three edited runtime files and both new test files compile; scoped diff checks pass. `semantic_owner_investigation_20261023/validation_summary.json` records the current runtime hashes and unchanged retained terminal receipt.


## Advisory source-evidence handoff after the live continuation

`semantic_owner_fix_e2e_20261023` made two calls and stopped before repair/export. Discovery returned three soft tradeoffs with current-plan citations only. Assessment accepted all three as advisory, but its ordinary advisory schema could not supply authority citations, while terminal acceptance required approved source authority plus current plan evidence. The timing exception and solver correction were not exercised in that continuation.

The existing `authorityEvidenceRefs` field is now available on the soft-tradeoff advisory branch. Its enumerated choices use the same `_soft_tradeoff_authority` predicate as final acceptance: user source messages, approved requirements, or active decisions with valid user-source provenance. Generic review policy alone is not source approval. The model can select the governing source while Python carries the existing current-plan evidence. Local assessment validation also applies the unchanged source-plus-current-evidence check, so evidence requirements cannot drift from the final gate. No prompt text, version, disposition or retry loop was added.

Twenty-two focused checks passed, including the retained three-tradeoff controlled replay, missing/incorrect authority and current evidence, strict assessment delivery, soft-tradeoff terminal acceptance, and carried hard blockers. Edited source/test files compile and scoped diff checks pass. `soft_tradeoff_evidence_fix_20261023/validation_summary.json` records hashes and results. Zero provider calls were made for this fix. The replay validates transport and acceptance consistency; it is not independent semantic approval or a production export.


## Evidence ownership and compiler correction — implementation and live check

Assessment now carries the finding's bound source/current evidence in Python. Soft tradeoffs with sufficient carried proof have no citation-output fields. Missing source authority uses bounded source keys; Python resolves provenance and still rejects policy-only, missing-current, unknown and duplicate selections. Narrow timing advisories similarly carry code-known policy/timing evidence after explicit adjudication, without model-authored FACT numbers.

Provider disposition eligibility and local validation now both use the canonical context. The reduced model evidence view cannot accidentally advertise a disposition that the complete context rejects. A fresh unverified timing finding is routed away from false absent-capability classification only when its cited session timing contains `supersetRoundSetup`, the corresponding actual session has an active superset of distinct known equipment/accessory resource sets, and both superset/timing repair dimensions exist. This does not choose advisory, waive source requirements, or affect carried blockers.

The ordinary repair compiler now canonicalizes explicit superset detachment. It computes straight-set recovery from the source group and existing approved rest rules, preserves explicit straight-set recovery, flattens singleton remnants, retains two-member remainders, and leaves redistribution-owned groups to their existing compiler. Transition rest is not mistaken for full straight-set recovery. Final ordering/contiguity remains the existing final audit's responsibility.

Eighteen evidence/disposition checks and three compiler checks passed; edited files compile and scoped diff checks pass. The exact retained numerical replay cleared all three groups with zero audit errors, unchanged weekly volume, and estimates 4806/4617/4897 seconds. Saved inputs were unchanged. Artifacts are under `evidence_ownership_validation_20261023`. Two tests in an earlier wider selection failed on expectations outside this change (removed progression dimension and old tool-description text); no pre-change baseline rerun was performed, so those are documented fixture failures rather than claimed verified baseline passes.

The authorized live continuation `evidence_ownership_e2e_20261023` used 10 calls in 266.51 seconds, approximately USD 0.110409 in logged token-price estimates (35 campaign calls total). Runtime hashes matched and the original conversation was unchanged. Discovery and assessment passed with zero rejections; the timing concern became a supported repair. The two repair submissions were rejected before materialization: replacement of a recipe protected by an assessed conservation/redistribution objective, then model-emitted code-owned set counts and further protected-recipe replacements. No candidate changed, no new solver stage ran, and no export was produced. The paid run exited at the bounded pause; it was not retried. This proves the previous evidence blocker cleared live, not that workout quality or end-to-end export is now reliable. The next owner issue is inconsistent repair intent: replacement/diversification versus preserving that same recipe, compounded by the remaining construction-based mixed-repair surface.
