# Exercise-motion throughput handoff

Updated 2026-10-08. Current task: execute the user-activated plan using bounded retained-stage experiments.

## Governing objective

Reduce end-to-end time to usable production movements across representative exercise types, preserving or improving motion quality and existing source, fit, render, review and packaging gates. Any repeatable reduction beyond noise counts; **no percentage target**. The persistent goal is not yet achieved.

Read `docs/exercise_motion_throughput_plan.md` for ranked evidence, bounded experiments and promotion criteria. This replaces the older shared-server-first experiment sequence. Historical detail remains in Git history and retained build artifacts.

## Current evidence

- Production/harness are Qwen-only; no CLEF fallback. Keep backend fixed for performance comparisons.
- Base exercises: Barbell Romanian Deadlift + Dumbbell Overhead Press. Fixed fixture: `build/exercise_motion/throughput_goal_fixtures_20261007_v4b/fixture_manifest.json`.
- Retained runs `20261008-121537-bc560935` and `20261008-122851-cb085986` took 735.3s/780.2s and packaged 1/2 versus 2/2. Different revisions/configurations prevent a controlled speed claim.
- Dominant attributed RDL cost: 228.253s fitting; browser startup/page ready 2.540s. First inspect fit subphases and exact reusable work; the two intervals are not interchangeable fit inputs.
- Render speculation was off in the first run; on in the second. The second's 52.803s OHP preparation was abandoned. Contention is a hypothesis requiring a matched captured-workload replay.
- Reconstruction startup 108.102s/53.899s and vision startup 43.615s/44.501s are measured opportunities; avoidability is unproven.
- Browser frame batching is production-default on. Source-frame caching remains opt-in; these runs explicitly enabled it. Do not count already-enabled optimizations as new margin.

## Confirmed defect and limits

Commit `b01c5d44` fixes mutable anatomy-report aliasing in production `controlled_motion.py`: a projection trial used to overwrite its own baseline. Focused regression passed. This is a correctness fix, not a demonstrated end-to-end speed improvement.

Retained browser A/B: `build/exercise_motion/diagnostics/rdl-report-alias-replay/production-fix/` and `parent-revision-replay/`. Both passed fit/pre-render/kinematic checks through the retained fallback and rendered a near-identical 117-frame RDL. They took 255.085s/294.672s; single-pair timing is not repeatability proof. Final VLM review and packaging were not run. The direct fitter comparison did not exercise the fixed branch.

Rendered sample comparison: `build/exercise_motion/diagnostics/rdl-report-alias-replay/rendered_ab_contact_sheet.jpg`. Sampling is not full continuous playback review.

## Next action

Fit/lifecycle/request audits are complete. One generic fit optimization is staged in isolated branch `experiment/motion-fit-throughput-20261008`: omit redundant sparse row deduplication before Boolean assignment. Balanced mask construction saved about2.3s with exact parity; the complete117-frame Jacobian also matched exactly, and two owning tests plus compilation passed. Four matched RDL fits all passed and produced identical pose digests, but the full-fit timing reversed with run order (mean candidate was1.317s slower), so this is not a proven end-to-end gain. The test input lacks complete source lineage and is not package qualification. Keep the code isolated; do not promote yet. Evidence/ledger: `build/exercise_motion/diagnostics/throughput_execution_20261008/`. Default promotion is pending. Next: bounded retained OHP render-prefetch versus RDL fit contention measurement if a faithful adapter can be built from retained inputs; do not repeat this RDL fit comparison, completed audits, or microbenchmarks. Independent audits may use subagents; timing experiments remain sequential. No unbounded solver sweeps, arbitrary gate relaxation, backend retest, or full generation before isolated evidence warrants it.

Floor Press remains source-cleared but output-rejected; Step-Up is source-unqualified. Other families need qualified original source evidence. The two base exercises do not establish broad exercise reliability. Preserve support/contact/source semantics during optimization.
