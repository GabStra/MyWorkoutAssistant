# Exercise-motion throughput handoff

Updated 2026-10-08. The persistent throughput goal is active and unfinished. The ranked evidence and experiment bounds live in `docs/exercise_motion_throughput_plan.md`.

## Objective and constraints

Reduce time to genuinely usable production movements across representative exercise types, preserving quality and all existing source, fit, render, review, and packaging gates. Any repeatable decrease beyond timing noise counts; there is no percentage target.

Keep Qwen fixed with no provider fallback. Use retained inputs and production paths first, isolate experiments, run timing arms sequentially with explicit caps, avoid full generation when focused replay answers the question, and commit only qualified production changes. Preserve unrelated workspace edits.

## Current findings

- Base iteration set: Barbell Romanian Deadlift and Dumbbell Overhead Press. Retained A/B runs took 735.3s/780.2s and accepted 1/2 versus 2/2 outputs; they are not a controlled speed comparison.
- The RDL's largest attributed cost is fitting (228.253s), but accepted-fit replay did not establish safely removable attempts or repeatable speed savings. The sparse-index optimization remains isolated and unpromoted.
- Selection/materialized acceptance takes 44.534–47.519s across three accepted outputs. The accepted Run B OHP profile matched all 42 comparable gate fields after path normalization; source clearance matched. The original review WEBM is missing, so video-quality parity remains unverified.
- The profile took 12.143s for core metrics and 0.077s for clearance; its 87-frame MediaPipe pass took 5.150s including cold imports. A retained 2026-10-07 same-source replay shows preflight and materialization each wrote a 248,485-byte cache for the same clip. The files are byte-identical (SHA256 `ED7F24F41B92DEE3EE49F3515DF7A67988134D2F65E76A8252CAB174E49B5D70`), but live in separate directories because production copies the clip without its adjacent cache.
- Speculative scheduling remains inconclusive: the bounded replay cap killed active fitting below its fit budget. No scheduling change is justified.

## Next action

Run `build/exercise_motion/diagnostics/profile_materialized_acceptance_cache_ab.py` with `C:\Users\gabri\miniconda3\envs\mwa-motion-cuda\python.exe` for the plan's isolated cache-sharing A/B on the fixed Run B OHP skeleton (`a5295ced101214a232ce8f31bba5c52e4f7c1ba2c7a5422a433c0140c4a04ed6`) and clip (`b76c494eb6ec44b3c16f4f27e1526d1274d3969f81d0bba2a70eeecda9b01b48`). Generate the seed cache from this exact clip inside the experiment using the current production interpreter and model configuration; do not seed from the 2026-10-07 cache, whose default-model identity is not recorded. Warm imports on a disposable copy, then use two sequential paired comparisons in reverse order with the same import state and a 120s total cap. Require identical deterministic metrics and decision, exact cache/video/model identity, zero detector calls on cache hits, and repeatable wall-time reduction beyond observed spread. No Qwen, rendering, final-output validation, or full generation. Make no production change until this passes.

Profile and reconciliation artifacts: `build/exercise_motion/diagnostics/materialized_acceptance_profile_20261008/20261008T170817Z/`. Duplicate retained cache evidence: `build/exercise_motion/speed-harness/20261007-183657-ba82ab23/`. Other exercise families still need source-qualified production-rendered evidence; the two-exercise base is not proof of universal reliability.
