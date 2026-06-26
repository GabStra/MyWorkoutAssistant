# Exercise Motion YouTube E2E Runbook

Use this when you want to start from an exercise name, find a suitable YouTube clip, run WHAM, rank the generated motion, and produce the Wear skeleton JSON.

The current default path is optimized for source quality first:

1. Search YouTube for the requested exercise name.
2. Run the semantic gate to discard unrelated candidates.
3. Run the YOLO pose prefilter on candidate timelines to find single-person, in-frame, stable-camera chunks. The single-exercise script enables this by default; the workout-plan script uses it when `-PosePrefilter` is passed.
4. Review the remaining source chunks with the VLM.
5. Run pre-WHAM source validation and source segment preparation.
6. Run WHAM, deterministic cleanup, adaptive preview settings, movement cut selection, and final materialization.
7. Write `selection_manifest.json`, the selected preview, and the selected Wear skeleton JSON.

## Prerequisites

- Run from the repo root: `C:\Users\gabri\Documents\MyWorkoutAssistant`.
- Docker Desktop must be running for the default WHAM Docker path.
- The default WHAM repo is `C:\Users\gabri\Downloads\WHAM`; otherwise the scripts try `third_party\WHAM`.
- The default body model root is `<WHAM>\dataset\body_models`.
- The default VLM path uses llama.cpp with:
  - `C:\Users\gabri\Downloads\gemma-4-12B-it-heretic-QAT-UD-Q4_K_XL.gguf`
  - `C:\Users\gabri\Downloads\mmproj-BF16.gguf`
- A YouTube cookies file is strongly recommended for reliable downloads.

Use a long shell/tool timeout when running these. A good source can finish much faster, but difficult searches or first-time cache misses can take 10-25 minutes.

## Single Exercise

```powershell
pwsh ./scripts/run_exercise_motion_youtube_bake_and_rank.ps1 `
  -ExerciseName "barbell bench press" `
  -WorkspaceRoot "build/exercise_motion/manual-runs" `
  -YouTubeCookiesPath "C:\Users\gabri\Downloads\www.youtube.com_cookies(8).txt"
```

Useful optional flags:

```powershell
# Keep every raw/generated intermediate for deep debugging.
-ArtifactRetention full

# Enable experimental SpinePose fusion.
-EnableSpinePose

# Keep up to N accepted final motions so you can pick manually.
-MaxSelectedResults 3

# Skip YouTube cookies only when public downloads are working.
# Omit -YouTubeCookiesPath
```

## Workout Plan

Use this when you want to generate one selected motion per exercise in a workout plan. If you have an equipment export, pass it so exercise searches are prefixed with the equipment name where available.

```powershell
pwsh ./scripts/run_exercise_motion_workout_plan.ps1 `
  -WorkoutPlanJson "C:\path\to\workout_plan.json" `
  -EquipmentJson "C:\path\to\equipment_export.json" `
  -WorkspaceRoot "build/exercise_motion/workout-plan" `
  -YouTubeCookiesPath "C:\Users\gabri\Downloads\www.youtube.com_cookies(8).txt" `
  -PosePrefilter `
  -MaxSelectedResults 3
```

The clearer alias script forwards to the same implementation:

```powershell
pwsh ./scripts/run_workout_plan_motion_bake_and_rank.ps1 `
  -WorkoutPlanJson "C:\path\to\workout_plan.json" `
  -EquipmentJson "C:\path\to\equipment_export.json" `
  -WorkspaceRoot "build/exercise_motion/workout-plan" `
  -YouTubeCookiesPath "C:\Users\gabri\Downloads\www.youtube.com_cookies(8).txt" `
  -PosePrefilter
```

Completed workout-plan exercises are compacted into:

```text
<WorkspaceRoot>/<exercise-slug>/selected/
```

That folder keeps the selected Wear skeleton JSON, selected review WebM, selected input MP4, copied `selection_manifest.json`, and debug source-selection files.

When `-MaxSelectedResults` is greater than 1, option 1 keeps the normal filenames and additional options are copied as:

```text
<exercise_slug>_option_02_wear_skeleton.json
<exercise_slug>_option_02_selected_preview.webm
<exercise_slug>_option_02_selected_input.mp4
```

## Output To Inspect

For a single exercise, the important files are under:

```text
<WorkspaceRoot>/<exercise-slug>-e2e/
```

Primary outputs:

```text
youtube_candidates.json
bake-final/selection_manifest.json
bake-final/selected_section_preview.html
bake-final/selected_section_preview_02.html
bake-final/<candidate>/input/selected_segment.mp4
bake-final/<candidate>/review/<selected>.webm
bake-final/<candidate>/wear/<selected>.json
```

For a workout-plan run:

```text
workout_motion_generation_summary.json
<exercise-slug>/bake.log
<exercise-slug>/selected/selection_manifest.json
<exercise-slug>/selected/<exercise_slug>_wear_skeleton.json
<exercise-slug>/selected/<exercise_slug>_selected_preview.webm
<exercise-slug>/selected/<exercise_slug>_selected_input.mp4
<exercise-slug>/selected/<exercise_slug>_option_02_wear_skeleton.json
<exercise-slug>/selected/<exercise_slug>_option_02_selected_preview.webm
<exercise-slug>/selected/<exercise_slug>_option_02_selected_input.mp4
<exercise-slug>/selected/debug/youtube_candidates.full.json
<exercise-slug>/selected/debug/candidate_decisions.jsonl
```

## Artifact Retention

The default retention mode is `debug`.

It keeps what is normally useful to inspect a result:

- `selection_manifest.json`
- selected input video
- selected review video
- selected Wear skeleton JSON
- selected preview HTML and candidate preview HTML
- candidate/review manifests
- contact sheets and candidate decision logs

It removes bulky generated intermediates:

- WHAM raw outputs such as `.pkl` and `.pth`
- raw/cleaned/retarget/source generation directories
- per-frame contact-sheet dumps like `frame_*.jpg`
- `.npy` and `.npz` scratch artifacts

Use `-ArtifactRetention full` when you need to debug WHAM internals or inspect every intermediate file from a run.

## Debugging A Bad Result

Start with `selection_manifest.json`.

Check:

- `timings`: where time was spent.
- `artifactRetention`: what was pruned.
- `selected`: final Wear skeleton, selected preview video, selected input video, section timing, and ranking payload.
- `selectedResults`: all retained manual-pick options when `-MaxSelectedResults` is greater than 1.
- `candidateResults`: which candidates reached WHAM and which failed earlier.
- `reviewItems`: what generated previews were reviewed and how they scored.

Then inspect:

- `youtube_candidates.json` or `selected/debug/youtube_candidates.full.json` for source selection and VLM source scores.
- `candidate_decisions.jsonl` for batch-by-batch YouTube candidate decisions.
- `<candidate>/input/selected_segment.mp4` to verify the source fed into WHAM.
- `<candidate>/review/ranking.json` to see final preview scoring.
- `<candidate>/segment_detection/segment_selection.json` when the source cut is wrong.
- `<candidate>/review/**/contact_sheet_*.jpg` when the VLM cut decision is suspect.

If the run selected nothing, keep the failed workspace and rerun with `-ArtifactRetention full` only when the compact evidence is not enough.
