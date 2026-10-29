# Workout quality design proposal — 2026-10-27

Status: implemented and under fresh E2E validation after the user requested applying this design. The original investigation used no paid calls. Implementation and validation artifacts are under `build/workout_quality_design_implementation_20261027/`. The Oct 21 fix brief remains operative; the existing solver, native audit, qualification, review, and export paths are reused.

The offline numerical probe found a native-audit-passing 82-set candidate with five Nordic sets and six horizontal-pull sets, versus 91/12/2 in the retained export. Its 75.7/78.9/78.9-minute estimates meet the 90-minute cap and five-minute spread preference. The probe used prior role assignments and seven explicitly unqualified recipe prototypes, so it demonstrates numerical feasibility, not fresh semantic acceptance. Family and distribution stages returned feasible incumbents at their time limits. The fresh run must qualify and prescribe its own pool and review its exact exported artifact.

The first implementation E2E stopped before a joint solve or export: one prescription worker hit its 16,384-token response limit. Its 44-definition pool also contained four unreviewed model proposals. The retained failure report is `build/workout_quality_design_implementation_20261027/failed_attempt_analysis.json`. Selection now exposes and validates the reviewed domain at preparation, cache reuse, restored drafting, and single-session preparation; an empty domain stops for evidence review. Worker output omits code-owned defaults and set indices while preserving explicit source prescriptions. These corrections require a new runtime snapshot and fresh E2E; the failed attempt is retained unchanged.

## Outcome to achieve

Generate an executable plan that meets the approved requirements and improves the identified movement/family distribution problems. A verified export alone is insufficient evidence of that improvement. The comparison must distinguish programmed quantities, estimated execution time, evidence-backed mechanical properties, and unknown personal tolerance.

The current program's binding development floors remain six qualified weekly working sets across at least two weekly sessions for lateral delts and vertical pulling. Those are approved programming inputs, not individual adequacy guarantees. The 90-minute session limit, two-set occurrence minimum, exercise/superset limits, aggregate volume bands, equipment restrictions, and other approved execution requirements remain intact. Similar durations means a soft 300-second spread tolerance. The app owns progression and load calibration.

## What the evidence establishes

The retained fresh run is `build/workout_quality_policy_20261027/fresh_e2e_v2`. Its 53 recorded runtime source hashes matched the worktree used for these experiments. Its actual export had 91 working sets, 12 Nordic sets, two horizontal-pull sets, eight lateral-delt sets, and eight vertical-pull sets. Estimated sessions were 68.5/68.3/72.4 minutes. Demand optimization was unavailable because classifications were incomplete.

All new counterfactuals were offline, with socket connections blocked and zero provider calls. They used the retained worker recipes and approved hard requirements; they did not rewrite the transcript or export.

| Check | Observed result | What it proves and limits |
|---|---|---|
| Omit the two development objectives from the requested order | Both objectives still execute | `_ordered_joint_objective_names` silently inserts them whenever a role has development intent. Explicit ordering and role intent have overlapping authority. This is not an experiment with those objectives truly disabled. |
| Explicitly place movement balance and family distribution before the two development objectives | Native audit passes; balance cost 17 → 4; lateral/vertical work 8/8 → 6/6; horizontal pulling 2 → 3; Nordic remains 12 | Priority order contributes to the result. Reordering alone does not fix the remaining menu limitation. The lower muscle-distribution stage timed out with a feasible incumbent. |
| Repeat that order with a redundant 900-set structural bound instead of the inherited 91-set cap | Balance cost stays 4 and Nordic stays 12; returned work rises to 115 sets and sessions to 85.2–88.5 minutes | The 91-set cap is not the cause of those residual values in this recipe pool. Removing it alone permits a much larger incumbent. This is not proof that 115 sets are necessary or optimal; the lower distribution stage was feasible rather than optimal. |
| Continuous weekly credit relaxation: current menu versus adding a credit profile present in the earlier retained export | Minimum pure-hamstring-profile contribution 12 → 3 under the same volume/necessary coverage constraints and 91-set cap | The current menu's credit geometry forces the reliance. The approved aggregate bands alone do not universally force it. This is a relaxation, not an executable or physiologically preferable replacement plan. |
| Add that alternative's actual retained executable recipe, keeping the 91-set cap and current hard requirements | Native audit passes; Nordic work 12 → 9; horizontal pulling remains 3; estimated sessions 68.6/70.2/72.0 minutes | The existing solver can exploit a broader recipe pool. The added definition has unknown family/demand metadata, so family optimization becomes unavailable. Prior role qualification is an explicit hypothesis, not a fresh receipt. This does not prove a full-policy quality improvement. |
| Independent shoulder-credit bound for zero movement-balance cost | At least 23 shoulder credits would be needed; the approved maximum is 21 | Under this menu's current qualified roles and credits, all four balanced push/pull roles must have at least six sets. Their minimum shoulder contribution is 15, plus six lateral-delt and two rear-delt credits. Exact equality is therefore impossible in this pool, even with no source-set cap. |

The last counterexample uses the library's existing Sumo Deadlift credit profile only as evidence that a materially different menu can change the bound. It does not justify prescribing that exercise, nine deadlift sets, an exercise-name branch, or treating reduced Nordic count as reduced fatigue.

Experiment artifacts:

- `build/workout_quality_design_20261027/priority_counterfactual.json`
- `build/workout_quality_design_20261027/priority_reordered_counterfactual.json`
- `build/workout_quality_design_20261027/priority_without_seed_cap_counterfactual.json`
- `build/workout_quality_design_20261027/menu_credit_counterfactual.json`
- `build/workout_quality_design_20261027/expanded_recipe_pool_counterfactual.json`
- `build/workout_quality_design_20261027/movement_balance_bound.json`

## Owning design problems

1. **A role's purpose also activates an unbounded quantity preference.** `requiredCoverage.intent=development` triggers max-min and combined-exposure objectives, including when the explicit order omits them. The hard development floors now establish minimum programmed exposure, but the old bonuses still compete for additional sets. See `joint_planning.py:_ordered_joint_objective_names` and the development objective construction. Minimum compliance, emphasis, and a preference to add more work need distinct meanings.

2. **The executable choice space comes from the initial shortlist.** `session_drafting.py:_movement_pool` unions the submitted definitions and makes their recipes available across sessions. The solver jointly chooses quantities, placement and retention inside that union. It cannot select a library alternative missing from it. `_development_menu_review` sees a wider catalog through a continuous relaxation, but that diagnostic does not provide complete executable alternatives. More count repairs cannot escape this boundary.

3. **Resource policy depends on an intermediate allocation.** `_source_working_set_budget_identity` derives a cap from submitted counts when no cap is supplied. The preparation path establishes and carries the first hard-feasible cap. This makes comparisons consistent within that run, but the original cap is not a user requirement and can differ with the initial menu. The controlled replay rules it out as the residual Nordic/balance cause here. Replacing it requires an explicit workload preference, not an unrestricted solve.

4. **The highest priority lacks the evidence needed to run.** `programming_demands.py:demand_distribution_inputs` correctly leaves a group unavailable when eligible executable candidates have unknown classifications. Expanding the pool without completing its evidence would worsen that problem. Missing data must remain unknown; accepting uncertainty permits a disclosed export but does not prove that priority was achieved.

5. **A valid candidate can still be an unfinished quality result.** Native compliance, optimization status, semantic suitability, and export status answer different questions. Existing `priorityExecution`, audit and review evidence should supply this distinction. A delegated acceptance of uncertainty or a tradeoff must not turn a quality failure into a claim of completion.

These are not all mathematical solver defects. The production solver proved a balance cost of four optimal within these recipes after satisfying the earlier duration preference. The separate 23-versus-21 bound explains why zero is impossible here. If a reviewed broader pool cannot remove a conflict, the remaining choice is an explicit programming tradeoff or requirement revision. Another model repair cannot change that arithmetic.

## Reassess policies as well as candidates

The user clarified that a change which could resolve currently unresolved outcomes should be proposed. Hard feasibility alone is not the trigger: a valid candidate may still miss its quality goals. Review the provenance and purpose of a binding limit, compare the same executable pool and approved objective order, and show resolved issues, remaining issues and regressions. Keep proposed changes explicit; evidence that a change helps does not silently approve it. Menu repair, code correction and policy revision remain distinct options.

The 21-set aggregate shoulder maximum originated in the explicitly approved October 21 alternative `ALT_688102642db2f2992fb97fd7`, which raised the original 18-set ceiling to accommodate that candidate. It is an approved programming choice, not an individually established physiological ceiling. The current proposal is to retain the 15-set minimum and compare an absent shoulder maximum, represented as `maximum: null`, against the existing maximum of 21. The existing workload-economy preference, occurrence bounds, duration limits and qualified movement floors remain unchanged. This comparison must report workload as well as movement balance; a better balance score alone does not establish a better prescription or personal tolerance.

The production alternative-diagnosis path currently explores requirement changes only after hard infeasibility. It does not yet automatically investigate quality-limiting policies in an otherwise valid plan. Do not describe the new debugging rule or the controlled comparison as implementation of that broader automatic behavior.

The latest repair failure has an independent proven cause. The retained message-38 candidate was infeasible while every source occurrence was pinned. A network-blocked replay with source selection unlocked is hard-feasible under the same 21-set shoulder ceiling in 8.52 seconds. Soft objectives were disabled in this control, so it establishes the selection-pin blocker, not a quality improvement. Evidence: `build/workout_quality_design_implementation_20261027/fresh_e2e_v3/controlled_replays/m38_unlocked_hard_feasibility.json`. An approved exercise-selection repair now unlocks source retention only when the definition-occurrence multiset changes; prescription, ordering and redistribution repairs remain pinned.

The same-pool shoulder comparison used corrected lateral-delt eligibility, the same 39 retained executable definitions and unchanged remaining requirements. With a maximum of 21, known unsupported-trunk peak was 16, Nordic sets 6, horizontal pulling 6, shoulder credits 20.5 and physical sets 84. With no shoulder maximum, those values were 15, 5, 10, 26.5 and 85. Both passed the native audit and the five-minute duration-spread preference. Removing the maximum improved the first-ranked demand objective while worsening the later movement-balance cost (5→7) and family-distribution cost (38→45). Those later optima are conditional on their different preceding demand optima; neither is a universal plan-quality score. Session-muscle distribution retained time-limited feasible incumbents in both cases. Evidence: `build/workout_quality_design_implementation_20261027/shoulder_policy_comparison/comparison.json`. The delegated controller adopted the minimum-only shoulder target for fresh attempt v4, with these tradeoffs explicitly disclosed and all other numeric constraints unchanged.

Fresh attempt v4 stopped before solving because one prescription worker supplied ten valid catalog entries while two others each supplied all 39 executable definitions. The per-worker exact-menu check incorrectly required the full catalog three times, although `solve_prescribed_week(... preserve_source_selection=False)` consumes their combined recipe inventory and places it across sessions. Validation now binds each worker's returned subset to code-owned source occurrences, rejects unknown/excess references, and checks maximum occurrence multiplicity once over the combined pool before solving. Source presets are restored by identity; prescriptions remain validated. An incomplete combined pool stops with structured missing-reference counts. The actual retained case passed a network-blocked, zero-provider admission replay; the solver was stubbed in that replay, so it does not establish executable feasibility. The retained run was then resumed under a new source snapshot without redrafting completed workers. Evidence: `build/workout_quality_design_implementation_20261027/fresh_e2e_v4/recipe_pool_replay.json`.

Fresh intake corrections also exposed a testing distinction: this harness starts from the original request plus policy prose, so it re-extracts requirements. The ordinary saved-conversation path already carries a structured requirements base with sparse typed updates. Reusing that approved base for a fresh *plan* would avoid repeated prose extraction, but would test a different intake path; source binding and renewed confirmation must remain explicit. Array-valued updates currently replace whole arrays, so omissions during a correction remain an identified design risk. Do not describe fresh-intake supervision as unaided reliability.

The resumed v4 run completed a verified exact export using 26 Flash calls in total. It has 83 physical sets, five Nordic sets, twelve horizontal-pull sets, and six qualified sets each for lateral delts and vertical pulling across two sessions. Estimates are 82.5/80.9/78.5 minutes. Aggregate shoulders rose to 28.5 credits under the disclosed minimum-only policy. Independent recursive inventory includes the four Ring Pull-Up sets nested in B's superset and the two standalone sets in C. Exact artifact/guidance/audit parity passed, source snapshots matched, and the original retained messages were unchanged. The later distribution solve, missing demand classifications, review advisories and personal suitability remain limitations, not completed quality goals. Detailed outcome and semantic adjudication: `build/workout_quality_design_implementation_20261027/fresh_e2e_v4/result_review.md` and `completed_run.json` in that folder.

## Architectural alternatives

| Approach | Benefit | Limitation | Decision |
|---|---|---|---|
| Add exercise caps or further quotas to the current shortlist | Small local changes; directly excludes individual bad outputs | Can turn an avoidable menu choice into apparent infeasibility; each symptom needs another number; unsupported fatigue thresholds remain unsupported | Use binding numbers only for an approved need, not as the primary repair |
| Select a fixed, curated routine/template | Predictable, easy to inspect, little search | Generality shrinks sharply for different equipment, goals and constraints; adaptations reintroduce search | Useful reference baseline if the product is deliberately narrowed |
| Reconsider one menu addition at a time | Reuses current diagnostics and repair path | Local checks can miss improvements requiring several simultaneous substitutions; creates another search/review loop | Diagnostic aid, not the strongest completion design |
| Supply the existing joint solver with a broader, bounded, qualified recipe pool and one explicit policy | Compares exercise selection, dosage and placement under the same real constraints; escapes the initial shortlist without model-authored arithmetic | Requires reviewed evidence and executable recipes for that pool; search size must be measured | Recommended |

The recommendation is an input/policy correction to the current solver, not a new solver or orchestration framework. A full-library optimum, physiological optimum, and guaranteed optimality under a time limit are outside its claim.

## Recommended design

### One explicit policy

Keep the existing requirements object as the numerical authority. An explicit `objectiveOrder` is authoritative: omitted goals do not reappear because of role intent. Role intent describes the requested purpose; `minimumWeeklySets`/`minimumSessions` define the approved floor. Additional exposure is optimized only when that preference is explicitly selected.

For this program, propose removing the two automatic extra-development bonuses now that binding floors exist. Preserve verified demand distribution first and similar durations next; then movement relationships, family distribution, workload economy, and session muscle distribution. This is a proposed policy adjustment, not an already approved change to the retained run. The six-set floors remain mandatory regardless of objective order.

Movement balance continues to use the approved explicit relationships. It does not establish a universal ratio, adequate horizontal-row dose, or a physiological verdict. If the user wants a binding additional development floor, that is a separate programming decision. Do not infer one from the disappointing two-set result.

### One qualified executable choice pool

Build the automatic pool from equipment/restriction eligibility, approved user selections, and reviewed candidates spanning materially different relevant profiles. The first LLM shortlist may rank or propose options; it must not silently define the entire feasible universe. Review movement/family/demand evidence and use the existing suitability decisions before admitting alternatives for automatic selection.

Retain distinct profiles when they differ in qualified roles, family, credits, demands, executable load/rep options, setup, or timing. Muscle-credit equality alone does not make exercises interchangeable. Avoid arbitrary top-k pruning that removes the only alternative needed for a joint substitution. Any deliberate pool restriction is disclosed as the optimization scope.

Complete the required evidence for the bounded automatic pool, rather than annotating the whole library as a prerequisite. An unclassified user-requested candidate requires the existing uncertainty decision; it is never a free zero-demand or new-family option. Family identity and sourced mechanical properties do not establish personal capacity or equal fatigue. Review the definitions of the mechanical properties before filling metadata: a sourced tag is still only the stated property.

Reuse current recipe qualification and executable prescription validation. The weekly relaxation may filter impossible options or expose a menu conflict; it must not select the winning workout before integer placement, execution and native timing checks. Do not ask the model to construct precise prescriptions for the whole catalog. Establish how the bounded pool obtains reusable recipes using existing worker/building paths before widening it, and measure the resulting option count.

Use one common pool/evidence context when comparing candidates. Family-profile grouping and available demand groups must have the same meaning on both sides; a smaller score after disabling a group is not an improvement. Reuse the existing audited-candidate comparison context for this boundary.

### Explicit workload selection, followed by dose-preserving placement

User-owned workload bounds remain hard. A generated allocation is a seed or reference, not a new hard user limit. For fresh generation, use the real duration, volume, occurrence and structure constraints for feasibility.

After the explicit selection priorities, minimize physical weekly working sets as an agreed preference before lower-priority session muscle equalization. Count physical sets once, including superset members and session frequency. This keeps workload economy visible and comparable across menus instead of inheriting an arbitrary initial cap. Its position is part of the policy: placing it before all quality preferences could favor broad-credit exercises or sacrifice desired balance.

Then reuse `_lock_weekly_recipe_doses` before distribution polishing, extending its current use for role-concentration polishing. Placement can change while weekly recipe doses remain fixed. A later placement stage cannot improve its score by adding calf, core, or other sets. If changing the weekly dose is necessary, return to the explicit dosage decision; do not hide that change inside distribution repair.

Demand objectives remain counts of verified properties. They are not fatigue scores or personal tolerance thresholds. Continue testing that moving the same known workload can improve concentration and that merely renaming variants or adding unrelated sets cannot manufacture an improvement. Do not rewrite the demand metric without a controlled counterexample demonstrating the need.

### One final artifact and honest completion

Audit, render, review and export the same selected plan through the existing path. The reviewer handles residual suitability, practical execution and genuine qualitative gaps using code-computed facts; it does not reconstruct counts, locations or source references.

Use existing concern identity/lifecycle and typed correction choices. Numerical defects return to their code owner; no extra prompt contract, contract version, invalidation rule or independent repair pipeline is needed for this work.

Report hard compliance, active/evidence-missing objectives, achieved values, timeout/gap status, and accepted tradeoffs separately. A clean human gate or disclosed export is a valid workflow outcome. It does not mark the original quality goal achieved if the target issues remain.

## Implementation reach

| Owner | Required reach |
|---|---|
| `joint_planning.py` | Authoritative goal ordering, explicit workload preference, shared candidate evaluation/comparison, dose-preserving polish, existing proof/priority reporting |
| `allocation.py` | Preparation remains a nonbinding seed; shared audited-candidate comparison uses the same policy, evidence and explicit resource bounds |
| `session_drafting.py` | Pool construction, recipe acquisition, preparation seed semantics, menu diagnostics and carried context |
| `recipe_contracts.py`, `programming_demands.py`, annotation data | Reuse evidence and qualification; complete the chosen bounded pool without guessing missing facts |
| `planning_tools.py`, `planner_context.py`, `programming_guidelines.py`, requirement accounting | Approved policy display/interpretation; no stale instruction that development automatically means maximizing exposure |
| `generation_audit.py`, `plan_review.py` | Same quantities/evidence; final-artifact review and accurate quality/completion disclosure |
| `interactive_shell.py`, `alternative_repair.py`, `repair_execution.py` callers | Verify they consume the same pool/policy/workload semantics; change only the affected shared calls, not their orchestration |
| Existing focused tests and retained harness | Update assertions that intentionally encoded implicit development goals or seed-derived caps; preserve user bounds, fixed workouts, superset/frequency accounting, repair obligations and exact export parity |

No app progression work, aggregate-credit changes, exercise-name rules, new dependency, contract-version layer, or transcript migration is proposed.

## Acceptance before calling this solved

1. **Policy invariants:** a development label cannot insert an omitted goal; explicit order is preserved; the six-set/two-session floors remain hard. Vary nonbinding seed counts and proposal order while keeping the same executable pool: the authorized problem and attainable objective values remain the same. Stable tie resolution may select among genuinely tied plans.
2. **Search boundary:** a controlled case requires two alternative profiles together; the broader joint pool finds it without iterative model menu repairs. An outside credit-only witness never counts as qualified or native-audit feasible. Under a common complete evidence context, adding admissible choices cannot worsen a proven earlier objective; timeout incumbents and changed comparison scopes are reported separately.
3. **Evidence:** missing demand/family metadata cannot make a candidate cheaper or more diverse, and cannot be described as a completed top-priority optimization. Classify the bounded pool sufficiently to exercise the approved demand objective in the acceptance run.
4. **Workload:** no first-seed-derived hard cap for fresh generation; a real user cap is preserved; placement polish preserves weekly doses exactly. Include the retained 115-set counterexample so a superficially better distribution score cannot silently become a larger-dose plan.
5. **Retained quality comparison:** solve the current saved case with the broader executable pool. Preserve all binding requirements and the duration preference when feasible at its declared rank. Demonstrate reduced single-family reliance and improved movement exposure against the 12-Nordic/two-row baseline. These are case-level regression expectations, not new universal quotas. If both cannot improve at the approved rank, provide a proven conflict or an explicitly scoped unproven result; do not call the original quality goal complete.
6. **Controlled semantic cases:** genuine bad variants are caught; corrected ordering, repeated exercises and nonidentical push/pull totals do not become invented violations. Unknown capability remains uncertainty.
7. **Search cost:** benchmark the expanded pool offline using existing compressed options, per-stage diagnostics and retained inputs. Preserve a feasible incumbent on timeout and disclose the proof scope. Do not solve repeated identical domains or turn a timeout into infeasibility.
8. **Fresh workflow:** after focused regressions and edited-file compilation, run one fresh production E2E with exact-artifact review/export checks and stage telemetry. There must be no controller-authored exercises, counts, order or runtime code fixes to rescue it. Intended approval/uncertainty gates remain legitimate. One success demonstrates that path, not a universal unaided success rate.

## Decisions adopted for implementation

The user's instruction to apply the design adopts the explicit hierarchy: verified demand distribution, duration balance, movement relationships, family distribution, workload economy, then dose-preserving session distribution. No extra-development bonus is requested; the six-set/two-session floors remain hard. The automatic pool contains every eligible definition with reviewed family identity and known sourced trunk-support classification; the current snapshot has 40 such definitions. Explicit selected candidates are retained, with evidence gaps disclosed. A valid disclosed export remains distinct from achievement of this quality goal.

Implement in this order once the design is accepted: make explicit policy authoritative and remove the current program's implicit extra-dose preference; complete/review the bounded pool and acquire executable recipes; feed the pool through the existing joint solve and common comparison context; replace seed-cap authority with the agreed workload preference and dose-preserving polish; update completion reporting and run the focused retained checks. Pay for a fresh E2E only after those checks demonstrate the intended quality improvement or expose a concrete decision that must be settled first.

The current evidence supports this architecture. It does not yet prove that an expanded, fully qualified executable plan can improve every desired quality simultaneously. That is the next offline acceptance experiment, followed by the fresh E2E after implementation is approved.
