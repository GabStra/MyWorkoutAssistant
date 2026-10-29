# Exercise Motion YouTube E2E Runbook

Use this when you want to start from an exercise name, find a suitable YouTube clip, reconstruct and rank the generated motion, and produce the Wear skeleton JSON. GVHMR in Docker is the only movement reconstruction backend.

The current default path is optimized for source quality first:

1. Search YouTube for the requested exercise name.
2. Run the semantic gate to discard unrelated candidates.
3. Run the YOLO pose prefilter on candidate timelines to find single-person, in-frame, stable-camera chunks. The single-exercise and workout-plan scripts enable this by default; pass `-SkipPosePrefilter` only for debugging.
4. Review the remaining source chunks with the VLM.
5. Run source validation and source segment preparation before reconstruction.
6. Run the configured motion reconstructor, deterministic cleanup, adaptive preview settings, movement cut selection, and final materialization.
7. Write `selection_manifest.json`, the selected preview, and the selected Wear skeleton JSON.

## Prerequisites

- Run from the repo root: `C:\Users\gabri\Documents\MyWorkoutAssistant`.
- Docker Desktop with GPU support must be running; GVHMR uses `myworkoutassistant/gvhmr:torch2.3-cu121`.
- All exercise movement model work uses Qwen3.5-9B UD-Q4_K_XL through llama.cpp:
  - `C:\Users\gabri\Downloads\Qwen3.5-9B-UD-Q4_K_XL.gguf`
  - `C:\Users\gabri\Downloads\mmproj-BF16(6).gguf`
  - The same model handles text-only stages without the projector and visual stages with the projector. The configured context is `8192`, image minimum is `1024` tokens, memory mapping is enabled, and `mlock` is disabled.
- A YouTube cookies file is strongly recommended for reliable downloads.

Use a long shell/tool timeout when running these. A good source can finish much faster, but difficult searches or first-time cache misses can take 10-25 minutes.

## Which Script To Use

Use these repo-level PowerShell entrypoints from `C:\Users\gabri\Documents\MyWorkoutAssistant`:

- Single exercise from an exercise name, with YouTube search, source validation, reconstruction, ranking, final validation, selected preview, and selected Wear skeleton:
  `scripts/run_exercise_motion_youtube_bake_and_rank.ps1`
- Single exercise from an exact local video or exact YouTube URL, without YouTube search/ranking:
  `scripts/run_exercise_motion_generation.ps1`
- Workout plan import, one run across many plan exercises:
  `scripts/run_exercise_motion_workout_plan.ps1`

For generated app-ready movements, prefer the first and third scripts. The direct generation script is mainly for a manually chosen source clip and writes a cleaned motion preview rather than running the full candidate-selection flow.

## Single Exercise By Name

This is the normal single-exercise movement generator. It searches YouTube using the exercise name, validates source chunks before reconstruction, bakes/ranks generated movement, and writes the selected preview and Wear skeleton. It runs GVHMR in Docker.

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
  -SegmentStartSeconds 2.0 `
  -SegmentEndSeconds 7.0
```

The direct-generation wrapper also runs GVHMR in Docker.

If you do not pass `-SegmentStartSeconds` and `-SegmentEndSeconds`, this script runs segment detection unless you pass `-UseSourceAsIs` or `-SkipSegmentDetection`.

## Workout Plan

Use this when you want to generate selected motions for every exercise in a workout plan. If you have an equipment export, pass it so exercise searches can use the equipment-qualified exercise name where available.

Both the single-exercise and workout-plan wrappers maintain
`build/exercise_motion/source_outcome_index.json` by default. Each source video is
counted once per run, even when several windows from that video are attempted. The
index records source-pass, reconstruction, final-acceptance, and rejection-tag
counts for both videos and channels. Discovery uses this history only as a bounded
ranking prior; current semantic, pose, source, and final-output gates remain
authoritative. Override the shared location with `-SourceOutcomeIndexJson` when an
isolated A/B run must not learn from production history.

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
downloads. The library runner groups ready exercises into resumable 8-exercise
waves by default. Each wave keeps one VLM session for source-cut validation,
releases it, runs the prepared candidates through one warm reconstruction worker
(GVHMR by default), releases the reconstructor, and then keeps one VLM session for
the unchanged final validators. Only
unsuccessful exercises enter the deeper individual retry lane. This prevents
per-exercise model loading and keeps GPU-backed VLM and reconstruction stages mutually
exclusive on a 12 GB GPU. The defaults can be tuned with `-StagedWaveSize`,
`-PrefetchWorkers`, and `-PrefetchQueueDepth`; use `-DisableStagedWaves` or
`-DisableCpuPrefetch` only for troubleshooting.
The llama.cpp server uses eight HTTP worker threads by default, leaving the other
logical CPU threads available for candidate downloads, FFmpeg, and orchestration.

For the experimental two-GPU arrangement, set
`$env:EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE = '1'` and add
`-GvhmrStageSplit -SharedLlamaServer` to the workout-plan command. This requires
staged waves, warm workers, GPU locking, and two distinct physical devices.
Preprocessing uses the selected secondary GPU with one heavy model resident at a
time. Prediction uses GPU 0 alongside the resident llama.cpp server; model requests
pause while prediction runs. At most two candidates enter the split pipeline, so
preprocessing the next candidate can overlap prediction of the current one.
The default remains the single reconstruction worker until controlled production
tests establish both rendered quality and time to an accepted movement.
Handoffs bind the exact source, configuration, model image, code and artifact bytes;
changed inputs require fresh evidence rather than silently reusing approval.

Source review uses semantic requirement descriptions across repetitions, alternating
pairs, distinct-end sequences, holds, travel and ongoing cycles. Logical phase IDs
stay inside code; the model selects from the supplied descriptions and source-frame
choices. Code still validates frame identities, sample coverage, equipment quantity
and required sequence order. A phase and a variant describing the same visible fact
can share one observation; repeated occurrences of the same phase remain unresolved
unless they have distinct semantic context.

When exact pose evidence establishes a single unanchored two-phase return cycle,
code supplies its start, excursion and return images and derives completion from
the measured cycle plus observed actions. The source review and interval-action
review use separate cached questions with the same cyclic-boundary policy. Other
movement types retain their completion and endpoint checks rather than being forced
into this geometry. A source-evidence policy upgrade can require fresh review;
structural library coverage does not establish rendered movement quality.

For sequences with three or more required phases, code proposes intervals from
confidence-qualified, separate left/right articulation tracks. Each interval review
receives chronological source samples, including the samples between its turning
points. The model selects qualitative action descriptions, without supplying times
or frame references. Code constructs exact citations and finds nonoverlapping ordered
coverage; one interval labelled with multiple actions cannot establish their order.
Both halves of an excursion remain candidates, since different actions can occupy
opposite directions. The 15-degree proposal prominence suppresses noisy candidates;
it neither approves an action nor changes source motion. Occlusion gaps are not
interpolated. Missing proposals or ambiguous labels remain unresolved.
Code proposes one coherent measured sequence before requesting action semantics,
rather than querying every overlapping interval hypothesis. Each phase receives
individual original-resolution images containing its measured motion witnesses,
endpoints and turning-point neighbors. The retained live replay showed that contact
sheets could confuse push-ups and alternating rows even with the same prompt and
schema. The model still has to confirm each action; the measured proposal cannot
approve itself. Unresolved or contradicted observations leave the sequence unresolved
within the existing source-turn budget. Equipment and clean-content questions use
uniform source images without unrelated motion-sheet attachments.
The clean-content question also receives the reviewed defining action and required
actions; without that context it cannot distinguish a prescribed transition from
unrelated exercise or setup.
Independent decisions are cached against source bytes, model, contract, images and
exact sample times. Equivalent phase and variant requirements share observed evidence.
Action labels enter that coverage only after their measured completion witnesses
pass. Currently supported action grammar covers push-ups, rows, squat cleans and
overhead presses: returns toward the observed entry state, separate left/right
excursions where required, a catch near the shoulders, and a terminal overhead
reach with arm extension. Unsupported action completion remains unresolved rather
than falling back to a label as proof. These are necessary two-dimensional motion
observations, not proof of exercise identity or three-dimensional form.
Only actual confident samples provide witnesses; an upper-arm track can corroborate
a row with an uncertain wrist. No missing joint is synthesized, and adjacent
observations must remain within the existing half-second gap limit.
Unchanged unresolved interval observations are cached as unresolved; new imagery
or other changed question evidence is required to ask again. Aggregate approvals
are separately versioned from these reusable semantic observations. A compound
phase cannot acquire proof from a predicate covering only one of its actions.
Other semantic facts still return a single observation object with code-owned
identity, so duplicate requirement rows cannot replace another fact.
When the phase list is explicitly approved, its coverage also owns composite-action
coverage; inferred complex phase proposals cannot add obligations to the reviewed
definition or replace the defining-action review. The measured two-phase cycle path
remains separate.
An explicit `all_uniform_samples` choice on a supported clean-interval claim expands
to the exact provided samples in code. Missing or mixed coverage remains unresolved.

Explicit overhead-press requirements additionally need corroborating landmarks from
the hash-verified source video. The check uses confident, visible head and arm
observations relative to the torso axis, and verifies that the cited samples
actually cover the observed overhead reach. This is a necessary observation, not
proof of a press or a three-dimensional lockout. Relevant phase reviews receive
individual source frames around the measured event. Cropping, uncertain tracking,
or unsupported citations leave the source unresolved for a clearer interval or
human review; they do not trigger reconstruction or relax the requirement.
Other actions currently rely on the narrow visual review and existing source
checks, rather than claiming an independent pose predicate that has not been
implemented and validated. Generated movement fidelity remains a separate gate.

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

## Source-funnel measurement

Every new `selection_manifest.json` includes `timings.sourceFunnel`, with the
first candidate's source-pass, reconstruction, acceptance, and rejection evidence.
Aggregate a frozen validation set without launching any model:

```powershell
python scripts/analyze_exercise_motion_source_funnel.py `
  build/exercise_motion/source-selection-baseline `
  --label baseline `
  --wall-seconds 1282.0 `
  --out-json build/exercise_motion/source-selection-baseline-summary.json
```

Pass the measured wall duration for the whole invocation with `--wall-seconds`; use
the arm's `wallSeconds` value in the harness `results.json` array for an isolated
run. Per-manifest `timings.totalSeconds` values are reported separately as
`summedCandidateProcessingSeconds` and are never used as whole-run elapsed time. If
whole-run wall time is omitted, `acceptedOutputsPerWallHour` is null.

Run the same frozen exercise/search set into a separate workspace and outcome index,
then compare `firstCandidateSourcePassRate`, `firstCandidateAcceptanceRate`,
`meanProcessedCandidatesPerSelection`, `acceptedOutputsPerWallHour`, and the rejection
taxonomy. Do not promote a ranking change if manual review shows a higher false-accept
rate, even when throughput improves.

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

- raw reconstruction outputs such as `.pkl` and `.pth`
- raw/cleaned/retarget/source generation directories
- per-frame contact-sheet dumps like `frame_*.jpg`
- `.npy` and `.npz` scratch artifacts

Use `-ArtifactRetention full` when you need to inspect reconstructor internals or every intermediate file from a run.

## Debugging A Bad Result

Start with `selection_manifest.json`.

Check:

- `timings`: where time was spent.
- `artifactRetention`: what was pruned.
- `selected`: final Wear skeleton, selected preview video, selected input video, section timing, and ranking payload.
- `selectedResults`: all retained manual-pick options when `-MaxSelectedResults` is greater than 1.
- `candidateResults`: which candidates reached reconstruction and which failed earlier.
- `reviewItems`: what generated previews were reviewed and how they scored.

Then inspect:

- `youtube_candidates.json` or `selected/debug/youtube_candidates.full.json` for source selection and VLM source scores.
- `candidate_decisions.jsonl` for batch-by-batch YouTube candidate decisions.
- The exact source path in `<candidate>/segment_detection/exact_source_phase_validation.json` and its matching pose-reference/video hashes. A retained workspace may omit `input/selected_segment.mp4`; a parent `source/source.mp4` is usable only when its bytes match that exact reference.
- `<candidate>/review/ranking.json` to see final preview scoring.
- `<candidate>/segment_detection/segment_selection.json` when the source cut is wrong.
- `<candidate>/review/**/contact_sheet_*.jpg` when the VLM cut decision is suspect.

If the run selected nothing, keep the failed workspace and rerun with `-ArtifactRetention full` only when the compact evidence is not enough.

For foot sliding, trace source observations through the fit-frame contact mask before running another reconstruction. Compound actions can contain local standing episodes without any joint staying stationary throughout the clip. These episodes need grounded posture corroboration; a stationary ankle alone does not establish a fixed heel, toe, or shoe heading.

Support classification can refresh from hash-bound retained pose and landmark observations without repeating source approval or model inference. Uncertain full-sole motion may be corroborated by independent heel/toe texture tracks over that exact interval. Contact states and interval bounds stay unchanged; only a verified material receipt authorizes stationary material anchors. Anchor identities must survive the native-source-to-fit clock mapping, including fractional frame-rate differences.

Carry source interval timestamps through sparse pose sampling and inference-video normalization. A sample-count ratio or normalized playback FPS cannot identify the original source exposure. Source comparisons and contact masks must use the retained source clock; synthetic bridge frames do not inherit observed support.

Inspect `sourceSupportAuthority`, `contactConstraintEvidence`, and `trajectoryFitEvidence` in the fit report. Zero constrained samples are not verified planting; unresolved evidence stays distinct from an optional check or compatibility-only geometric fit. Dense floor correction must measure the same shoe vertices and orientation as playback validation, while preserving observed plants. A polish step may not retain a new failure in a previously passing source or physical check, including individual contact and floor limits inside an already-failing playback result.
