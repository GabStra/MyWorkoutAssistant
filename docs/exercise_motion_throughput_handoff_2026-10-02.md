# Exercise-motion throughput handoff

Updated 2026-10-09. The active goal is still open; the full evidence and qualification matrix are in `docs/exercise_motion_throughput_plan.md`.

## Current result

- The bounded native source-frame cache is enabled by default in production and the speed harness. Two matched production pairs in opposite orders both favored ON: 40.1s and 85.1s lower total wall time, and 37.957s and 85.423s earlier first packaged output. All four arms packaged both RDL/OHP results with complete lineage.
- Source windows and selected MP4 bytes matched. Playback review found no cache-specific regression: one exercise matched exactly in each pair; the other had small joint deltas with equivalent visible range, support and timing. Shared RDL elbow and OHP lockout/equipment-visibility limitations remain.
- A separate foot-landmark cache-transfer change saved 2.2–3.5s on each retained-input materialized-acceptance replay for RDL and OHP, with identical cached bytes and deterministic gate metrics. This is a measured stage saving; the original review videos are missing, and the replay did not measure fresh end-to-end time to package.
- Do not run another full cache comparison. Other audited stages have no new performance experiment with proven safe savings. The 2026-10-08 policy-62 source-only review of `ZzEQWEZZDik` completed, but the selected frames do not establish the required rack-supported bar setup. This source is not a qualified family fixture, so no selected-output fidelity check is justified.
- The narrow Qwen JSON-grammar compatibility retry passed its exact saved-request replay and focused regression; neither production pair triggered it, so production incidence is unknown.

## Next work

A bounded CPU replay identified discarded Linear initialization in the two strictly checkpoint-loaded preprocessors. After applying identical checkpoint-cache preconditioning, both order pairs saved 8.112s/8.343s in complete constructors, beyond observed spread (3.360s baseline, 3.129s candidate); all 906 parameter/buffer states and checkpoint hashes matched. Evidence: `build/exercise_motion/diagnostics/pretrained_startup_20261008/cache_conditioned/summary.json`. The unconditioned comparison was inconclusive and must not be repeated. Production remains unchanged. Both exact retained-input worker replays now match all consumed reconstruction fields and metadata; DemoPL checkpoint keys are complete. One OHP readiness timeout was diagnosed from retained state (ready at 126.369s, clean stop, no job); a single 180s-cap retry passed. These are correctness runs, not comparable startup timing arms. Next: define one matched production comparison with valid retained source stages and preserved real acceptance/review/render/package. Confirm exact input identity and isolate both arms before running; the older WHAM retained-pair config is not interchangeable. Do not repeat CPU or output-parity runs. CPU stage savings do not establish time to package. Keep Qwen and exclusive GPU handoffs fixed.

The policy-62 Floor Press source-only review is complete, but the source lacks visible required rack support and cannot qualify the selected output. Its `cleared` status records selection provenance; the resolved repair bypassing contradictory equipment evidence remains a separate quality concern with unmeasured runtime impact. Keep the goal active and commit only qualified production changes.

Cache A/B roots: `build/exercise_motion/speed-harness/20261008-210549-f07e8576/`, `.../20261008-211843-39688924/`, `.../20261008-213659-88077694/`, `.../20261008-214936-c97ed79e/`.
