# Programming-quality Stage 5: existing history evidence and limits

Status: existing exercise-level evidence is reusable; recovery-aware and session-duration adaptation remain unsupported by available records.

## What the current path observes

`TrainingHistory` indexes only completed workout sessions (`WorkoutHistoryStore.completed_sessions()` requires `isDone is True`). For each matched exercise occurrence, it records performed working-set facts such as actual reps and load, set order/execution sequence, equipment and accessory snapshots when present, and session date/end reason. Warm-up, calibration, skipped, inactive and explicitly unexecuted sets are excluded from ordinary performance evidence.

Effort fields are retained only when recorded. `autoRegulationRIR` and `rpe` are observations; `calibrationRIR` remains separately identified and must not be read as working-set effort. Missing effort remains unknown. Existing evidence keeps actual timer duration for timed sets and recorded elapsed duration, distance and available pace/heart-rate values for running results. These are exercise-level measurements, not measured total workout duration.

Exact comparison is bounded by exercise identity and current setup. Equipment, accessory and bodyweight-accounting differences remain visible under `otherSetupSessions` with comparison limitations; semantically related movements remain separate, explicitly non-equivalent evidence. The existing planner and reviewer projections retain the factual records they consume. These protections support reuse of comparable history without converting related loads or inferring current capacity.

## What the records do not establish

- There is no recovery/readiness/soreness check-in or equivalent subjective signal in this history contract. Exercise performance, `endReason`, or a missing session cannot substitute for one.
- `isDone` filtering omits unfinished workout sessions from this evidence path. An unfinished session therefore cannot be used here to claim which exercise caused a stop or which prescribed work was missed.
- The retrieved performance rows report completed sets, but do not provide a matched prescribed-versus-performed dose comparison for each historical exercise. A set count alone would not explain why planned work is absent.
- Timed-set and running durations are measured at the exercise level. The history contract has no measured start-to-finish workout duration. A per-set start timestamp without a matching end timestamp cannot produce one.
- Recency is represented by session date and `daysSinceLatestSession`; compaction drops time-of-day and per-set start timestamps. No current selection consumer uses those dropped values, and retaining them alone would not add a measured recovery interval or session duration.

## Existing regression evidence

`tests/test_workout_generator_training_history.py` already exercises the relevant boundaries: actual records exclude warmups/skips/calibration; recorded effort fields remain distinct; count-up/countdown durations follow app semantics; running results are measured once with routes omitted; changed setups stay non-comparable; related history stays separate from exact history; and history facts survive planner/reviewer compaction. Existing tests also cover native load calibration when usable comparable history is absent.

No additional storage, UI, inferred capacity, or recovery guidance was added for this stage. A future recovery-aware adjustment needs an actual user-sourced recovery observation and a defined event/identity that connects it to the relevant session or prescription. A true session-duration comparison needs a source-recorded session duration or paired start/end measurements. Any follow-up should add those at the owning history producer, then pass them through the existing compact evidence path and compare only records with adequate exercise/setup identity.

Until those facts exist, Stage 5 can support provisional load and rep decisions from comparable completed performances and report missing evidence as unknown. It cannot responsibly personalize volume from recovery, explain incomplete-session adherence, or tune estimated session duration from actual total workout time.
