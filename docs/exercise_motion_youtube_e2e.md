# Exercise motion YouTube E2E

Use this workflow when you want to provide an exercise name, find a suitable YouTube source video, detect the usable movement segment, bake the motion, and generate the preview/Wear skeleton artifacts.

## Command

```powershell
pwsh ./scripts/run_exercise_motion_youtube_bake_and_rank.ps1 `
  -ExerciseName "cat cow" `
  -WorkspaceRoot "build/exercise_motion" `
  -ResultsPerQuery 8 `
  -MaxCandidates 5 `
  -VisionCandidatesPerExercise 5 `
  -VisionDownloadWorkers 3 `
  -VisionLlmWorkers 3
```

Replace `"cat cow"` with the exercise name.

To let DeepSeek suggest additional YouTube search queries before the normal `yt-dlp`
search, set `DEEPSEEK_API_KEY` and add `-UseDeepSeekQueryPlanner`:

```powershell
$env:DEEPSEEK_API_KEY = "..."
pwsh ./scripts/run_exercise_motion_youtube_bake_and_rank.ps1 `
  -ExerciseName "cat cow" `
  -UseDeepSeekQueryPlanner
```

DeepSeek is only used as a query planner. It does not download video, inspect
frames, choose the final segment, or run WHAM; those still stay in the existing
`yt-dlp`, vision review, segment detection, and bake pipeline.

## Whole Workout Plan Command

Use this when you already have a workout plan or workout-store backup JSON and want to generate movement artifacts for every exercise it contains:

```powershell
pwsh ./scripts/run_exercise_motion_workout_plan.ps1 `
  -WorkoutPlanJson "C:\path\to\workout_plan.json" `
  -WorkspaceRoot "build/exercise_motion/my-workout" `
  -ResultsPerQuery 8 `
  -MaxCandidates 5 `
  -VisionCandidatesPerExercise 5 `
  -VisionDownloadWorkers 3 `
  -VisionLlmWorkers 3 `
  -UseDeepSeekQueryPlanner `
  -ExerciseWorkers 2 `
  -ProgressIntervalSeconds 15
```

The script first writes one shared `youtube_candidates.json`, then creates one per-exercise candidate manifest and runs the existing bake stage into a separate folder for each movement. `-VisionLlmWorkers` controls the parallel vision review during YouTube candidate ranking. `-ExerciseWorkers` controls how many exercise bake pipelines run at the same time after discovery; keep it low because WHAM, video decoding, Docker, and GPU work can saturate the host quickly.

During the bake stage, the script prints progress snapshots with finished/running/queued counts, active exercise names, and the latest non-empty line from each active exercise `bake.log`. Use `-ProgressIntervalSeconds` to make this more or less chatty.

## What the script does

1. Creates a temporary workout-plan JSON for the exercise.
2. Searches YouTube using the exercise name.
3. Keeps at least 5 metadata-ranked candidates when available.
4. Scores candidate videos with the vision LLM in chunks.
5. Selects the best source video.
6. Downloads the selected YouTube video.
7. Runs independent segment detection on the selected video.
8. Trims the selected segment.
9. Runs the bake/rank motion pipeline.
10. Writes preview and Wear skeleton artifacts.

## Current scoring split

YouTube selection only decides whether a video is a good source candidate.

It scores chunks using:

```json
{
  "target_match": 0.0,
  "complete_movement": 0.0,
  "capture_quality": 0.0,
  "execution_quality": 0.0,
  "source_score": 0.0,
  "blocking_issues": ["none"],
  "confidence": 0.0,
  "reason": "short reason"
}
```

Final source ranking uses mostly vision:

```text
final_score = metadata_score * 0.10 + vision_score * 0.90
```

Segment detection owns the exact trim/window timing. Do not treat the YouTube `bestChunkIndex` as the final trim source; it is evidence/debugging for source selection.

## Important output files

For `-ExerciseName "cat cow"`, the default workspace is:

```text
build/exercise_motion/cat-cow-e2e
```

Typical outputs:

```text
build/exercise_motion/cat-cow-e2e/cat-cow-plan.json
build/exercise_motion/cat-cow-e2e/youtube_candidates.json
build/exercise_motion/cat-cow-e2e/bake-final/selection_manifest.json
build/exercise_motion/cat-cow-e2e/bake-final/<candidate>/preview/motion_preview.html
build/exercise_motion/cat-cow-e2e/bake-final/<candidate>/wear/skeleton.preview.json
build/exercise_motion/cat-cow-e2e/bake-final/<candidate>/cleaned/motion.cleaned.json
```

For the whole-plan script, the default summary is:

```text
build/exercise_motion/workout-plan/workout_motion_generation_summary.json
```

The default output root is:

```text
build/exercise_motion/workout-plan
```

Each exercise gets its own workspace:

```text
build/exercise_motion/workout-plan/<exercise-slug>/youtube_candidates.json
build/exercise_motion/workout-plan/<exercise-slug>/bake.log
build/exercise_motion/workout-plan/<exercise-slug>/bake/selection_manifest.json
build/exercise_motion/workout-plan/<exercise-slug>/bake/<candidate>/preview/motion_preview.html
build/exercise_motion/workout-plan/<exercise-slug>/bake/<candidate>/wear/skeleton.preview.json
```

## Latest verified cat cow run

Command completed successfully.

Selected source:

```text
Title: Cat Cow Stretch | Movement Demo
URL: https://www.youtube.com/watch?v=Qo7qeZDtMgk
Final score: 0.973
Vision score: 1.0
```

Generated artifacts:

```text
build/exercise_motion/cat-cow-e2e/bake-final/cat-cow-001-qo7qezdtmgk/preview/motion_preview.html
build/exercise_motion/cat-cow-e2e/bake-final/cat-cow-001-qo7qezdtmgk/wear/skeleton.preview.json
build/exercise_motion/cat-cow-e2e/bake-final/cat-cow-001-qo7qezdtmgk/cleaned/motion.cleaned.json
```

## Notes

- The run needs YouTube/network access.
- The vision path uses llama.cpp when enabled by the CLI defaults.
- The script may print H.264 decode warnings from downloaded YouTube media. The pipeline still completed in the verified run.
- If the selected source looks wrong, inspect `youtube_candidates.json` first, then inspect `selection_manifest.json` to see which source and segment were used.
