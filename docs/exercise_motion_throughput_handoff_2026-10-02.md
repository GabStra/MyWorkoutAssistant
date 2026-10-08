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
- The 117-frame RDL structural-refinement profile measured 71.451s in that stage. One trajectory solve dominated; four other `least_squares` calls were tiny camera registrations, not repeat full fits. Two alternative Jacobian color orders both remained at 108 groups.
- An isolated retained-input `x_scale="jac"` postprocess completed in 30.525s, but that is not a matched speed comparison and its candidate failed root-continuity, physical-pose and limb-velocity diagnostics. Two reversed direct-fit pairs showed only a 0.669-1.401s fit-only edge, with different poses; this is not a quality-qualified gain. A missing-camera preflight also lacks incidence on the retained accepted production paths.
- Run B's accepted RDL is a terminal cyclic rebake with a passing pre-render gate. Its separate final controlled fit took 208.266s: a source-preflight-valid full-interval attempt failed fitted anatomy/seam checks after 99.078s, then the retained-interval fit passed in 108.922s. The second fit reused all 40 anatomy-repair frames and shared support calibration. The failed attempt cannot be skipped from source preflight alone.
- The exact pre-controlled-fit baked payload was pruned from Run B. Replaying from the final cyclic-rebaked skeleton or regenerating the upstream bake would not be an exact reproduction, so no attempt-skip/budget experiment is justified from this artifact.

## Confirmed defect and limits

Commit `b01c5d44` fixes mutable anatomy-report aliasing in production `controlled_motion.py`: a projection trial used to overwrite its own baseline. Focused regression passed. This is a correctness fix, not a demonstrated end-to-end speed improvement.

Retained browser A/B: `build/exercise_motion/diagnostics/rdl-report-alias-replay/production-fix/` and `parent-revision-replay/`. Both passed fit/pre-render/kinematic checks through the retained fallback and rendered a near-identical 117-frame RDL. They took 255.085s/294.672s; single-pair timing is not repeatability proof. Final VLM review and packaging were not run. The direct fitter comparison did not exercise the fixed branch.

Rendered sample comparison: `build/exercise_motion/diagnostics/rdl-report-alias-replay/rendered_ab_contact_sheet.jpg`. Sampling is not full continuous playback review.

## Next action

Fit/lifecycle/request audits are complete. One generic fit optimization is staged in isolated branch `experiment/motion-fit-throughput-20261008`: omit redundant sparse row deduplication before Boolean assignment. Balanced mask construction saved about 2.3s with exact parity; the complete 117-frame Jacobian also matched exactly, and two owning tests plus compilation passed. Four matched RDL fits all passed and produced identical pose digests, but timing reversed with run order (mean candidate was 1.317s slower), so this is not a proven end-to-end gain. Keep the code isolated; do not promote it yet. Evidence/ledger: `build/exercise_motion/diagnostics/throughput_execution_20261008/`.

The retained scheduling replay's OFF1 completed in 191.569s; its full 117-frame RDL candidate passed the pre-render gate and had a review video. The 2.0s crop was correctly rejected. Initial ON hit the external 300s cap without persisted events, so OFF2 was omitted. A fresh diagnostic ON (`runs/20261008T143015Z-359d45`) showed OHP yield/abandon correctly; RDL browser CPU admission and fit-slot admission both had no meaningful wait. RDL held the fit slot until the watchdog killed the process at 300s, below its 360s fit budget. It produced no artifact before kill. This identifies the replay timeout as an external harness cap interrupting active fitting; it does not establish a production deadlock or prove a prefetch slowdown. No OFF/ON conclusion is valid.

Defer further prefetch contention replay and production scheduling edits unless new production traces show lost critical-path time. The RDL lineage question is resolved: the accepted cyclic rebake came from a distinct final controlled fit; the `x_scale="jac"` replay fails at an earlier postprocess diagnostic stage and is not a production regression. The two coloring screens did not reduce groups, and the small direct-fit timing edge is not quality-qualified.

Next, run the plan's single 120s source-clearance and core deterministic-acceptance profile on an isolated copy of accepted Run B OHP. Exact selected skeleton SHA256 is `a5295ced101214a232ce8f31bba5c52e4f7c1ba2c7a5422a433c0140c4a04ed6`; the source manifest is `515c47f218f59b158d5bcfa71fe7de51957f893099e51a9b2c2c3e9fed8d3727`; the candidate source, selected segment, and retained-package selected input share SHA256 `b76c494eb6ec44b3c16f4f27e1526d1274d3969f81d0bba2a70eeecda9b01b48`; candidate and retained-package exact-source pose references match at SHA256 `4cbb785a45716b0efe713a51b05d74819b4e76718662246e4f575faae39e35d2`. Source-clearance image inputs survive. The original review WEBM does not, so exclude only its quality submetric and do not substitute the package preview. Make no Qwen calls, render no contact sheets, and do no full selection replay. Stop if any other input or deterministic decision differs; change production only if this profile identifies a concrete repeated cost.

The sparse-index candidate remains unpromoted: the source lineage of its fit timing input is incomplete and its matched full-fit timing was inconclusive. Floor Press remains source-cleared but output-rejected; Step-Up is source-unqualified. Other families still need qualified original source evidence. The two base exercises do not establish broad exercise reliability. Preserve support/contact/source semantics during optimization.
