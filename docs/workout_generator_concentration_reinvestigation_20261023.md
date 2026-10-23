# Concentration re-investigation — 2026-10-23

Read-only investigation of the real REVISION_5 failure. No production changes, model calls, or new exercise classifications were made. Artifacts live under `build/workout_joint_priority_solver_20261023/reinvestigation_20261023/`. Its `source_hashes.json` matches all 51 generator files used by the preceding verified replay. Retained conversations and library backup remain unchanged.

## Main result

The hard numerical targets do not force the RDL to remain in Full Body B. Moving its complete two-set prescription from B to A, without editing any prescription field, passes the production numerical audit: A/B/C estimates are 88.40/67.08/83.08 minutes, all weekly muscle totals remain unchanged, and required coverage is preserved. This is a feasibility proof, not evidence of better recovery, suitability, order or semantic approval.

The muscle-distribution objective gives that exact moved layout a cost of 64 versus 16 for the original layout. A preserved-placement solve can retain the move and recover distribution cost 16 through other allowed prescription changes. Thus the owning question is which feasible programming tradeoff should win, not whether the only available outcome is B's existing layout. See `exact_move_audit.json`, `preserved_placement_checks.json` and `placement_causality.json`.

The complete three-set Bent-Over Row move to A does not pass unchanged: A exceeds its limit by 80 seconds. Reallocation can produce feasible variants, which must be compared as different prescriptions rather than described as the same exact move.

## Problems in the previous diagnosis

1. **Metadata is necessary for the new physical-property objective, but is not the whole solution.** Its current gate covers participating definitions, not the whole catalog. The latest plan uses 19 unique definitions. All 311 library definitions lack annotations, but annotating all 311 is not required to compare a bounded menu. Missing facts on fixed or unexecutable candidates also currently affect availability, so the gate is broader than the qualified variable domain.

2. **The new objective has a narrower meaning than general demand interaction.** It minimizes a sum of separate per-property session peaks. It can distribute multiple exercises sharing one property, but can tie schedules that combine different properties differently. For example, property vectors A=[2,2,0,0], B=[2,2,0,0] and A=[2,2,0,0], B=[0,0,2,2] both score four, while their raw combined peaks are four and two. This is an objective counterexample, not a physiological score or approved interaction rule. Filling metadata cannot alone resolve that distinction.

3. **The reviewer has not established that B's arrangement is excessive.** The source requests avoiding excessive axial loading and repeated heavy hinges, but supplies no threshold that makes this particular co-placement a demonstrated violation. This deserves programming assessment; the presence of a source goal alone does not prove the current plan violates it. Broad category counts also do not establish such a violation: heavy-compound sets are A/B/C=18/12/14, and heavy-plus-moderate compound sets are 23/19/23. These counts are descriptive, not interchangeable fatigue measurements.

4. **Review carries and multiplies overlapping concerns.** The saved continuation's findings grow from seven to ten, of which nine require repair, while all executable `repairObjectives` remain empty. `_review_complete_draft` combines new findings, a synthesized whole-source correction finding and open carried findings. Single-attempt assessment then assigns a singleton group per finding. This retains claims about the same few issues as separate obligations; changing an allowed field does not establish the intended semantic improvement. See `review_and_objective_evidence.json`.

5. **The recent placement-unlock change does not demonstrate a fix to this live path.** That change is in `alternative_repair.execute_repair`. The final live calls used ordinary `audit_workout_plan`; its REVISION_5 receipt had `preserveSourceSelection=true`. A direct free solve can also undo a proposed placement in pursuit of its numerical objectives, so an explicitly selected repair outcome must survive compilation and optimization. Simply unlocking more placement is insufficient.

6. **A separate target-boundary issue merits a focused regression before changing code.** Existing typed redistribution constraints and their validator count matching recipes inside destination indexes, without explicitly forbidding an extra matching recipe outside them. The target-excluding-B experiment did not demonstrate that violation, and REVISION_5 has no such repair contract. This is a source-code concern, not the proven cause of this saved failure.

## Approaches and recommendation

| Approach | What it establishes | Limitation |
| --- | --- | --- |
| Populate reviewed properties and keep the current objective | Deterministic distribution of those individual properties | Does not define cross-property interactions or establish excessive fatigue; editorial work remains necessary |
| Add universal fatigue weights or compound quotas | A mechanically decidable ranking | Introduces unsupported policy; not justified by this source or experiment |
| Compare bounded feasible alternatives under a shared, explicit programming preference | Hard feasibility is computed first; selected changes can be compiled and preserved; evidence and tradeoffs remain visible | Qualitative suitability still needs bounded judgment or an approved operational rule |

Prefer the third path before broad metadata work. Reuse the existing solver, menu-selection compiler and exact final-artifact review:

- Separate hard approved constraints from soft programming preferences and missing evidence.
- Produce a small set of feasible placement/menu alternatives with the changed prescriptions and tradeoffs stated exactly.
- Let an explicit approved comparison, or the selector's bounded semantic judgment, choose among them. Do not present the numerical optimum as a physiological optimum.
- Preserve the chosen repair's actual placement/outcome through optimization, rather than merely checking that some allowed field changed.
- Review the exact final artifact and account for prior concerns once. A preference or unmeasured tolerance concern must not acquire an invented hard threshold through repetition.

Reviewed property data can support these comparisons. It should be scoped to the executable candidate domain and should retain unknowns; it must not be used to manufacture physiological certainty. Fully deterministic physiological suitability is not established by the current inputs.
