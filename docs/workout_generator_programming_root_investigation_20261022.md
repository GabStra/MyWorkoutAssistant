# Remaining programming issues: unpaid investigation

This is an investigation, not an implemented programming policy or an approved replacement workout. The operative fix brief and all existing requirements remain in force. Evidence and reproducible scripts are in `build/workout_programming_root_investigation_20261022/`.

## Findings

### A menu dependency is not a global impossibility

The retained menu requires at least 12 Nordic sets under its current credits and targets. But a different eligible exercise can change the coupling: Barbell Deadlift receives half a quad set as well as full hamstring/glute credit in this library. A controlled menu with 12 squat sets, six deadlift sets and nine Nordic sets reaches 15 quad, 15 hamstring and 18 glute sets with unchanged credits. This is an accounting counterexample, not evidence that the deadlift substitution is personally preferable.

The complete controlled candidate also has four lateral-raise sets, two shoulder-press sets and two pull-up sets; 74 total sets across 25 occurrences; estimated sessions 77.13/82.20/74.55 minutes. Production draft-schema, volume, coverage, execution-rule and execution-detail checks return no errors. Its muscle-distribution objective remains zero. No exercise-specific qualification, fresh independent semantic review, actual execution timing or personal suitability is established for the new recipe. It is not exported or adopted.

Therefore changing credits or relaxing requirements is not the first necessary remedy. The original library's credit assumptions still deserve scrutiny independently of whether this counterexample is useful.

### The numerical objectives do not represent overall programming quality

`joint_planning.py::solve_prescribed_week` minimizes absolute deviations from equal per-session muscle volume, then the progression penalty, then preservation. The saved approval explicitly retains `objectiveOrder = [distribution, progression]`; do not silently reinterpret it.

Consolidating the retained three RDL sets into one session, while preserving weekly totals and every session's posterior-chain coverage, passes the numerical/execution checks and saves approximately three estimated minutes and two exercise occurrences. But its distribution objective worsens from zero to 24, so the current primary objective disfavors it. This is a policy trade-off, not a solver arithmetic bug. A source request to distribute work for fatigue management does not itself prove that exact equal muscle credits are the best arrangement.

`recipe_contracts.py::progression_margin` assigns unknown setups a penalty derived from the number of selectable external loads. In the retained case an ordinary pull-up receives 50 and an incline row 25. Moving one row set to the pull-up preserves all weekly muscle totals and the distribution score, remains under the time cap, and increases the progression cost by exactly 25. The model is not making this preference: the code is. It measures equipment configurability, not demonstrated personal progression potential or overall programming quality. The app continues to own native progression.

### A larger candidate pool does not fix the objective

One bounded production solve with an additional deadlift recipe returns an optimal numerical result in approximately 19 seconds: nine Nordic sets and six deadlift sets, but only one lateral-raise set and one pull-up set. It still includes eight one-set occurrences. It flags changed order/placement for independent review.

This distinguishes two causes: the supplied menu limits what the solver can choose; the objective still determines which feasible emphasis it favors. A larger pool alone does not resolve both.

### Weighted pull-up is available and was discovered

`LIBRARY_20`, Weighted Vest Pull-Up, is eligible with the confirmed gear and 0–20 kg selectable additional load. It has the same audited muscle-credit vector as the ordinary pull-up. The original search returned it at conversation message 20, but it did not enter the selected recipe pool.

Both configurations have zero comparable recorded sessions in the supplied history. Without a declared or observed starting load, the weighted configuration's progression penalty is 26 rather than the ordinary version's 50. Thus it nearly removes the numerical penalty difference versus the row, but does not establish personal ability. Additional resistance cannot assist an unweighted repetition.

A second bounded production solve with both added recipes returns an optimal numerical candidate in approximately 11 seconds: one weighted pull-up set, one lateral-raise set, two shoulder-press sets, nine Nordic sets and six deadlift sets. Adding the weighted alternative changes the loading configuration but does not create meaningful emphasis automatically. Both research recipes still require qualification and independent review before adoption.

### Capability uncertainty is real missing input

The retained exact-movement evidence reports no comparable sessions for Nordic Curl, Pull-Up or Ab Wheel Rollout. `training_history.py::apply_native_load_calibration_policy` supports external-load selection; it does not establish achievable unassisted repetitions or whole-week recovery. `load_suitability_validator` addresses observed load/rep contradictions; missing history alone does not generate an incapacity finding. That distinction is appropriate. A material unresolved minimum-demand question needs existing user clarification or a supported alternative, not another invented score or a blanket ban on unfamiliar exercises.

## Approaches compared

1. **Add direct-set minima, movement quotas or numerical balance ratios.** Predictable, but invents requirements unless the user supplies them. It can reproduce the same accounting problem at finer granularity. Not the default fix.
2. **Expand the menu and ask a stronger reviewer to repair it.** The bounded solves show why menu expansion helps only partway. Review also correctly distinguishes optional improvement from a demonstrated violation. More review retries cannot correct an objective that keeps preferring the same result. Not sufficient alone.
3. **Correct ownership of the preferences and missing evidence.** Retain code-owned feasibility, credits, timing assumptions and exact artifact review. Make semantic selection compare a small number of complete feasible candidates using the actual source priorities. Stop treating external-load-step penalties as a cross-exercise dose-quality metric. Treat equal distribution as its disclosed numerical preference, subject to the source's practical priorities rather than proof of fatigue management. Resolve material minimum-demand uncertainty through existing history/clarification paths. Recommended direction; numerical objective interpretation changes need an explicit decision before implementation.

The simplest next implementation is to remove the unsupported progression-cost proxy from cross-exercise set allocation while retaining its underlying equipment/history facts, and use the existing selector to choose complete feasible menus. Do not replace it with a new universal fatigue or quality score. A bounded comparison must show whether this actually improves retained cases before a paid E2E. The distribution-versus-practicality preference and any requirement change must remain explicit.

## Verification boundary

All counterfactuals are saved separately. Production checks reproduce the baseline and eight controlled variants; assertions verify the identical-credit pull-up swap and its cost difference. Two bounded solver comparisons use current worktree code, with runtime differences from the retained run limited to the preceding selection-boundary fix's three files. Saved source conversation hashes are unchanged. No paid provider calls, production runtime edits, requirement approvals, new exports or commits were made for this investigation.
