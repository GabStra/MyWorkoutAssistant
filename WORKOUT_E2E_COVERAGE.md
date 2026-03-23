# Workout E2E Coverage vs Business Logic

This document summarizes core workout business logic (from `shared/`) and how the current Wear OS E2E tests cover it, plus gaps that remain.

## Business Logic Areas (shared/)

- Workout state machine
  - `WorkoutState` includes Set, Rest, Completed states with `currentSetData`, `skipped`, `startTime`, and ordering.
  - State generation handles exercises, rests, and workout components.
- Set types and data models
  - Sets: `WeightSet`, `BodyWeightSet`, `TimedDurationSet`, `EnduranceSet`, `RestSet`.
  - Set data: `WeightSetData`, `BodyWeightSetData`, `TimedDurationSetData`, `EnduranceSetData`, `RestSetData` with volume/timer fields.
  - Sub-categories: `WorkSet`, `WarmupSet`, `RestPauseSet`, `BackOffSet`.
- History storage
  - `storeSetData()` persists `SetHistory` using `currentSetData` and `skipped`.
  - Rest sets are not stored; warmup sets are excluded from set history.
  - `WorkoutHistory` includes duration, heart beat records, and done state.
- Workout progression / metadata
  - `ExerciseSessionProgression`, `ExerciseInfo`, progression state (deload/retry/progress/failed).
- Warmup and intra-set logic
  - Optional warmup set generation, rest insertion, and unilateral/intra-set rest handling.
- Equipment / load logic
  - Equipment-specific available weights, plate change calculations, load jumps.
- Resume and record
  - `WorkoutRecord` persisted for resume and set index tracking.

## E2E Coverage (Wear OS)

### `WearWorkoutFlowE2ETest`

Covered:
- Rest timer skip flow and transition to next set.
- Workout completion screen visibility after finishing a workout.
- Calibration-required workout start flow.
- Restart-timer recovery flow after process death on rest screen.
- Timed-duration set process-death recovery with running timer continuity.

### `WearExerciseHistoryE2ETest`

Covered:
- Weight set: modify reps and weight, assert `SetHistory` stores updated values.
- Body weight set: modify reps and additional weight, assert history stored.
- Timed duration (manual start): start/stop early, assert stored timers.
- Endurance (manual start): start/stop early, assert stored timers.
- Skipped set flag stored as `skipped=true`.
- Comprehensive workout: completes all sets; verifies ordering, start/end times present, rest sets excluded, and volume calculations for weight/body-weight sets.
- Warmup sets excluded: verifies that warmup sets (with `SetSubCategory.WarmupSet`) are excluded from `SetHistory` storage.

## Gaps / Not Yet Covered by E2E

- Warmup set behavior
  - ~~Explicitly verifying warmup sets are excluded from `SetHistory` and do not affect progression.~~ (COVERED: `exerciseHistory_warmupSetsExcludedFromHistory`)
  - Sub-category handling for `RestPauseSet` and `BackOffSet` (WarmupSet exclusion is covered).
- Superset sequencing and history
  - Superset order, transitions, and `SetHistory` coverage for superset exercises.
- Unilateral / intra-set rest
  - Extra rest insertion and two-side execution for exercises with `intraSetRestInSeconds`.
- Progression logic
  - Deload/retry/progress state changes and `ExerciseSessionProgression` persistence.
  - `ExerciseInfo` updates (streak, counters) across sessions.
- Equipment-specific load handling
  - Plate change results and UI on the plates page.
  - Load jump defaults, max caps, and equipment-specific combos in actual stored set data.
- Timed sets with auto-stop
  - Auto-stop behavior and stored end timers for `TimedDurationSet` and `EnduranceSet` with `autoStop=true`.
- History fields beyond set data
  - `WorkoutHistory.duration`, `heartBeatRecords`, `hasBeenSentToHealth`, and `globalId` not asserted.
- Resume robustness
  - Resume after app process death and validation of stored `WorkoutRecord` fields (setIndex/exerciseId) beyond UI state.
- Skipped sets beyond weight
  - Skipped flag stored for body-weight/timed/endurance sets and its impact on stored data.

