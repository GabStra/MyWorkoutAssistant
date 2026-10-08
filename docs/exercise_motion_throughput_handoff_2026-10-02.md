# Exercise-motion throughput handoff

Updated 2026-10-08. The persistent throughput goal is active and unfinished. The ranked evidence and experiment bounds live in `docs/exercise_motion_throughput_plan.md`.

## Objective and constraints

Reduce time to genuinely usable production movements across representative exercise types, preserving quality and all existing source, fit, render, review, and packaging gates. Any repeatable decrease beyond timing noise counts; there is no percentage target.

Keep Qwen fixed with no provider fallback. Use retained inputs and production paths first, isolate experiments, run timing arms sequentially with explicit caps, avoid full generation when focused replay answers the question, and commit only qualified production changes. Preserve unrelated workspace edits.

## Current findings

- Base iteration set: Barbell Romanian Deadlift and Dumbbell Overhead Press. Retained A/B runs took 735.3s/780.2s and accepted 1/2 versus 2/2 outputs; they are not a controlled speed comparison.
- The RDL's largest attributed cost is fitting (228.253s), but accepted-fit replay did not establish safely removable attempts or repeatable speed savings. The sparse-index optimization remains isolated and unpromoted.
- Selection/materialized acceptance takes 44.534–47.519s across three accepted outputs. The accepted Run B OHP profile matched all 42 comparable gate fields after path normalization; source clearance matched. The original review WEBM is missing, so video-quality parity remains unverified.
- The profile took 12.143s for core metrics and 0.077s for clearance; its 87-frame MediaPipe pass took 5.150s including cold imports. OHP and RDL A/Bs that include the production cache-transfer helper saved 3.300/2.730s and 3.476/2.165s respectively beyond their timing spreads; transfer itself cost 0.038–0.055s. All compared deterministic gates and cache payloads matched; warm arms made zero detector calls. Production carries a cache across the deterministic-confirmation copy only when video bytes, model bytes, and schema v3 match. Both original candidate review WEBMs are missing, so video-quality parity remains unverified.
- Speculative scheduling remains inconclusive: the bounded replay cap killed active fitting below its fit budget. No scheduling change is justified.

## Next action

Next: the cache-only optimization is stage-qualified on both base exercises. Continue with the remaining ranked areas only if retained evidence supports a specific, bounded test; preserve the rule that broad throughput claims need fresh production-rendered/package evidence. No full generation is currently justified by this cache fix.

Profile and reconciliation artifacts: `build/exercise_motion/diagnostics/materialized_acceptance_profile_20261008/20261008T170817Z/`. Duplicate retained cache evidence: `build/exercise_motion/speed-harness/20261007-183657-ba82ab23/`. Other exercise families still need source-qualified production-rendered evidence; the two-exercise base is not proof of universal reliability.
