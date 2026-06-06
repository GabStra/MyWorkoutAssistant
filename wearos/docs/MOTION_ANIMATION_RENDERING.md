# Wear Motion Animation Rendering

This documents the current V1 flow for generating a baked exercise animation from video and rendering it on Wear with `WearSkeletonMotionPreview`.

## 1. Generate Motion From Video

Use the repo runner. It downloads/copies the source video, optionally trims it, runs WHAM, cleans the motion, generates the HTML review preview, and exports a Wear-ready skeleton JSON.

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -YouTubeUrl "https://www.youtube.com/watch?v=VIDEO_ID" `
  -UseWhamDocker
```

For a local video:

```powershell
pwsh ./scripts/run_exercise_motion_generation.ps1 `
  -ExerciseSlug deadlift `
  -VideoPath "C:\path\to\video.mp4" `
  -UseWhamDocker
```

Useful options:

- `-UseSourceAsIs`: skip segment detection and use the whole source clip.
- `-SkipSegmentDetection`: skip automatic segment detection but still run the rest of the pipeline.
- `-SegmentStartSeconds <n> -SegmentEndSeconds <n>`: manually trim the source before WHAM.
- `-WhamRepoPath "C:\Users\gabri\Downloads\WHAM"`: override the WHAM checkout path.
- `-BodyModelRoot "C:\Users\gabri\Downloads\WHAM\dataset\body_models"`: override SMPL body model path.

Main generated artifacts are written under:

```text
build/exercise_motion/<exercise-slug>/
```

Important outputs:

```text
preview/motion_preview.html
wear/skeleton.preview.json
cleaned/motion.cleaned.json
manifest.json
```

## 2. Review And Bake The Wear Skeleton

Open the HTML preview:

```text
build/exercise_motion/<exercise-slug>/preview/motion_preview.html
```

Use it as the review gate. The Wear export is meant to match the preview's baked skeleton configuration:

- automatic world alignment
- root drift lock
- selected loop
- optional Y drift lock
- centering/framing

The pipeline already writes:

```text
build/exercise_motion/<exercise-slug>/wear/skeleton.preview.json
```

If you need to re-export from an existing cleaned motion JSON:

```powershell
python -m exercise_motion_pkg.cli wear-skeleton `
  --motion-json "build/exercise_motion/<exercise-slug>/cleaned/motion.cleaned.json" `
  --out-json "build/exercise_motion/<exercise-slug>/wear/skeleton.preview.json" `
  --title "<exercise-slug>" `
  --loop-index 0
```

Use `--loop-index -1` to bake the full clip. Add `--lock-y-drift` if the selected movement should also freeze root Y drift.

## 3. Add The JSON To Wear

Copy the baked JSON into Wear raw resources with an Android-safe resource name:

```powershell
Copy-Item `
  -LiteralPath "build\exercise_motion\<exercise-slug>\wear\skeleton.preview.json" `
  -Destination "wearos\src\main\res\raw\<exercise_slug>_skeleton.json" `
  -Force
```

Resource names must be lowercase with underscores only.

Current V1 test asset:

```text
wearos/src/main/res/raw/youtube_uyumul_g_v0_loop_1_lock_feet.json
```

## 4. Render On Wear

Use `WearSkeletonMotionPreview`:

```kotlin
WearSkeletonMotionPreview(
    modifier = Modifier.fillMaxSize(),
    skeletonResId = R.raw.youtube_uyumul_g_v0_loop_1_lock_feet,
    animated = true,
    viewYawDegrees = -28f,
    viewPitchDegrees = 18f,
    orbitView = false,
)
```

For visual testing in Android Studio, use the preview in:

```text
wearos/src/main/java/com/gabstra/myworkoutassistant/composables/WearSkeletonMotionPreview.kt
```

`orbitView = true` rotates the camera around the model. For production playback, prefer `orbitView = false` and update `viewYawDegrees` only from user input, so the component avoids unnecessary frame invalidation.

## 5. Renderer Contract

The Wear renderer expects a JSON payload with:

- `kind = "wearPreviewSkeleton"`
- `fps`
- `frames`
- `bounds`
- per-frame `joints`

The renderer does not run cleanup, alignment, loop selection, or root locking. Those are baked into the exported JSON by `write_wear_skeleton_json`.

The current V1 renderer is intentionally lightweight:

- Compose `Canvas`, no OpenGL dependency.
- Primary-color low-poly humanoid.
- Animated joint caps to visually connect limb segments.
- Articulated pelvis/spine/ribcage rather than a single solid torso.
- Head rendered as a shaded sphere.
- Floor grid projected from the same camera transform as the model.

## 6. Verification

After changing Wear rendering code or raw resources, compile:

```powershell
./gradlew :wearos:compileDebugKotlin :shared:compileDebugKotlin --parallel --build-cache
```

For motion pipeline changes, run the focused Python tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_exercise_motion_pkg.py
```
