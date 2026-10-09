# Qwen exercise vision and segment detection

Exercise movement generation uses Qwen3.5-9B UD-Q4_K_XL for all text and vision
model work: exercise contracts, source selection and review, segment detection,
and visual review of generated movement.

The local llama.cpp defaults are:

- Model: `C:\Users\gabri\Downloads\Qwen3.5-9B-UD-Q4_K_XL.gguf`
- Vision projector: `C:\Users\gabri\Downloads\mmproj-BF16(6).gguf`
- Server: `C:\Users\gabri\Documents\llama.cpp\build-master\bin\Release\llama-server.exe`

Text-only requests use the model without the projector. Image and video-frame
requests use the same model with its matching projector. Keep both files
available at the configured paths, or pass the corresponding model settings to
the PowerShell runner.

## Detect an exercise segment

```powershell
pwsh ./scripts/run_exercise_segment_detection.ps1 `
  -VideoPath "C:\path\to\downloaded_video.mp4" `
  -ExerciseName "burpee"
```

The command samples frames from overlapping video windows, asks Qwen which
windows contain the requested movement, and writes the selected span and frame
evidence under:

```text
build/exercise_motion/<video-stem-or-slug>/segment_detection/
```

The main generation wrapper can use this span to trim the source before GVHMR
reconstruction. You can provide `-SegmentStartSeconds` and
`-SegmentEndSeconds` to choose a span directly, or pass `-UseSourceAsIs` to
process the whole source.

## Run the full movement flow

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -YouTubeUrl "https://www.youtube.com/watch?v=VIDEO_ID" `
  -ExerciseName "burpee" `
  -ExerciseSlug "burpee"
```

The wrapper performs segment detection when no explicit segment is supplied,
then runs GVHMR in Docker and continues through conversion, cleanup, and preview
generation.

Historical WHAM-labeled cache files and metadata remain readable for compatible
retained artifacts. They are not rewritten; cache reuse still depends on the
normal identity checks.
