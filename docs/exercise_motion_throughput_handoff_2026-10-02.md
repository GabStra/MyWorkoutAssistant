# Exercise-motion throughput handoff

Updated 2026-10-08. Current task: execute the user-activated plan using bounded retained-stage experiments.

## Governing objective

Reduce end-to-end time to usable production movements across representative exercise types, preserving or improving motion quality and existing source, fit, render, review and packaging gates. Any repeatable reduction beyond noise counts; **no percentage target**. The persistent goal is not yet achieved.

Read `docs/exercise_motion_throughput_plan.md` for ranked evidence, bounded experiments and promotion criteria. This replaces the older shared-server-first experiment sequence. Historical detail remains in Git history and retained build artifacts.

## Current evidence

- Production/harness are Qwen-only; no CLEF fallback. Keep backend fixed for performance comparisons.
- Base exercises: Barbell Romanian Deadlift + Dumbbell Overhead Press. Fixed fixture: `build/exercise_motion/throughput_goal_fixtures_20261007_v4b/fixture_manifest.json`.
- Retained runs `20261008-121537-bc560935` and `20261008-122851-cb085986` took 735.3s/780.2s and packaged 1/2 versus 2/2. Different revisions/configurations prevent a controlled speed claim.
- Dominant attributed RDL cost: 228.253s fitting; browser startup/page ready 2.540s. The fit audit found no reusable work across distinct intervals; exact Jacobian masks were the measured repeat work. The sparse-index optimization preserved outputs, but four full-fit timings did not show a repeatable gain. The two intervals remain non-interchangeable inputs.
- Run B's OHP speculative worker ran for 52.803s before abandonment. That is worker wall time; the exact overlap with RDL finalization and any causal slowdown are unknown. The retained trace shows no finalizer wait (`renderPrefetchWaitSeconds=0.0`).
- Each retained wave already reused one reconstruction worker across two requests; exclusive final VLM handoff requires release. No avoidable restart was found. Review traces showed no exact duplicate requests; per-call identity evidence is incomplete.
- Browser frame batching is production-default on. Source-frame caching remains opt-in; these runs explicitly enabled it. Do not count already-enabled optimizations as new margin.

## Confirmed defect and limits

Commit `b01c5d44` fixes mutable anatomy-report aliasing in production `controlled_motion.py`: a projection trial used to overwrite its own baseline. Focused regression passed. This is a correctness fix, not a demonstrated end-to-end speed improvement.

Retained browser A/B: `build/exercise_motion/diagnostics/rdl-report-alias-replay/production-fix/` and `parent-revision-replay/`. Both passed fit/pre-render/kinematic checks through the retained fallback and rendered a near-identical 117-frame RDL. They took 255.085s/294.672s; single-pair timing is not repeatability proof. Final VLM review and packaging were not run. The direct fitter comparison did not exercise the fixed branch.

Rendered sample comparison: `build/exercise_motion/diagnostics/rdl-report-alias-replay/rendered_ab_contact_sheet.jpg`. Sampling is not full continuous playback review.

## Next action

Fit/lifecycle/request audits are complete. One generic fit optimization is staged in isolated branch `experiment/motion-fit-throughput-20261008`: omit redundant sparse row deduplication before Boolean assignment. Balanced mask construction saved about 2.3s with exact parity; the complete 117-frame Jacobian also matched exactly, and two owning tests plus compilation passed. Four matched RDL fits all passed and produced identical pose digests, but timing reversed with run order (mean candidate was 1.317s slower), so this is not a proven end-to-end gain. Keep the code isolated; do not promote it yet. Evidence/ledger: `build/exercise_motion/diagnostics/throughput_execution_20261008/`.

The retained scheduling replay completed OFF1 in 191.569s; its full 117-frame RDL candidate passed the pre-render gate and had a review video. The 2.0s crop was correctly rejected. ON hit the external 300s cap; the adapter buffered events until worker joins, so the timeout left no decisive trace. OHP's partial fit failed its gates, and RDL produced no baked artifact. OFF2 was not run; no OFF/ON conclusion is valid. This is not evidence of a production deadlock or contention regression.

Next, only if pursuing this hypothesis, add append-only flushed event telemetry to the replay adapter at BrowserWorkers enqueue/start, CPU scheduler admission wait/acquire, fit-slot wait/acquire, and OHP abandon/yield. Then run at most one capped diagnostic replay to identify the blocked stage; do not treat it as a timing comparison. Do not launch it automatically. Preserve the exact retained inputs, full RDL loop inventory, production 360s fit budget, and 300s process-tree cap. No model, reconstruction, download, or full generation work is needed. If telemetry cannot distinguish a likely cause within that cap, defer this hypothesis and advance to the next ranked area.

The sparse-index candidate remains unpromoted: the source lineage of its fit timing input is incomplete and its matched full-fit timing was inconclusive. Floor Press remains source-cleared but output-rejected; Step-Up is source-unqualified. Other families still need qualified original source evidence. The two base exercises do not establish broad exercise reliability. Preserve support/contact/source semantics during optimization.
