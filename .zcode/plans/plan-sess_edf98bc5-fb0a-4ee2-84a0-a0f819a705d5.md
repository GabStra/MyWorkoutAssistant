Diagnose and free up C: drive storage:

1. Run a read-only size scan of C: hotspots (Gradle caches, Android SDK/AVD images, HuggingFace/LM Studio/llama.cpp models, Temp, pip caches, Downloads, the repo's motion-gen artifacts, Recycle Bin) and report the sizes before touching anything.
2. Apply cleanups in safety order, confirming destructive steps:
   - Safe deletions: temp files, Gradle daemon logs/stale caches, pip cache purge, Recycle Bin.
   - Safe relocations to another drive: HuggingFace/LM Studio models (via HF_HOME / app settings or directory symlinks), Android AVD system images, large repo artifacts — using symlinks or env vars so nothing breaks.
3. Verify apps/tools still resolve the relocated data (Gradle build works, models load) and report space freed.