# Exercise Motion Tooling

Pipeline for turning an exercise video into a cleaned, reviewable motion clip that can later be rendered in the HTML preview and on Wear.

Current scope:

- accepts a YouTube URL or local video file
- runs GVHMR from a prepared local checkout, or consumes an existing `hmr4d_results.pt`
- reconstructs joints from GVHMR `smpl_params_global`
- performs cleanup: trim idle frames, estimate support ground, stabilize drift, smooth jitter
- writes `ground.metadata.json` plus embedded `metadata.ground`
- writes a standalone HTML/WebGL preview
- can emit a deterministic kinematic refinement bundle and refined motion preview

Not in scope:

- `.glb` export
- Blender rig retargeting
- direct Wear integration
- physics-based humanoid simulation

## Install

```powershell
pip install -e .[motion,test]
```

## GVHMR Setup

Clone and prepare the official GVHMR repo locally:

1. Clone `https://github.com/zju3dv/GVHMR`
2. Follow the repo install instructions
3. Make sure these required assets exist:
   - `tools/demo/demo.py`
   - `inputs/checkpoints/gvhmr/gvhmr_siga24_release.ckpt`
   - `inputs/checkpoints/hmr2/epoch=10-step=25000.ckpt`
   - `inputs/checkpoints/vitpose/vitpose-h-multi-coco.pth`
   - `inputs/checkpoints/yolo/yolov8x.pt`
   - `inputs/checkpoints/body_models/smpl/SMPL_NEUTRAL.pkl`
   - `inputs/checkpoints/body_models/smplx/SMPLX_NEUTRAL.npz`

Repo defaults:

- GVHMR repo: `C:\Users\gabri\Downloads\GVHMR`
- body model root: `C:\Users\gabri\Downloads\GVHMR\inputs\checkpoints\body_models`
- workspace: `build/exercise_motion`

## Repo Runner

Use the repo-level PowerShell entrypoint for the full flow:

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
  -GvhmrRepoPath "C:\Users\gabri\Downloads\GVHMR" `
  -BodyModelRoot "C:\Users\gabri\Downloads\GVHMR\inputs\checkpoints\body_models" `
  -GvhmrPython "python" `
  -StaticCamera
```

Runtime behavior:

1. copies or downloads the source video into `build/exercise_motion/<slug>/input`
2. optionally detects the exercise span and trims the clip first
3. runs GVHMR and writes `hmr4d_results.pt` under `build/exercise_motion/<slug>/raw/gvhmr/<video-stem>/`
4. converts the result into repo motion JSON
5. cleans the motion and regenerates motion-derived ground metadata
6. writes raw, cleaned, preview, and manifest artifacts

Main artifacts:

- `manifest.json`
- `raw/motion.raw.json`
- `raw/gvhmr/<video-stem>/hmr4d_results.pt`
- `cleaned/motion.cleaned.json`
- `cleaned/ground.metadata.json`
- `preview/motion_preview.html`

## Local LLM Segment Detection

Use the segment detector before extraction when you want a tighter clip:

```powershell
pwsh ./scripts/run_exercise_segment_detection.ps1 `
  -VideoPath "C:\path\to\downloaded_video.mp4" `
  -ExerciseName "burpee"
```

What it does:

1. starts the local LiteRT-LM/Gemma vision flow
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
  --gvhmr-repo-path "C:\\Users\\gabri\\Downloads\\GVHMR" `
  --body-model-root "C:\\Users\\gabri\\Downloads\\GVHMR\\inputs\\checkpoints\\body_models"
```

If you already ran GVHMR yourself:

```powershell
python -m exercise_motion_pkg.cli generate `
  --exercise-slug squat `
  --video-path "C:\\path\\to\\video.mp4" `
  --gvhmr-results-pt "C:\\path\\to\\hmr4d_results.pt" `
  --body-model-root "C:\\Users\\gabri\\Downloads\\GVHMR\\inputs\\checkpoints\\body_models"
```

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
