# Exercise Motion Tooling

Pipeline for turning an exercise video into a cleaned, reviewable motion clip that can later be rendered in the HTML preview and on Wear.

Current scope:

- accepts a YouTube URL or local video file
- runs GVHMR in Docker, or consumes an existing `reconstruction_output.pkl`
- reconstructs joints from the GVHMR result's normalized reconstruction fields
- performs automated post-processing: ground-plane fitting, soft root-height clamping, foot contact detection, foot locking, and support-segment root stabilization
- writes `ground.metadata.json` plus embedded `metadata.ground`
- writes a standalone HTML/WebGL preview
- writes an offline retarget handoff:
  - fixed target rig contract
  - SMPL retarget source JSON when `reconstruction_output.pkl` is available

Not in scope:

- browser-side live rig retargeting
- `.glb` export
- direct Wear integration
- physics-based humanoid simulation

## Install

```powershell
pip install -e .[motion,test]
```

## Reconstruction and model setup

GVHMR is the movement reconstruction backend and runs in Docker. The default image
is `myworkoutassistant/gvhmr:torch2.3-cu121`; Docker Desktop and a working GPU
container runtime are required. No local reconstruction checkout, SLAM setup,
SMPLify environment, or host checkpoint installation is used by this pipeline.

Qwen3.5-9B UD-Q4_K_XL is used for all exercise movement model work, including
exercise contracts, source review, and visual output review. Text requests use
the GGUF without an image projector; vision requests use its matching
`mmproj-BF16(6).gguf`. See
[LLAMACPP_SEGMENT_DETECTION.md](LLAMACPP_SEGMENT_DETECTION.md) for the local
model paths and segment-detection command.

The default workspace is `build/exercise_motion`. The pipeline can reuse an
existing reconstruction result when its cache identity matches. Legacy cache
files and metadata carrying historical WHAM labels remain readable through
explicit result paths; existing artifacts are left untouched. Automatic stage
reuse requires the current cache layout and identity, so older stages may be
recomputed after this migration.

## Repo Runner

GPU work checks the hottest NVIDIA card before starting each reconstruction,
pose/depth operation, or model request. At 80°C, new GPU work waits until all
cards reach 74°C or below. Active operations finish normally; models stay loaded
and CPU preparation/fitting can continue through the existing worker queues.
Cooling waits are logged and bounded to ten minutes or the remaining candidate
budget, whichever is shorter. An individual operation can still exceed 80°C;
this policy only pauses between operations. If temperature telemetry is initially
unavailable, a warning reports that cooling admission cannot be enforced; losing
telemetry during an active cooling wait fails that operation.

On dual-GPU hosts, set `EXERCISE_MOTION_EXCLUSIVE_GPU_DEVICE=1` to move
reconstruction, pose/depth/spine stages to the second card behind their own
lock lane while the resident llama server is pinned to the first card. Reviews
and reconstruction then overlap instead of trading server drain/restart cycles;
single-GPU hosts ignore the setting and keep the legacy single-lane behavior.

For the current app-ready movement-generation commands, including single-exercise YouTube search/ranking and workout-plan generation, use the runbook:

```text
docs/exercise_motion_youtube_e2e.md
```

Use `run_exercise_motion_generation.ps1` when you already have a specific local video or exact YouTube URL and want to run the lower-level GVHMR/cleanup/preview pipeline without YouTube candidate search and ranking:

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -ExerciseSlug squat `
  -VideoPath "C:\path\to\video.mp4"
```

For a YouTube source:

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -YouTubeUrl "https://www.youtube.com/watch?v=eFYv8Skf66g"
```

Key overrides:

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -ExerciseSlug burpee `
  -VideoPath "C:\path\to\video.mp4" `
  -UseReconstructionDocker `
  -ReconstructionDockerImage "myworkoutassistant/gvhmr:torch2.3-cu121"
```

Runtime behavior:

1. copies or downloads the source video into `build/exercise_motion/<slug>/input`
2. optionally detects the exercise span and trims the clip first
3. runs GVHMR in Docker and writes `reconstruction_output.pkl` under `build/exercise_motion/<slug>/raw/reconstruction/<video-stem>/`
4. converts the result into repo motion JSON
5. applies the automated post-processing pass and regenerates motion-derived ground metadata
6. writes raw, cleaned, preview, and manifest artifacts

Main artifacts:

- `manifest.json`
- `raw/motion.raw.json`
- `raw/reconstruction/<video-stem>/reconstruction_output.pkl`
- `cleaned/motion.cleaned.json`
- `cleaned/ground.metadata.json`
- `retarget/target_rig.contract.json`
- `retarget/reconstruction.retarget_source.json` when the pipeline has a reconstruction result
- `preview/motion_preview.html`

## Local LLM Segment Detection

For the current llama.cpp + Qwen 3.5 setup (paths, mmproj compatibility, and the cat-cow workflow), see [LLAMACPP_SEGMENT_DETECTION.md](LLAMACPP_SEGMENT_DETECTION.md).

Use the segment detector before extraction when you want a tighter clip:

```powershell
pwsh ./scripts/run_exercise_segment_detection.ps1 `
  -VideoPath "C:\path\to\downloaded_video.mp4" `
  -ExerciseName "burpee"
```

What it does:

1. uses the configured local Qwen3.5-9B vision model
2. splits the video into overlapping windows
3. samples keyframes from each window
4. asks the local model which windows contain the actual exercise cycle
5. writes:

```text
build/exercise_motion/<video-stem-or-slug>/segment_detection/segment_detection.json
build/exercise_motion/<video-stem-or-slug>/segment_detection/frames/...
```

The resulting JSON contains the selected span that the main generator can trim before GVHMR runs.

## Normalized Motion Contract

The downstream app code uses a stable repo-owned motion JSON contract:

```json
{
  "fps": 30,
  "jointNames": ["pelvis", "spine", "neck", "head", "left_hip", "left_knee", "left_ankle"],
  "frames": [
    {
      "timeSec": 0.0,
      "joints": {
        "pelvis": [0.0, 0.95, 0.0]
      }
    }
  ]
}
```

If you already have a normalized motion JSON, pass `--normalized-motion-json` and the extractor stage is skipped.

## Direct CLI Example

```powershell
python -m exercise_motion_pkg.cli generate `
  --exercise-slug squat `
  --youtube-url "https://www.youtube.com/watch?v=eFYv8Skf66g" `
  --use-reconstruction-docker `
  --reconstruction-docker-image "myworkoutassistant/gvhmr:torch2.3-cu121"
```

If you already have a GVHMR result:

```powershell
python -m exercise_motion_pkg.cli generate `
  --exercise-slug squat `
  --video-path "C:\\path\\to\\video.mp4" `
  --reconstruction-results-pkl "C:\\path\\to\\reconstruction_output.pkl"
```

The shared reconstruction options use backend-neutral names, including
`--no-reuse-reconstruction-cache`, `--use-reconstruction-docker`,
`--reconstruction-docker-image`, `--reconstruction-docker-shm-size`,
`--reconstruction-docker-gpus`, `--reconstruction-timeout-seconds`, and
`--export-reconstruction-smpl-preview`. The selected reconstruction worker is
GVHMR.

## Kinematic Refinement

Generate the refinement bundle from cleaned motion:

```powershell
python -m exercise_motion_pkg.cli physics-bundle `
  --motion-json "build/exercise_motion/how-to-do-burpees/cleaned/motion.cleaned.json" `
  --out-dir "build/exercise_motion/how-to-do-burpees/physics_bundle"
```

This writes:

- `reference_targets.json`
- `controller_config.json`
- `summary.json`

Then run the deterministic refinement pass:

```powershell
python -m exercise_motion_pkg.cli physics-sim `
  --bundle-dir "build/exercise_motion/how-to-do-burpees/physics_bundle" `
  --out-motion-json "build/exercise_motion/how-to-do-burpees/physics_bundle/simulated_motion.kinematic.json" `
  --preview-html "build/exercise_motion/how-to-do-burpees/physics_bundle/simulated_preview.kinematic.html"
```

Current behavior:

- `backend=kinematic` is the default and the main supported path
- `backend=prototype` remains available as a simpler damping-only fallback
- the public workflow no longer exposes the failed MuJoCo branch
