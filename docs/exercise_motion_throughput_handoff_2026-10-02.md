# Exercise-motion throughput handoff

Updated 2026-10-08. The active goal is still open; the full evidence and qualification matrix are in `docs/exercise_motion_throughput_plan.md`.

## Current result

- The bounded native source-frame cache is enabled by default in production and the speed harness. Two matched production pairs in opposite orders both favored ON: 40.1s and 85.1s lower total wall time, and 37.957s and 85.423s earlier first packaged output. All four arms packaged both RDL/OHP results with complete lineage.
- Source windows and selected MP4 bytes matched. Playback review found no cache-specific regression: one exercise matched exactly in each pair; the other had small joint deltas with equivalent visible range, support and timing. Shared RDL elbow and OHP lockout/equipment-visibility limitations remain.
- A separate foot-landmark cache-transfer change saved 2.2–3.5s on each retained-input materialized-acceptance replay for RDL and OHP, with identical cached bytes and deterministic gate metrics. This is a measured stage saving; the original review videos are missing, and the replay did not measure fresh end-to-end time to package.
- Do not run another full cache comparison. Other audited stages have no new performance experiment with proven safe savings. The 2026-10-08 policy-62 source-only review of `ZzEQWEZZDik` completed, but the selected frames do not establish the required rack-supported bar setup. This source is not a qualified family fixture, so no selected-output fidelity check is justified.
- The narrow Qwen JSON-grammar compatibility retry passed its exact saved-request replay and focused regression; neither production pair triggered it, so production incidence is unknown.

## Next work

The current margin audit found no new performance experiment with both proven removable shared work and a faithful, quality-discriminating replay. Do not benchmark highest-cost stages alone. An older two-wave run spent 115.283s in two GVHMR startups, but it has no accepted/package lineage and each worker stops for Qwen's exclusive GPU handoff; no safe saving is established. The policy-62 Floor Press source-only review is complete, but this source does not visibly establish required rack support and cannot qualify the selected output. Its harness `cleared` status is source-selection provenance, not semantic qualification: the resolved disagreement repair returned despite contradictory identity/equipment evidence. This is a quality-risk lead, not a quantified throughput opportunity; no reconstruction was run. Keep the goal active and hold experiments until retained evidence identifies removable shared work with a reliable accepted-output replay. Preserve all gates and motion quality; commit only qualified production changes.

Cache A/B roots: `build/exercise_motion/speed-harness/20261008-210549-f07e8576/`, `.../20261008-211843-39688924/`, `.../20261008-213659-88077694/`, `.../20261008-214936-c97ed79e/`.
