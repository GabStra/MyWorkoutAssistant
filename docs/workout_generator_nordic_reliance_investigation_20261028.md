# Nordic reliance investigation — 2026-10-28

## Finding

The saved export's twelve Nordic sets are explained by the interaction between its hamstring floor, glute ceiling, and the muscle credits of its selected quad and hinge exercises. They are not evidence that Nordics are the only exercise capable of training or progressing hamstrings: the export also contains three Barbell Romanian Deadlift sets, and the training record has nine comparable Barbell RDL sessions with load headroom.

This arithmetic applies to the retained export only. That export predates the prepared nine-set calf and abdominal floors and still includes the now-excluded Dumbbell Squat. It is not evidence that a newly generated plan with current requirements is feasible or will have the same distribution.

## Proven accounting for the retained export

The exact export records 12 Weighted Vest Nordic Curl sets and three Barbell Romanian Deadlift sets. Its audit reports 15 effective hamstring sets and 18 glute sets. The quad total is 15 sets: four Barbell Back Squat, nine Dumbbell Squat, and two Barbell Hack Squat sets.

Under the audit's current library credit rules, each of those 15 squat sets contributes one quad and one glute credit. Each RDL set contributes one hamstring and one glute credit. Each Nordic set contributes one hamstring credit and no glute credit. The resulting equations for this exercise mix are:

```text
quad work = 15, contributing 15 glute credits
15 + RDL sets <= glute maximum 18, so RDL sets <= 3
Nordic sets + RDL sets >= hamstring minimum 15
therefore Nordic sets >= 12
```

The export sits exactly at that conditional lower bound: 12 Nordics + 3 RDLs. A set-count objective or a different lexicographic tie-break cannot beat this while preserving the same exercise credit profile and the 15/18 hamstring/glute bounds.

The relevant live rules are in [initial requirements](workout_generator_initial_requirements.json), [muscle credit accounting](../workout_generator_pkg/generation_audit.py#L750), and [joint planning dose locks](../workout_generator_pkg/joint_planning.py#L2505). The workout audit and exact export are retained under `build/workout_review_subject_fix_20261028/live_resume4/`.

## What the saved candidate pool supports

The prior provider-free, qualified worker menu included a Barbell Romanian Deadlift with `hip_dominant` and `posterior_chain` roles; it has nine comparable records and a current selectable ceiling of 111 kg versus an 81 kg latest recorded load. This is positive load-headroom evidence, not a promise of personal suitability.

The same saved recipe contracts included Weighted Vest Nordic Curl and Single-Leg Nordic Curl, both in the same reviewed Nordic family. Changing between those variants can change loading or execution, but it does not diversify away from the Nordic family. The exact Weighted Vest Nordic definition had no comparable history; a sibling standard Nordic definition has six different-setup sessions, including 18 kg × 6 on 2026-06-09, and is flagged for setup reassessment. History identity therefore remains relevant when choosing the variant.

Dumbbell Romanian Deadlift was also in the old menu, but the current history check marks it for reassessment: related Barbell RDL records reach 81 kg while the dumbbell-pair setup tops out at 50 kg. Do not count it as a load-suitable substitute without an explicit resolution. Barbell Hip Thrust has no hamstring muscle credit in the audit and cannot replace hamstring work by arithmetic.

The full equipment-available library contains other hamstring-tagged barbell and dumbbell movements. In the current muscle-credit map, those alternatives also credit glutes. Their presence in the library does not mean they are qualified in the saved worker menu, have suitable technique, or are approved for this plan. The saved menu is the evidence boundary for the controlled comparisons below.

## What the older controlled replays establish

The previous provider-free counterfactual in `build/workout_nordic_investigation_20261028/cap12_no_warmstart/` found a clean 12-Nordic + 3-Barbell-RDL plan with 15 hamstring sets, 18 glute sets and an 88-set workload optimum. It deliberately removed incumbent role-dose locks and imposed a diagnostic Nordic ceiling. This proves feasibility in that finite, older menu; it does not establish feasibility with the current nine-set calf/abdominal floors or the Dumbbell Squat exclusion.

That replay used an older runtime snapshot: fifteen files in its `source_hashes.json` differ from the current worktree. The later saved export's runtime manifest also differs in `recipe_contracts.py`, `session_drafting.py`, and `training_history.py`. I did not rerun either replay against an unverified reconstructed menu. A current controlled solve would require the fresh run's own qualified menu.

Other retained variants that relaxed the hamstring minimum or raised the glute maximum are hypotheses only. They were generated against older requirements and menus, and their outcomes varied with timeout and workload: they do not justify changing either approved bound. No requirement was changed here.

## Current limits and next decision

The fresh nine-set calf/abdominal floors add fourteen direct weekly sets relative to the retained export. Together with the Dumbbell Squat exclusion, they change the feasible menu and time budget. Until the new E2E produces a current qualified menu, the following remain unproven:

- whether the corrected quad selection still contributes 15 glute credits;
- whether an approved, qualified hamstring alternative can create room for more hip-hinge sets under the 18-set glute ceiling;
- whether the new direct calf and abdominal work fits the 90-minute session cap;
- whether any lower-Nordic plan can preserve every approved volume and movement requirement.

No generic Nordic cap is supported. The next reliable comparison should use the fresh run's qualified menu and exact current requirements. If the corrected quad menu still consumes 15 glute credits and its only evidenced non-Nordic hamstring option credits one glute per set, then 12 Nordic sets remain mathematically necessary under hamstrings ≥15 and glutes ≤18. A lower count would then require a qualified exercise with a different credit profile, or an explicitly approved change to a bound; it should not be obtained by silently weakening either requirement.

Demand-distribution optimization was not run or inferred. No exercise-familiarity, recovery, fatigue, or personal-suitability conclusion follows from these set-credit equations.
