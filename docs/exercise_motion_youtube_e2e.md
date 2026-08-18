# Exercise Motion YouTube E2E Runbook

Use this when you want to start from an exercise name, find a suitable YouTube clip, run WHAM, rank the generated motion, and produce the Wear skeleton JSON.

The current default path is optimized for source quality first:

1. Search YouTube for the requested exercise name.
2. Run the semantic gate to discard unrelated candidates.
3. Run the YOLO pose prefilter on candidate timelines to find single-person, in-frame, stable-camera chunks. The single-exercise and workout-plan scripts enable this by default; pass `-SkipPosePrefilter` only for debugging.
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
  - `C:\Users\gabri\Downloads\gemma-4-12b-it-UD-Q4_K_XL.gguf`
  - `C:\Users\gabri\Downloads\mmproj-BF16(4).gguf`
  - The same Gemma model handles text-only stages without the projector and visual stages with the projector. Context/fit context is `8192`, image min tokens is `1024`, memory mapping is enabled, and `mlock` is disabled.
- A YouTube cookies file is strongly recommended for reliable downloads.

Use a long shell/tool timeout when running these. A good source can finish much faster, but difficult searches or first-time cache misses can take 10-25 minutes.

## Which Script To Use

Use these repo-level PowerShell entrypoints from `C:\Users\gabri\Documents\MyWorkoutAssistant`:

- Single exercise from an exercise name, with YouTube search, source validation, WHAM, ranking, final validation, selected preview, and selected Wear skeleton:
  `scripts/run_exercise_motion_youtube_bake_and_rank.ps1`
- Single exercise from an exact local video or exact YouTube URL, without YouTube search/ranking:
  `scripts/run_exercise_motion_generation.ps1`
- Workout plan import, one run across many plan exercises:
  `scripts/run_exercise_motion_workout_plan.ps1`

For generated app-ready movements, prefer the first and third scripts. The direct generation script is mainly for a manually chosen source clip and writes a cleaned motion preview rather than running the full candidate-selection flow.

## Single Exercise By Name

This is the normal single-exercise movement generator. It searches YouTube using the exercise name, validates source chunks before WHAM, bakes/ranks generated movement, and writes the selected preview and Wear skeleton.

```powershell
pwsh ./scripts/run_exercise_motion_youtube_bake_and_rank.ps1 `
  -ExerciseName "weighted ab wheel" `
  -WorkspaceRoot "build/exercise_motion/manual-runs" `
  -YouTubeCookiesPath "C:\Users\gabri\Downloads\www.youtube.com_cookies(18).txt" `
  -SingleExerciseNameQuery `
  -MaxSelectedResults 1 `
  -MaxSourceWindowAttempts 3 `
  -LlamaCppParallel 4 `
  -ArtifactRetention full
```

Useful optional flags:

```powershell
# Keep only compact debug artifacts instead of every generated intermediate.
-ArtifactRetention debug

# Enable experimental SpinePose fusion.
-EnableSpinePose

# Keep up to N accepted final motions so you can pick manually.
-MaxSelectedResults 3

# Disable the default pose prefilter only when debugging candidate filtering.
-SkipPosePrefilter

# Skip YouTube cookies only when public downloads are working.
# Omit -YouTubeCookiesPath
```

The single-exercise output folder is:

```text
<WorkspaceRoot>/<exercise-slug>-e2e/
```

Open this first:

```text
<WorkspaceRoot>/<exercise-slug>-e2e/bake-final/selected_section_preview.html
```

That page embeds the exact interactive preview used for the selected result and links the exact selected source input video. From the interactive preview, change preview settings and download/bake a different Wear skeleton if needed.

## Single Exercise From A Known Source

Use this only when you already know the exact source video or exact YouTube URL. This path does not run the YouTube candidate search/ranking flow.

Local video:

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -ExerciseName "barbell back squat" `
  -ExerciseSlug "barbell-back-squat-manual" `
  -VideoPath "C:\path\to\selected_source.mp4" `
  -Workspace "build/exercise_motion/manual-source-runs" `
  -UseWhamDocker `
  -SegmentStartSeconds 2.0 `
  -SegmentEndSeconds 7.0
```

Exact YouTube URL:

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -ExerciseName "barbell back squat" `
  -ExerciseSlug "barbell-back-squat-manual" `
  -YouTubeUrl "https://www.youtube.com/watch?v=VIDEO_ID" `
  -YouTubeCookiesPath "C:\Users\gabri\Downloads\www.youtube.com_cookies(18).txt" `
  -Workspace "build/exercise_motion/manual-source-runs" `
  -UseWhamDocker `
  -SegmentStartSeconds 2.0 `
  -SegmentEndSeconds 7.0
```

If you do not pass `-SegmentStartSeconds` and `-SegmentEndSeconds`, this script runs segment detection unless you pass `-UseSourceAsIs` or `-SkipSegmentDetection`.

## Workout Plan

Use this when you want to generate selected motions for every exercise in a workout plan. If you have an equipment export, pass it so exercise searches can use the equipment-qualified exercise name where available.

```powershell
pwsh ./scripts/run_exercise_motion_workout_plan.ps1 `
  -WorkoutPlanJson "C:\Users\gabri\Documents\MyWorkoutAssistant\workouts\workout_plan_2026-05-15_174946.json" `
  -EquipmentJson "C:\Users\gabri\Downloads\equipment_20260514_192507.json" `
  -WorkspaceRoot "build/exercise_motion/workout-plan/workout_plan_2026-05-15_174946" `
  -YouTubeCookiesPath "C:\Users\gabri\Downloads\www.youtube.com_cookies(18).txt" `
  -SpeedProfile fast `
  -MaxSelectedResults 1 `
  -MaxSourceWindowAttempts 3 `
  -LlamaCppParallel 4 `
  -ProgressIntervalSeconds 300 `
  -ArtifactRetention full
```

## Exercise Library

Use the library wrapper to generate and attach movements for every definition in an
`myworkoutassistant.exercise-library` package:

```powershell
pwsh ./scripts/run_exercise_motion_library.ps1 `
  -ExerciseLibraryJson "C:\Users\gabri\Downloads\my_exercise_library.json" `
  -WorkspaceRoot "build/exercise_motion/exercise-library" `
  -SpeedProfile fast `
  -MaxSelectedResults 1 `
  -ProgressIntervalSeconds 300
```

The library JSON already embeds `equipments` and `accessoryEquipments`, so `-EquipmentJson`
is optional. Pass it only to override or supplement that embedded inventory.

The wrapper runs two phases automatically. The first phase tries one recommended
candidate per unresolved definition and postpones unsuccessful definitions instead
of expanding their search immediately. After every definition has had that chance,
the second phase automatically applies the deeper search to only the postponed
definitions.

Candidate preparation is pipelined automatically. Two CPU/network prefetch workers
keep up to six upcoming exercises ready and each uses twelve parallel preview
downloads. The library runner groups ready exercises into resumable 20-exercise
waves by default. Each wave keeps one VLM session for source-cut validation,
releases it, runs the prepared candidates through one warm WHAM worker, releases
WHAM, and then keeps one VLM session for the unchanged final validators. Only
unsuccessful exercises enter the deeper individual retry lane. This prevents
per-exercise model loading and keeps GPU-backed VLM and WHAM stages mutually
exclusive on a 12 GB GPU. The defaults can be tuned with `-StagedWaveSize`,
`-PrefetchWorkers`, and `-PrefetchQueueDepth`; use `-DisableStagedWaves` or
`-DisableCpuPrefetch` only for troubleshooting.
The llama.cpp server uses eight HTTP worker threads by default, leaving the other
logical CPU threads available for candidate downloads, FFmpeg, and orchestration.

The wrapper resumes by default. Each successful exercise is materialized under its
own workspace immediately, and aggregate progress is checkpointed after every
terminal exercise. If the process is interrupted, run the same command again;
completed selections and the current phase are reused. Use `-Fresh` only when
completed selections should be regenerated.

On the first resume after a selection-policy upgrade, the wrapper automatically
revalidates legacy selections before reusing them. The report is written to
`exercise_library_revalidation_report.json`; each exercise receives a versioned
`selected/revalidation.json` marker. A selection remains reusable whenever that
specific existing artifact still passes the current policy, even if another baked
settings variant scores higher. Only rejected selections are queued for regeneration;
missing legacy review evidence is reported for manual review. Use
`-SkipExistingSelectionRevalidation` only when you
intentionally want to bypass this migration check.

Only candidates that completed identity review and were recommended by discovery
may enter baking. A failed first pass is postponed; it is not silently replaced by
an unreviewed lower-ranked source. Equipment type, equipment name, required
accessories, exercise type, category, and muscle context from the library are
preserved in each one-exercise plan and supplied to movement-contract and final
output review. Risky outputs (including adjacent title variants and rigid two-hand
equipment) receive source-versus-preview visual validation; low-risk outputs keep
the deterministic fast path.

Each exercise also stores `youtube_candidate_prefetch.json`. On resume, a manifest
whose source-plan hash still matches skips repeated prefetch work; if a cached
preview is missing, the normal review stage downloads it again.

The default output is `my_exercise_library_with_movements.json` beside the input
library. Use `-OutputJson` to choose another destination. A partial importable package
is written after phase one and updated after phase two. It preserves every definition
ID, adds `movementRef` to completed definitions, and embeds the compressed movement
files in `exerciseMovements`; unresolved definitions remain valid without a movement.

For a small batch or a single definition, append one or more filters:

```powershell
  -OnlyExerciseName "Pull-Up" `
  -OnlyExerciseName "Spin Bike Seated Cycling"
```

The clearer alias script forwards to the same implementation:

```powershell
pwsh ./scripts/run_workout_plan_motion_bake_and_rank.ps1 `
  -WorkoutPlanJson "C:\path\to\workout_plan.json" `
  -EquipmentJson "C:\path\to\equipment_export.json" `
  -WorkspaceRoot "build/exercise_motion/workout-plan" `
  -YouTubeCookiesPath "C:\Users\gabri\Downloads\www.youtube.com_cookies(18).txt"
```

To process only one exercise from the plan:

```powershell
pwsh ./scripts/run_exercise_motion_workout_plan.ps1 `
  -WorkoutPlanJson "C:\path\to\workout_plan.json" `
  -EquipmentJson "C:\path\to\equipment_export.json" `
  -WorkspaceRoot "build/exercise_motion/workout-plan/debug-one" `
  -YouTubeCookiesPath "C:\Users\gabri\Downloads\www.youtube.com_cookies(18).txt" `
  -OnlyExerciseName "Weighted Ab Wheel" `
  -MaxSelectedResults 1 `
  -ProgressIntervalSeconds 60
```

Completed workout-plan exercises are compacted into:

```text
<WorkspaceRoot>/<exercise-slug>/selected/
```

That folder keeps the selected Wear skeleton JSON, selected review WebM, selected input MP4, selected preview HTML, copied interactive preview HTML, copied `selection_manifest.json`, and debug source-selection files.

Open this first for each completed exercise:

```text
<WorkspaceRoot>/<exercise-slug>/selected/<exercise_slug>_selected_preview.html
```

That selected preview page links the exact selected input MP4 and embeds the same interactive preview page as the single-exercise output. Use it when you want to tweak preview settings and download/bake a new skeleton from the browser.

When `-MaxSelectedResults` is greater than 1, option 1 keeps the normal filenames and additional options are copied as:

```text
<exercise_slug>_option_02_wear_skeleton.json
<exercise_slug>_option_02_selected_preview.webm
<exercise_slug>_option_02_selected_input.mp4
<exercise_slug>_option_02_selected_preview.html
<exercise_slug>_option_02_interactive_preview.html
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
<exercise-slug>/selected/<exercise_slug>_selected_preview.html
<exercise-slug>/selected/<exercise_slug>_interactive_preview.html
<exercise-slug>/selected/<exercise_slug>_selected_input.mp4
<exercise-slug>/selected/<exercise_slug>_option_02_wear_skeleton.json
<exercise-slug>/selected/<exercise_slug>_option_02_selected_preview.webm
<exercise-slug>/selected/<exercise_slug>_option_02_selected_preview.html
<exercise-slug>/selected/<exercise_slug>_option_02_interactive_preview.html
<exercise-slug>/selected/<exercise_slug>_option_02_selected_input.mp4
<exercise-slug>/selected/debug/youtube_candidates.full.json
<exercise-slug>/selected/debug/candidate_decisions.jsonl
```

## Artifact Retention

The PowerShell E2E wrappers default to `-ArtifactRetention full` so manual review and reruns have all generated evidence available. Use `-ArtifactRetention debug` when you want smaller output folders.

The compact `debug` mode keeps what is normally useful to inspect a result:

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
