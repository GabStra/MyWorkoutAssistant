# Shared policy and preference comparisons — 2026-10-28

The Oct 21 brief remains the operative simplification guide. This work follows the user's request to implement the shared policy fix. Existing uncommitted work is the baseline; no retained conversation, active requirement or exported workout is replaced.

## Evidence and scope

The duration-first retained replay intentionally changed `objectiveOrder`; it is not evidence that production silently reordered an approved policy. Current code already owns priority order in extracted requirements, records solver execution, reviews the final rendered artifact and supports explicitly permitted hypothetical requirement changes. Reuse those paths rather than introducing another policy object, version or orchestration layer.

Three concrete gaps motivate the changes:

1. `objectiveOrderUsed` described available priorities rather than stages actually attempted. A bounded solve could overstate which lower priorities ran.
2. `diagnose_conflict_and_propose` returned early for a feasible candidate, so its authorized-bound comparison path could not serve a requested preference comparison.
3. The alternative review callback did not attach its joint-solver receipt to the review snapshot. The normal reviewer consumes that receipt for optimization disclosure and priority facts.

## Shared behavior

- Requirements remain authoritative for hard bounds, full priority order and permission to explore specific numeric changes. Permission to explore never activates a changed value. The existing exact-proposal approval path remains authoritative.
- Solver receipts report actual attempted approved priorities and preserve optimal, feasible, unavailable and not-run distinctions. Reuse must not retain an internally contradictory execution claim.
- The existing alternative tool accepts either current source-backed advisory concern identities or names selected from the current approved priority order. Selecting a priority requests comparison; it does not assert that a nonzero score is a defect or that evidence is sufficient.
- Before comparison, the caller binds the exact current candidate to its requirements, library, history, decisions, completed review, final artifact, source coverage and finding ledger. It carries the current source working-set budget. Hypothetical repair candidates remain on their existing separate path.
- The unchanged baseline is neither solved nor reviewed again. Existing permitted numeric paths supply bounded comparison scenarios, with single-path scenarios preceding combinations. Every candidate still needs production audit and independent review under the full unchanged priority order and all unaffected requirements.
- Code reports differences in physical work sets, per-definition exposure, qualified movement coverage, effective muscle credits, duration and optimization evidence. These are comparison facts, not a universal fatigue score or an automatic declaration of superiority.
- Failed, unavailable or unauthorized comparisons retain the original candidate and its actual review status. They cannot manufacture a feasibility conflict or turn a failed semantic review into a pass.
- Hypothetical reviews receive the same solver receipt that owns their plan. Existing final-artifact review, accepted-tradeoff lifecycle, approval and export checks remain in place.

## Validation and completion

Use focused regressions for early solver stop/receipt reuse, exact baseline forwarding, priority selection without prose parsing, unauthorized changes, baseline preservation, comparative arithmetic and hypothetical review receipt forwarding. Compile edited Python files. Re-audit the retained capped/uncapped counterfactual artifacts with current code and record source hashes without rewriting historical inputs.

These checks establish shared-path behavior, not a new workout-quality result. A subsequent fresh E2E must use the approved demand-first order, record per-stage rejection data and verify exact reviewed-artifact/export parity. Assess the resulting exercise exposure, sequence, qualified development floors, duration spread and stated evidence gaps. A bounded solver result must retain its optimization limitations.

No physiological thresholds, exercise-specific branches, muscle-credit changes or automatic requirement relaxations are introduced. The retained source has empty `relaxationPermissions`; comparison under that source must stop without changing its glute ceiling. The capped/uncapped artifacts are controlled counterfactual evidence, not approved replacements.

## Implemented validation

- The combined focused checkpoint passed 15 tests covering the new selectors, caller integration, baseline comparison, receipt consistency, exact-artifact review and accepted-concern lifecycle. Subsequent caller-boundary refinements passed the integration regression and the existing ordinary conflict-routing regression (2 tests).
- `py_compile` passed for all five edited runtime modules and their edited/new test files. Scoped `git diff --check` passed; Git only reported its existing CRLF-normalization warning.
- `build/workout_shared_policy_20261028/validation.json` records provider-free current-code native audits of both retained counterfactuals, exact per-definition and audit differences, unchanged transcript bytes and source hashes. It reproduces Nordic sets 12 to 6, effective glute credits 18 to 27, and physical working sets 91 to 94. This comparison uses the explicitly hypothetical duration-first order on both sides, not the approved demand-first policy.
- Historical source hashes differ from this implementation in the five edited runtime modules, so the old solver results are not presented as current-code solves. The final caller routing guard was completed after the retained audit checkpoint and separately tested; `final_checks.json` records the final source hashes. No fresh model review, solver rerun, E2E or export was performed in this change.
