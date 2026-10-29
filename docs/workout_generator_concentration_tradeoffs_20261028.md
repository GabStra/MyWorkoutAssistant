# Concentration and priority tradeoffs — 2026-10-28

The operative Oct 21 brief still applies. This change reuses the existing qualified recipe pool, joint solver, audit and alternative-comparison tool. It adds no physiological score, exercise-specific rule, set cap, contract version or automatic requirement relaxation.

## Verified starting point

The retained current-code native replay at `build/workout_solver_fix_20261028/current/` already optimized exercise selection, prescriptions and placement jointly over 3,211 recipes / 9,633 options. All eight stages were optimal, including the approved family-concentration preference. Its approved priority order was demand distribution, duration balance, source balance, exercise distribution, workload economy, then muscle distribution. The family-concentration score was 64 and physical weekly sets were 94. The later live continuation reviewed and exported the saved candidate without running that selection again.

The posterior-chain profile includes reviewed Nordic, squat, hip-thrust and Romanian-deadlift families. It assigned 14 Nordic sets, five squat-family sets and two hip-thrust sets. The solver measures weekly family exposure, not merely placement. It minimizes the sum of profile peaks, so a lower concentration in one profile can trade against a higher peak in another. The aggregate optimum alone does not establish that each profile, or Nordic exposure specifically, is individually minimal.

The continuous volume analysis proves a 12-Nordic lower bound only within its candidate-pool volume relaxation. It omits the full executable model and cannot establish the best complete workout. Removing the glute ceiling alone previously produced an extreme hip-thrust solution under a different counterfactual; that is evidence against silently removing the ceiling, not a recommended program.

## Shared ownership

Requirements own hard constraints and the approved preference order. The native solver already fixes each achieved objective before solving the next. Qualified alternatives remain selection variables inside the supplied worker recipe pool. Unknown exercise properties are not evidence of low demand or suitability.

The comparison caller previously supplied only the selected reviewed workout. That narrowed subsequent searches by discarding unselected worker recipes. A retained pool can be recovered only through its exact preparation, current authority, qualified contracts and matching materialized submission. Otherwise the comparison remains explicitly scoped to the selected menu.

Priority diagnostics use the same full executable solver: first the approved order, then hypothetical orders moving an explicitly selected priority ahead of earlier preferences. Each scenario reports the changed precedence, actual solver status and stages, native-audit differences, family-profile exposure and source scope. Hypothetical orders are diagnostic only: no semantic approval, proposal identifier or export authority is created. The current reviewed plan and all hard requirements remain active. Timeouts and incomplete searches are not proofs of impossibility.

Numeric requirement changes remain on the existing separately authorized alternative path. A diagnostic preference comparison does not grant permission to change a hard bound. Candidate-universe coverage describes the retained prepared/qualified recipe pool, not the entire library.

## Validation scope

Use focused provenance, order-scenario, budget, audit and caller-forwarding regressions plus compilation. A provider-free retained experiment separately tests whether reducing the selected Nordic-family exposure can tie the achieved aggregate concentration score while preserving earlier priorities and the complete hard model. That diagnostic target is not a production Nordic-specific rule or an approved policy change.

The native diagnostic at `build/workout_concentration_design_20261028/profile_counterfactual_v3/exercise_stage.json` proved a minimum of **14 Nordic sets** when the first three achieved priorities and aggregate family score 64 are retained. Thus the saved result is not demonstrated to be an arbitrary 14-versus-12 tie at those scores. This bound is conditional on the supplied executable pool and locks; it is not a physiological minimum or proof that changing a preference or requirement cannot improve the plan.

The full diagnostic subsequently completed with a clean native audit, 94 physical weekly sets, 15 effective hamstring sets (14 direct plus one indirect), and estimated sessions 4,811 / 4,798 / 5,051 seconds. Its later placement scores are conditional on the solver's documented weekly-dose locks and can differ between equal-score dose selections; they are not evidence of a unique or globally best workout. Solver-relevant sources and transcript bytes stayed unchanged. The complete receipt is `profile_counterfactual_v3/summary.json`.

The current production comparison boundary was also replayed with the retained native receipt (no new native optimization or provider calls). It recovered three variable worker sessions and zero fixed sessions: 39 prepared/qualified definitions, 38 worker recipe definitions, with the remaining definition explicitly excluded for unsupported native warm-up. The replay preserved transcript bytes, kept the reviewed baseline and hard requirements, and produced no approvable/exportable proposal. Its attempt budget deliberately left additional priority scenarios unexplored; the top-level search status correctly remains incomplete.

Final combined focused verification passed eight tests covering retained-pool provenance and coverage, order scenarios, timeout/budget handling, fallback scope, and caller forwarding. Edited Python modules and tests compile. No paid E2E or new export was run for this change.

`build/workout_concentration_design_20261028/validation.json` records final runtime source hashes and verification artifacts. The earlier interrupted and failed harness attempts are retained separately; neither supplies a feasibility claim.
