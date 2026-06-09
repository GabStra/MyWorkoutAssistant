# Llama.cpp Segment Detection Notes (Qwen3VL)

## Current working setup

- Model: `C:\Users\gabri\Downloads\Qwen3VL-8B-Instruct-Q4_K_M.gguf`
- mmproj: `C:\Users\gabri\Downloads\mmproj-Qwen3VL-8B-Instruct-F16.gguf`
- CLI binary: `C:\Users\gabri\Downloads\llama-b9555-bin-win-cuda-13.3-x64\llama-mtmd-cli.exe`
- Backend: `gpu`

These are now the defaults in:

- `scripts/run_exercise_segment_detection.ps1`
- `scripts/run_exercise_motion_generation.ps1`

## Why these values matter

The current detection client (`python -m exercise_motion_pkg.cli detect-segment --llama-cpp-*`) requires a matching text model + mmproj pair.

If the pair does not match, llama.cpp returns an embedding-size mismatch error (example seen during setup: `mismatch between text model ... n_embd = 16384` vs `mmproj ... n_embd = 2560`).

## Standard detection run (single input video)

```powershell
pwsh ./scripts/run_exercise_segment_detection.ps1 `
  -VideoPath "C:\path\to\cat_cow.mp4" `
  -ExerciseName "cat cow"
```

This creates:

- `build/exercise_motion/<video-or-slug>/segment_detection/segment_detection.json`
- `build/exercise_motion/<video-or-slug>/segment_detection/frames/...`

Output JSON is then used to trim a single candidate segment in the generation flow.

## Full generation flow with auto detection (YouTube)

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -YouTubeUrl "https://www.youtube.com/watch?v=KB12DLp7Zzg" `
  -ExerciseName "cat cow" `
  -ExerciseSlug "cat-cow"
```

The generation wrapper runs:

1. optional YouTube download
2. segment detection (`run_exercise_segment_detection.ps1`)
3. trim to `detectedSpan`
4. WHAM + conversion + cleanup

## When you want whole video once (then loop later)

If you want one complete execution without auto detection, use:

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -YouTubeUrl "https://www.youtube.com/watch?v=KB12DLp7Zzg" `
  -ExerciseName "cat cow" `
  -ExerciseSlug "cat-cow" `
  -UseSourceAsIs
```

This disables detection and trimming, processes the original clip directly, and is the clean path if you only want a single pass loop candidate.

If you need a manual one-shot crop, use:

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -VideoPath "C:\path\to\cat_cow.mp4" `
  -ExerciseName "cat cow" `
  -ExerciseSlug "cat-cow" `
  -SegmentStartSeconds 12.0 `
  -SegmentEndSeconds 25.3
```

## Backend / client switching

- `-LlamaCppBackend gpu` is the default and intended for your current setup.
- `-LlamaCppBackend cpu` exists and can be used for CPU-only fallback.
- `-UseLiteRt` switches segment detection to the LiteRT/Gemma path instead of llama.cpp.

## Known-good command-line flags

- `--llama-cpp-command`
- `--llama-cpp-model`
- `--llama-cpp-mmproj`
- `--llama-cpp-backend`
- `--llama-cpp-n-predict`
- `--llama-cpp-image-min-tokens`
- `--llama-cpp-image-max-tokens`
- `--base-url` (server mode; run one `llama-server` and reuse process)
- detection tuning:
  - `--window-seconds`
  - `--overlap-seconds`
  - `--frames-per-window`
  - `--max-frame-width`
  - `--merge-gap-seconds`
  - `--min-segment-seconds`
  - `--max-segment-seconds`
  - `--confidence-threshold`
- generation wrapper passthrough for the same:
  - `-SegmentWindowSeconds`
  - `-SegmentOverlapSeconds`
  - `-SegmentFramesPerWindow`
  - `-SegmentMaxFrameWidth`
  - `-SegmentMergeGapSeconds`
  - `-SegmentConfidenceThreshold`
  - `-SegmentMinSegmentSeconds`
  - `-SegmentMaxSegmentSeconds`

## Speed profile switches

- `-UseLlamaCppServer` in `run_exercise_segment_detection.ps1` starts/uses `llama-server` instead of launching `llama-mtmd-cli` per window.
- `-LlamaCppNPredict`, `-LlamaCppImageMinTokens`, `-LlamaCppImageMaxTokens` let you tune prompt runtime and vision token budget when quality still holds.

## Fastest practical profile (trade-off aware)

On local tests with RTX 4070 SUPER + Qwen3VL-8B-Q4_K_M, the fastest settings that stayed stable were:

```powershell
pwsh ./scripts/run_exercise_segment_detection.ps1 `
  -VideoPath "C:\path\to\cat_cow.mp4" `
  -ExerciseName "cat cow" `
  -UseLlamaCppServer `
  -LlamaCppNPredict 128 `
  -LlamaCppImageMinTokens 512 `
  -LlamaCppImageMaxTokens 1024 `
  -WindowSeconds 10 `
  -OverlapSeconds 2 `
  -FramesPerWindow 6 `
  -MaxFrameWidth 640 `
  -ConfidenceThreshold 0.45
```

Measured wall-clock was around **35–55s per detection** on that clip, with quality generally acceptable after a few sanity checks.

If you keep `-LlamaCppNPredict` too low, the server can return truncated JSON payloads, so keep a quick fallback validation step in place.

## Quick checks before a run

1. Confirm the files exist at the configured paths.
2. Confirm `segment_detection.json` is produced and has one sensible `detectedSpan`.
3. If results are poor, verify prompt/window settings before changing model backend first.

## Timing strategy (window-first)

The current detection flow is window-driven:

- `movement_present` is the primary signal for candidate windows.
- `movement_start_seconds`, `movement_end_seconds`, and `executions` are treated as coarse hints, not authoritative boundaries.
- Final span selection is computed from contiguous positive windows, then trimmed with setup/recovery heuristics.
- Per-window timing hints can only tighten spans; they should not force a multi-window boundary.

If a single attempt still gets merged with neighbors, reduce `-SegmentOverlapSeconds`/`-SegmentWindowSeconds`, or raise `-SegmentConfidenceThreshold`.

## Direct download command used for the mmproj

```powershell
curl -L --fail "https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-F16.gguf?download=true" `
  -o "C:\Users\gabri\Downloads\mmproj-Qwen3VL-8B-Instruct-F16.gguf"
```

Keep this file with the model file under `Downloads` so the scripts can resolve defaults without manual overrides.
