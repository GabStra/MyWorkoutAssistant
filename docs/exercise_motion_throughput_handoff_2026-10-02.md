# Exercise-motion throughput handoff

Updated 2026-10-08. The active goal is still open; the full evidence and qualification matrix are in `docs/exercise_motion_throughput_plan.md`.

## Current result

- The bounded native source-frame cache is enabled by default in production and the speed harness. Two matched production pairs in opposite orders both favored ON: 40.1s and 85.1s lower total wall time, and 37.957s and 85.423s earlier first packaged output. All four arms packaged both RDL/OHP results with complete lineage.
- Source windows and selected MP4 bytes matched. Playback review found no cache-specific regression: one exercise matched exactly in each pair; the other had small joint deltas with equivalent visible range, support and timing. Shared RDL elbow and OHP lockout/equipment-visibility limitations remain.
- Do not run another full cache comparison. Other audited stages do not yet have a measured, safely removable cost plus a retained replay that can distinguish an improvement. The Floor Press source remains unqualified for rack-use semantics.
- The narrow Qwen JSON-grammar compatibility retry passed its exact saved-request replay and focused regression; neither production pair triggered it, so production incidence is unknown.

## Next work

Use the plan's risk-based family qualification on the next source-qualified representative output. For performance changes, begin with retained evidence and proceed only when it demonstrates removable work and a bounded replay. Keep Qwen fixed, preserve all gates and motion quality, and commit only qualified production changes.

Cache A/B roots: `build/exercise_motion/speed-harness/20261008-210549-f07e8576/`, `.../20261008-211843-39688924/`, `.../20261008-213659-88077694/`, `.../20261008-214936-c97ed79e/`.
