# Exercise-motion throughput handoff

Updated 2026-10-08. The active goal is still open; the full evidence and qualification matrix are in `docs/exercise_motion_throughput_plan.md`.

## Current result

- The bounded native source-frame cache is enabled by default in production and the speed harness. Two matched production pairs in opposite orders both favored ON: 40.1s and 85.1s lower total wall time, and 37.957s and 85.423s earlier first packaged output. All four arms packaged both RDL/OHP results with complete lineage.
- Source windows and selected MP4 bytes matched. Playback review found no cache-specific regression: one exercise matched exactly in each pair; the other had small joint deltas with equivalent visible range, support and timing. Shared RDL elbow and OHP lockout/equipment-visibility limitations remain.
- A separate foot-landmark cache-transfer change saved 2.2–3.5s on each retained-input materialized-acceptance replay for RDL and OHP, with identical cached bytes and deterministic gate metrics. This is a measured stage saving; the original review videos are missing, and the replay did not measure fresh end-to-end time to package.
- Do not run another full cache comparison. Other audited stages have no new performance experiment with a proven safe saving. An older Floor Press artifact still lacks rack-use evidence; a separate verified source cleared policy 60 but needs current policy-62 review and selected-output fidelity validation.
- The narrow Qwen JSON-grammar compatibility retry passed its exact saved-request replay and focused regression; neither production pair triggered it, so production incidence is unknown.

## Next work

The current margin audit found no new performance experiment with both proven removable work and a faithful, quality-discriminating replay. Do not benchmark highest-cost stages alone. An older two-wave run spent 115.283s in two GVHMR startups, but its outputs have no accepted/package lineage and each worker stop enforces Qwen's exclusive GPU handoff; no safe saving is established. Keep the goal active. For family qualification, Barbell Floor Press is the strongest retained candidate: its confirmed source matches the current Barbell + Squat Rack context and contract policy 30, and it cleared source policy 60. The next bounded step is one current source-policy-62 source-only review using Qwen, with no discovery, reconstruction, or generation. This will qualify only source semantics; the selected package is still policy 121 and needs manual review because source-pose-fidelity evidence is unavailable. Keep all gates and motion quality, and commit only qualified production changes.

Cache A/B roots: `build/exercise_motion/speed-harness/20261008-210549-f07e8576/`, `.../20261008-211843-39688924/`, `.../20261008-213659-88077694/`, `.../20261008-214936-c97ed79e/`.
