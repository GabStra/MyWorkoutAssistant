# Prescribed workout plans

The prescribed-plan path compiles an existing PlanIndex or a workout source document directly. It does not create a planning conversation or mark an unreviewed plan as approved.

## Inputs and extraction

PlanIndex JSON is validated and compiled locally. It makes no source-extraction model call. JSON may contain the PlanIndex directly or under a top-level `planIndex` property.

Text (`.txt`, `.md`, `.text`) and text-based PDF (`.pdf`) sources are interpreted once per source/model identity, then resolved against the currently loaded exercise library. Exercise names are matched to catalog definitions after case and punctuation normalization; there is no fuzzy auto-selection and the tool does not add definitions. Unmatched names can be repaired with an explicit source-key to current definition-ID mapping in the cached `source_facts.json`. Supported quantities include integer `sets x reps[-range]`, exact `kg`/`lb` loads, and explicitly unit-marked rest such as `90s` or `2 min`. Reps-first instructions require group-round evidence; per-hand loads are accepted only for mapped dumbbell equipment. RPE and source citations are retained. Unsupported or ambiguous instructions and missing exact loads are reported for repair instead of guessed. The source extractor makes one source-only model call; repeated runs with the same source and model settings reuse the saved source facts. Scanned PDFs are unsupported; OCR is not performed. Superset/block evidence, rounds, rest lines, and source provenance remain attached to exercise placement notes.

The compiler needs an exercise library and equipment snapshot. Use `--exercise-library-file` for a schema-v2 WorkoutStore or exercise-library JSON; provide `--equipment-file` too when equipment is stored separately.

## Run JSON, text, or PDF

Use the same command shape for all three formats; the source extension selects the input path:

```powershell
python -m workout_generator_pkg.main `
  --prescribed-plan-file "C:\plans\plan-index.json" `
  --exercise-library-file "C:\plans\library.json" `
  --equipment-file "C:\plans\equipment.json" `
  --prescribed-state-dir "C:\plans\state\program-01" `
  --output-file "C:\plans\exports\program-01.json"
```

For prose or PDF, replace `plan-index.json` with the `.txt`, `.md`, `.text`, or `.pdf` source path. Text/PDF interpretation requires the configured model endpoint and API key. PlanIndex JSON does not.

On success the command prints the saved package path. A source-mapping or compile failure prints the diagnostic and, when available, the editable PlanIndex and compatibility report paths. The command exits without writing a successful package when compilation fails.

## Repair and resume

The state directory contains `source_facts.json`, `active_plan.json` when a structured plan is available, `compatibility.json`, `identity.json`, and `workflow_metrics.json`.

- If compatibility diagnostics point to an editable `active_plan.json`, correct the PlanIndex and rerun with the same source, library, and `--prescribed-state-dir`. The saved source facts are reused, and the compiler revalidates the edited plan.
- If an exercise name needs a catalog alias, edit `source_facts.json` under `extracted.definitionMappings`, mapping the opaque source key to the intended current definition UUID. Keep the original `rawName` and source evidence intact; the explicit mapping records the catalog choice without rewriting what the document said. Candidate definitions are included in diagnostics when a name does not resolve uniquely.
- If a library or history snapshot changes, the saved source facts can be remapped against the new snapshot. Mapping and deterministic compilation run again; source extraction is not repeated when its source and model identity still match.
- If the source file changes while using an explicit state directory, the run stops and preserves the previous editable plan. Use a new state directory for the changed source. With no explicit state directory, the default state path is namespaced by source hash.

## Measured workflow reports

`workflow_metrics.json` records the latest run and per-source cumulative metrics. Each immutable attempt receipt is stored in `attempts/<attemptId>.json`, with the attempt list in `attempts/index.json`. `latestRunWallSeconds` is the latest measured run; `cumulativeRunWallSecondsForSource` sums measured runs; `elapsedSinceFirstAttemptSecondsForSource` also includes idle time between attempts, such as repair time. Cumulative API calls and token totals are available as `cumulativeApiCallsForSource` and `cumulativeTokenTotalsForSource`; cumulative token totals remain unknown if any attempt has missing usage. Prescribed runs report `sourceInterpretation` and `deterministicCompile` stage wall times. A JSON source run has zero API calls; token totals of zero in that case mean no API requests occurred. Missing usage for a run that did make requests remains unknown.

The controlled replay artifact in `build/prescribed_benchmark/` compares the prescribed JSON route with the existing reviewed `execute_workout_generation` route. It replays an already confirmed recipe; a deterministic review stub prepares that recipe before timing, and the timed run makes no provider calls. The parity check covers exercise order, sets, reps, loads, rest, and notes. The reviewed route retains its existing `AUTO_REGULATION` progression and legacy history behavior; prescribed exports use `OFF` progression and set `shouldReapplyHistoryToSet` to `false` so app history cannot replace source-fixed loads. `reviewed_workflow_metrics.json` identifies the baseline as a reviewed workflow replay; the comparison CLI currently labels its generic second column `Open-ended`. This run does not measure the live open-ended planning conversation or establish a model latency or token saving.

To make a receipt from an existing open-ended conversation log, first provide its source/library/history/model/settings identity hashes and confirm whether the exact package was valid:

```powershell
python scripts/benchmark_workout_planning.py `
  --workflow-log "C:\runs\open-ended.log" `
  --identity-json "C:\runs\open-ended-identity.json" `
  --valid-package `
  --output "C:\runs\open-ended-metrics.json"
```

Then compare the two receipts:

```powershell
python scripts/benchmark_workout_planning.py `
  --workflow-reports "C:\plans\state\program-01\workflow_metrics.json" "C:\runs\open-ended-metrics.json"
```

The comparison marks results controlled only when all required identity hashes match and both callers marked their packages valid. It is descriptive evidence for those runs, not proof that one path caused a speed or token reduction. Conversation-log wall time includes user idle time through the saved-export marker; prescribed-run wall time measures one invocation. Compare elapsed times only when the measurement boundaries are comparable. The synthetic tests use an injected local extraction stub, make no model calls, and do not estimate live model latency or token savings.

## Ordered sessions and phases

PlanIndex supports an ordered list of named workouts with per-occurrence set, rep, load, rest, and notes. It has no calendar, week, or phase-scheduling metadata. Four phase-named workouts can preserve distinct prescriptions and their order, but an aggregate report over those entries is not automatically a single coach's training week.

## Recurring prescriptions

Recurring identity is opt-in and must be explicit in the supplied source instructions. The generator never infers a recurring session from repeated workout names, repeated prescriptions, or similar exercise names.

- A PlanIndex using recurring keys must include an explicit, stable `recurringProgramKey`, unique to that program and reused across regenerations. Every workout in one declared family uses the same `recurringSessionKey`; the generator derives IDs from the program, session and slot keys. Do not derive the program key from the plan name, filename or plan contents.
- Explicit order and display text, when present in the source, become `prescriptionOrdinal` (positive integer) and `prescriptionLabel`.
- An exercise slot inside that family may declare a `recurringExerciseKey`. The generator resolves `recurringExerciseId` from the session key and track key, never from the library definition, display name, or similar names.
- An exercise track must keep the same library definition, exercise type, and equipment across matching occurrences. Different slots of the same definition (for example A/B strength days) are distinct tracks. Conflicting references fail mapping.
- `loadHistoryPolicy` is `NONE` by default. `LAST_WORKING_LOAD` is emitted only when the source explicitly requests reusing the last working load for that recurring track. `PRESCRIBED_WEIGHT` marks an explicitly fixed recurring-week load override (such as a prescribed deload) and lets that exact weight take precedence over carried history and automatic progression. An initial load alone does not imply this policy. Reps, RPE and rest remain source-owned.
- Non-recurring workouts and exercises keep the existing generated package shape with no recurring fields. Prescribed exports continue to use `progressionMode: OFF` and `shouldReapplyHistoryToSet: false`.

Author input example for a text/PDF source:

```text
Workout A - Squat day
Back Squat 3 x 8 @RPE 7, 100 kg
REST 2 min

Workout B - Squat day
Back Squat 3 x 10 @RPE 8, 100 kg
REST 2 min
```

The source instructions must also state the recurrence explicitly. The cached `source_facts.json` then carries the matching keys, which remain editable:

```json
{
  "facts": {
    "planName": "Squat progression",
    "exercises": [
      {
        "sourceKey": "SRC_..._1",
        "rawName": "Back Squat",
        "evidenceKeys": ["SRC_..._1"],
        "recurringExerciseKey": "back-squat",
        "loadHistoryPolicy": "NONE"
      }
    ],
    "workouts": [
      {
        "name": "Workout A - Squat day",
        "recurringSessionKey": "squat-progression",
        "prescriptionOrdinal": 1,
        "prescriptionLabel": "Workout A",
        "blocks": [{"type": "straight", "exerciseKeys": ["SRC_..._1"], "restKey": "SRC_..._2"}]
      }
    ]
  }
}
```

Use the same `recurringSessionKey` on every workout in the family and the same `recurringExerciseKey` only for the matching slot. Use distinct track keys for A/B slots even when they reference the same library definition.
