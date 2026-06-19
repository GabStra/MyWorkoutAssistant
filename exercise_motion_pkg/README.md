# Exercise Motion Tooling

Pipeline for turning an exercise video into a cleaned, reviewable motion clip that can later be rendered in the HTML preview and on Wear.

Current scope:

- accepts a YouTube URL or local video file
- runs WHAM from a prepared local checkout, or consumes an existing `wham_output.pkl`
- reconstructs joints from WHAM `pose_world` or `pose`
- performs automated post-processing: ground-plane fitting, soft root-height clamping, foot contact detection, foot locking, and support-segment root stabilization
- writes `ground.metadata.json` plus embedded `metadata.ground`
- writes a standalone HTML/WebGL preview
- writes an offline retarget handoff:
  - fixed target rig contract
  - WHAM SMPL retarget source JSON when `wham_output.pkl` is available

Not in scope:

- browser-side live rig retargeting
- `.glb` export
- direct Wear integration
- physics-based humanoid simulation

## Install

```powershell
pip install -e .[motion,test]
```

## WHAM Setup

Clone and prepare the official WHAM repo locally:

1. Clone `https://github.com/yohanshin/WHAM`
2. Follow the repo install instructions
3. Make sure these required assets exist:
   - `demo.py`
   - `checkpoints/wham_vit_w_3dpw.pth.tar`
   - `checkpoints/hmr2a.ckpt`
   - `checkpoints/vitpose-h-multi-coco.pth`
   - `checkpoints/yolo26x.pt`
   - `dataset/body_models/smpl/SMPL_NEUTRAL.pkl`

Repo defaults:

- WHAM repo: `C:\Users\gabri\Downloads\WHAM`
- body model root: `C:\Users\gabri\Downloads\WHAM\dataset\body_models`
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
  -WhamRepoPath "C:\Users\gabri\Downloads\WHAM" `
  -BodyModelRoot "C:\Users\gabri\Downloads\WHAM\dataset\body_models" `
  -WhamPython "python" `
  -EstimateLocalOnly
```

Runtime behavior:

1. copies or downloads the source video into `build/exercise_motion/<slug>/input`
2. optionally detects the exercise span and trims the clip first
3. runs WHAM and writes `wham_output.pkl` under `build/exercise_motion/<slug>/raw/wham/<video-stem>/`
4. converts the result into repo motion JSON
5. applies the automated post-processing pass and regenerates motion-derived ground metadata
6. writes raw, cleaned, preview, and manifest artifacts

Main artifacts:

- `manifest.json`
- `raw/motion.raw.json`
- `raw/wham/<video-stem>/wham_output.pkl`
- `cleaned/motion.cleaned.json`
- `cleaned/ground.metadata.json`
- `retarget/target_rig.contract.json`
- `retarget/wham.retarget_source.json` when the pipeline ran from WHAM output
- `preview/motion_preview.html`

## Local LLM Segment Detection

For the current llama.cpp + Qwen3VL setup (paths, mmproj compatibility, and the cat-cow workflow), see [LLAMACPP_SEGMENT_DETECTION.md](LLAMACPP_SEGMENT_DETECTION.md).

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

The resulting JSON contains the selected span that the main generator can trim before WHAM runs.

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
  --wham-repo-path "C:\\Users\\gabri\\Downloads\\WHAM" `
  --body-model-root "C:\\Users\\gabri\\Downloads\\WHAM\\dataset\\body_models"
```

If you already ran WHAM yourself:

```powershell
python -m exercise_motion_pkg.cli generate `
  --exercise-slug squat `
  --video-path "C:\\path\\to\\video.mp4" `
  --wham-results-pkl "C:\\path\\to\\wham_output.pkl" `
  --body-model-root "C:\\Users\\gabri\\Downloads\\WHAM\\dataset\\body_models"
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
