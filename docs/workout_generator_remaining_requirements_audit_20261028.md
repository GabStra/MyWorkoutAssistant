# Initial requirements update and remaining investigation

## Changes implemented

`workout_generator_initial_request.md` is the editable next-run source request. It copies the original retained input without rewriting it, replaces the inclusion-only calf/abdominal clause with nine direct working sets weekly for each, and records later approved constraints and app-owned progression. Three sets each per session is a preference, not a hard frequency requirement. Superset size/exercise-count limits, the duration preference, existing exclusions and the new Dumbbell Squat exclusion are included. No arbitrary Nordic cap or fatigue score was added.

`workout_generator_initial_requirements.json` updates the last prepared structured requirements: calves and abs become development roles with `minimumWeeklySets: 9`. Other hard requirements remain unchanged. Core retains inclusion status; it does not introduce another abdominal dose. The notes preserve the soft three-per-session preference and the known regional evidence limitation. This is a prepared user-specific input, not a global default or an approved new generation receipt.

Shared recipe qualification now derives calves and abs from the library's primary muscle tags. Secondary-only involvement or a model-added coverage label cannot qualify those roles through this path. Fresh, cached and independently reviewed recipe contracts all pass through the same canonical qualification function. No new prompt contract, version or solver objective was introduced.

## Remaining findings

| Finding | Evidence and interpretation | Next action |
|---|---|---|
| Known regional limitation | The app's `MuscleGroup` body map lacks separate lats, lateral delts and chest regions. The generator already supports regional labels and sourced anatomy separately, but coverage is incomplete. Combined back/shoulder totals cannot prove the original regional request. The user confirmed this is a known limitation. | Keep regional adequacy unverified. Completing reviewed annotations can improve the generator audit without requiring an app enum migration. Do not silently replace the original regional request with aggregate compliance. |
| Suitable quad exercise selection | The retained export assigns nine weekly sets to the now-excluded Dumbbell Squat configuration. Its current load-suitability replay fails. | Use the confirmed exclusion and current shared suitability guard in the next generation. Re-solve rather than append compensating work. |
| New calf/abdominal targets affect feasibility | The retained export has two weekly direct sets for each. Nine each is fourteen additional physical sets if the remainder is unchanged. | Include the floors during selection and solving. A new feasible 90-minute plan has not been established by this update. |
| Chest-accounting dependency | Retained export: Bench Press contributes six direct chest sets; Pullover contributes six direct sets; Overhead Press contributes three already-weighted indirect credits. Total fifteen. | Review exercise-specific muscle-role assignments and supporting evidence before treating the total as adequate development. This investigation establishes the arithmetic dependency, not that those credits are physiologically wrong. Do not change credits to obtain a preferred answer. |
| Nordic reliance | Retained export: twelve Nordic sets plus three RDL sets supplies fifteen hamstring credits. Glutes sit at the eighteen-set ceiling. | A controlled comparison is needed before asserting that this ceiling, exercise availability or another bound causes the concentration. Present source-authorized tradeoffs; no universal Nordic cap was approved. |
| Similar time is not similar demand | Estimated durations are 80.8/77.5/77.2 minutes. Those estimates pass the five-minute preference. Actual execution and recovery remain unverified. | Preserve the timing preference; do not claim equal difficulty or re-enable demand-distribution optimization without the evidence/authorization it requires. |
| Repetition and diversity | The retained plan repeats many recipes across the week. Family-diversity optimization compares reviewed classified pools; it does not establish global optimality or physiological benefit. | Reassess after removing unsuitable candidates and adding the new dose floors. No new variety quota is justified by this observation alone. |
| Superset count | Export has no supersets. The approved bounds are fifteen exercise occurrences per session and at most three per superset. A separate numerical superset-count limit is not recorded. | Do not invent another quota. Superset use remains a practical selection preference, not a mandatory count. |

## Validation and limits

`build/workout_initial_requirements_20261028/verification.json` records provider-free verification of the structured schema, preservation of other hard requirements, absence of hard three-session calf/abdominal frequency floors, rejection of the old export for both new minima, and a controlled nine-set audit boundary probe. The boundary probe is not a newly solved workout.

Focused qualification/coverage tests: thirteen passed, twelve deselected. Edited Python compiled; scoped whitespace checks passed. No paid intake extraction, solver feasibility comparison or fresh E2E was performed. The next live run must consume the new source prompt and structured inputs, rather than the archived original prompt or an old approval receipt.
