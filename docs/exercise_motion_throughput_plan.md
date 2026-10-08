# Exercise-motion improvement plan

Updated 2026-10-08. This replaces the earlier throughput experiment sequence.

> For agentic workers: execute one evidence-backed task at a time using the existing production paths. Independent source/timing audits may use subagents; timing experiments run sequentially. Read this plan before launching work.

**Goal:** Reduce time to usable production movement across representative exercise types, preserving or improving motion quality and all existing gates. Any repeatable reduction beyond normal timing noise counts; there is no percentage target.

**Architecture:** Optimize the owning stage using retained inputs first. Promote a change only after matched production comparisons preserve accepted, packaged, production-rendered outputs. Keep the production renderer, source semantics, and exclusive GPU ownership.

**Tech stack:** Existing Python/SciPy fitting, Playwright renderer, GVHMR worker, Qwen review, PowerShell production runner and retained replay tools.

**Spec:** The active goal and Exercise Movement Generator Working Principles in `AGENTS.md`. This document governs the next experiments; the handoff is a short status index.

## Constraints and success measures

- The plan was delivered and the user activated its execution goal. Follow its bounds before each experiment.
- Optimize elapsed time to a good output, first packaged usable output time, and usable outputs per elapsed hour. Record acceptance and attempts alongside timing. Faster rejection alone is not success.
- Count startup, waits, retries, review and packaging. Cumulative concurrent job/request seconds are workload measures; they cannot be added to infer wall time.
- Keep thresholds, valid articulation/range, support geometry and temporal quality. Classify failures as justified rejection, processing bug, or insufficient evidence before changing behavior.
- Implement fixes in shared production owners and exercise them through the existing replay/harness. No exercise-name branches, fixed poses, or camera-specific tuning.
- Production and harness currently use Qwen. Keep that decision fixed during performance comparisons; no CLEF-to-Qwen fallback or new backend experiment is needed here.
- Use isolated worktrees/output directories and fixed input, contract, source-evidence and configuration hashes. Preserve unrelated workspace changes. Use the production CUDA Python interpreter for timing.
- Use RDL + OHP for iteration. Broader exercise reliability requires the risk-based family qualification below.
- Reuse existing tests. Add one focused regression only for an uncovered concrete defect/risk; run the smallest owning subset and compile edited Python once per combined change. Commit qualified production changes.

## Evidence and realistic improvement margin

Retained run roots: `build/exercise_motion/speed-harness/20261008-121537-bc560935/` (A) and `build/exercise_motion/speed-harness/20261008-122851-cb085986/` (B). Values below come from their `results.json` and A's RDL checkpoint.

| Observation | A | B | Interpretation |
| --- | ---: | ---: | --- |
| Total arm wall time | 735.3s | 780.2s | Different commits/configurations and different accepted output counts; not a controlled speed comparison |
| Source / generation / final phase | 190.832 / 219.592 / 290.369s | 201.549 / 172.951 / 360.510s | Final processing is the largest phase in both |
| Packaged accepted movements | 1/2, OHP only | 2/2, RDL + OHP | The faster arm did less successful work |
| Preview bake + fit cumulative job time | 402.808s, 2 jobs | 442.558s, 3 jobs | Includes fitting; not pure renderer cost or wall time |
| Reconstruction worker startup | 108.102s | 53.899s | Material setup cost with substantial variation |
| Vision startup, all sessions | 43.615s | 44.501s | Measured lifecycle cost; avoidability not established |
| Source review requests / cumulative time | 28 / 278.994s | 28 / 302.245s | Meaningful workload, but no duplicate requests established |
| Speculative render preparation | Disabled | 52.803s, abandoned for finalization | Actual unfinished/unused work; overlap may also contend with useful work |

A's RDL `qwen-full/isolated/exercise_motion/workspace/barbell-romanian-deadlift/bake/barbell-romanian-deadlift-001-yqbsqckhvtm/baked_stage_checkpoint.json` separates:

- Articulation fitting: **228.253s**; two solver attempt reports: **112.656s + 106.015s**. They fit different selected intervals, so this is not proof of duplicate whole fits.
- Browser startup + page ready: **2.540s**. Export: **1.752s**. Review render: **1.799s**. Browser reuse has much less measured margin than fitting.
- Both attempts ultimately rejected. Valid source/repetition phase does not prove that fitted anatomy, playback or seam will pass.

The latest matched retained production-bake replay is in `build/exercise_motion/diagnostics/rdl-report-alias-replay/`: parent 294.672s versus fixed 255.085s. Both required two attempts and passed the retained fallback; their joint coordinates differed by at most 0.583mm. One pair does not establish a repeatable improvement. The separate direct fitter replay did not exercise the repaired anatomy-report branch, so its timing difference cannot be credited to that fix.

## Ranked work

### 1. Controlled-fit initialization and repeated attempt work

**Priority:** Highest measured cost. Safely removable time is still unquantified; the 228s stage cost is an investigation budget, not a promised saving.

**Production owners:** `exercise_motion_pkg/controlled_motion.py::_fit_observed_cycles`, `fit_controlled_motion`; `articulation_trajectory.py`; source cycle proposal construction in `bake_and_rank.py`; existing candidate fit context/cache in `fit_runtime.py`.

**Relevant coverage/tools:** `tests/test_candidate_fit_session.py`, `tests/test_source_cycle_proposals.py`, `tests/test_controlled_motion.py`; `scripts/replay_controlled_motion_fit.py`, `scripts/replay_trajectory_fit.py`, `scripts/replay_baked_preview.py`.

- [x] Audit existing attempt/subphase reports and exact input identities. Separate anatomy/support initialization, residual/Jacobian computation, optimizer evaluations, final checks and repair. Check existing source/anatomy caches before proposing another cache.
- [x] Choose the largest proven repeated computation whose inputs and policy identities match across attempts. No uncached reuse across distinct RDL crop/full inputs was found; exact masks were the measured repeat work. Reuse only that computation in the shared production owner. Different crops, source bindings, contacts or budgets must invalidate reuse where they affect the result.
- [x] If no reusable work is demonstrated, inspect which subphase dominates and select one specific algorithmic optimization there. Do not start a collection of solver settings sweeps.
- [ ] Only if evidence shows a poor cycle attempt consumes time without progress, consider a bounded progress-based exit or narrower first-attempt budget. Preserve the retained-interval fallback and a passing source-cycle control. Current source preflight and endpoint gap alone do not justify skipping a fit.

**First experiment after review:** One retained-input baseline/candidate pair at the chosen subphase, with identical evaluation/budget policy. No discovery, VLM, reconstruction or unrelated render. If promising, run one reverse-order pair plus a passing source-cycle/OHP control. At most four timing runs for the primary input before a decision; no automatic retry.

**Keep only if:** Less measured computation and repeatable lower completed-fit time, unchanged fit/pre-render decisions, equivalent source articulation/support/temporal quality. Check the resulting production playback before claiming a usable improvement. Reject if the gain comes from dropping valid motion, bypassing a fallback, or moving a failure to a later gate.

### 2. Speculative render scheduling and CPU contention

**Priority:** A concrete 52.803s abandoned job exists in B. It overlaps generation; causal effect on the structural-fit timeout remains unproven. This is an independent bounded hypothesis, not evidence that prefetch should always be disabled.

**Owners:** `wave_pipeline.py::prepare_cpu_render_cache` and its submission/drain paths; `resource_budget.py`; `staged_wave_service.py`; `fit_runtime.py`. Coverage: `tests/test_wave_scheduling.py`, `tests/test_candidate_fit_session.py`, `tests/test_resource_budget.py`.

- [ ] Read retained timestamps to establish the exact overlapping jobs and whether the speculative result was consumed. Use process/thread attribution; host CPU samples alone cannot identify the culprit.
- [ ] If the overlap is confirmed, replay the captured RDL trajectory fit with and without the real OHP CPU preparation workload, holding fit inputs, native thread limits and deadline fixed. `scripts/replay_trajectory_fit.py` is the existing fitter entry; `prepare_cpu_render_cache` is the production competing workload.
- [ ] Use a small diagnostics-only adapter only if needed to reproduce that overlap. Ordinary `replay_baked_preview.py` does not exercise the wave prefetch switch; prepared candidates bypass CPU/network candidate prefetch, which is a separate feature.

**Experiment bound:** OFF / ON / OFF, one sequence, no model calls/reconstruction/downloads. Use the captured production fit budget and report preparation time, consumed/abandoned work, fit evaluations, timeout, gates and combined elapsed time.

**Decision:** If speculation repeatedly slows useful fitting or is predictably abandoned, adjust generic admission/cancellation in production, preserving cases where useful work is consumed. If the captured workload is not reproducible or no causal loss appears, defer this area. A faster fitted rejection still does not qualify promotion.

### 3. Reconstruction startup amortization

**Priority:** 53.899-108.102s measured startup versus only 2.441â€“3.838s reported prediction work across the pair. Prediction is only a subset of reconstruction; this does not mean all remaining reconstruction time is removable.

**Owners:** `wham_runner.py::ensure_warm_worker_ready`, `run_wham_with_warm_worker`; `gvhmr_warm_worker.py`; production PowerShell worker lifecycle. Coverage: `tests/test_wham_warm_worker_recovery.py` and existing worker ownership checks.

- [x] Inspect retained lifecycle events: container/process startup, import, checkpoint load, readiness, GPU acquisition, shutdown and existing warm-worker reuse. Determine whether the next request/wave can actually reuse this worker under exclusive GPU transitions.
- [ ] Propose a change only for a demonstrated redundant startup/load or avoidable restart. Do not enable GPU co-residency or retain models that must release memory for review.

**First experiment:** Initialization/readiness or loading-only replay with identical weights and lifecycle, followed by a second request to measure amortization. No full source pipeline. If output-affecting worker state changes, use one retained reconstruction and verify its downstream decisions before broader runs.

**Decision:** Keep only measured setup reduction with safe GPU ownership, cancellation/recovery and deterministic source handling. Defer if exclusive transitions require the same reload or benefit exists only in an artificial warm state.

### 4. Review call identity and model handoffs

**Priority:** Material workload; zero recorded question-cache hits does not prove a defect or duplicate calls.

**Owners:** Existing source/review question caches, vision-session lifecycle, `shared_llama_server.py`; `scripts/motion_speed_harness.py` supports serial `qwen-full` / `qwen-shared` arms.

- [x] Compare retained request identities and lifecycle events: exact images, prompts, contract, interval, model and policy. Distinguish independent evidence questions from exact duplicates.
- [ ] Fix only proven duplicate submissions or missing safe cache/coalescing reuse. Preserve source-semantic and final-render review requirements.
- [ ] Consider serial shared-server ownership only if a retained lifecycle trace shows an avoidable restart compatible with exclusive GPU handoff. Multi-wave overlap is a separate architectural change and is deferred.

**First experiment:** Reuse a retained exact request sequence; establish identical decisions and fewer actual calls/restarts. Run one baseline/candidate pair, with reverse order only if a promising timing benefit needs confirmation. Defer when no duplicate or avoidable lifecycle event is demonstrated.

### 5. Browser and source-frame extraction

**Priority:** Low additional margin on the current retained path. Browser frame batching is already enabled; source decode cache is on in A/B. The RDL browser-start/page-ready cost is only 2.540s.

- [ ] Inspect existing render/cache identities only if a trace shows duplicate content-identical rendering or decoding. Reuse `browser_workers.py` and `stage_cache.py`; do not introduce another renderer/cache framework.
- [ ] Any experiment must compare the same frames, timestamps, production renderer state and image bytes. Reject reuse that hides changed motion or stale source evidence.

No new browser worker-count or frame-batch sweep is scheduled. Revisit after larger costs are addressed or evidence shows a different workload dominated by rendering.

## Qualification and promotion

1. **Stage qualification:** A winning isolated change passes its owning gates and focused regressions. Retained-stage timing remains a stage result.
2. **Matched integration:** Only then run a matched production RDL/OHP pair with one changed variable, equivalent initial caches and pinned sources/contracts. Verify selection, actual package bytes, lineage and production playback against source. Record first usable output and total time. If promising, repeat in reverse order; stop and inspect any failure before rerunning.
3. **Risk-based family checks:** Use retained qualified sources for the specific behavior changed. Bilateral hinge/standing press are covered by the base pair; add only the exposed family initially: stationary supine/floor support (Floor Press), unilateral changing support (Step-Up), fixed-hand support/hanging, locomotion, or ballistic/multiphase motion (Box Jump). Equipment count/grip and oblique/moving-camera evidence are additional axes. A source-unqualified clip cannot validate the fitter; report that gap rather than weakening clearance.
4. **Fresh production promotion:** Before claiming a default improves the broad goal, representative fresh runs must show repeatable lower time to equally good accepted/packaged/rendered outputs. Fresh discovery is needed for discovery/semantic/cache changes; fit-only iteration reuses qualified sources until this final checkpoint. Ignore differences within observed run-order noise. There is no minimum percentage.

## Review focus

- Whole-interval phase fallback may still fail seam/anatomy: retain useful crop attempts and bounded fallback.
- Source/crop/contact changes can invalidate shared initialization: never reuse by exercise identity alone.
- Speculative work can help one schedule and starve another: measure consumed work and useful critical-path completion.
- Warm workers/caches can create misleading comparisons: match initial state and preserve exclusive GPU handoffs.
- Accepted diagnostics can contain earlier rejected variants: identify the selected packaged lineage and inspect its playback, not the union of candidate warning strings.

## Execution order and stop rules

- Finish this plan first. Next, complete the read-only fit-subphase audit; independent lifecycle and request-identity audits can run in parallel without running timing work.
- Select **one** hypothesis from the highest-priority area with demonstrated removable work. Record input hashes, intended change, skipped stages, metric, decision rule and runtime cap before launching it.
- Keep each timing comparison sequential and bounded as above. If its budget cannot discriminate a gain, report the limit instead of expanding it automatically.
- Maintain one short result per hypothesis: keep, reject or inconclusive, with evidence paths. No new full run to compensate for unexplained rejection; no repeated passing checks without changed evidence.
- Advance to the next ranked area when the current hypothesis is decided or its removable margin cannot be demonstrated. Reorder only when new evidence changes the expected value.
- Update the short handoff and commit only qualified changes. The broad goal remains unfinished until representative fresh quality and timing evidence satisfies it.

## Execution evidence — 2026-10-08

- Six bounded independent source/evidence audits completed. Exact crop/full-fit reuse is already implemented. Each retained wave already reuses one loaded reconstruction worker for two requests; exclusive final VLM handoff requires release. Review traces prove no duplicate requests or avoidable restart; per-call identity evidence is incomplete. Defer startup/review experiments.
- One fit callback profile exposed redundant `np.unique` over sparse dependency row IDs immediately before a same-value Boolean scatter. Removing deduplication preserves the mask for repeated/unsorted/empty indices. This is generic production fitting work, with no changed objectives/gates/settings.
- Retained117-frame mask A/B/B/A: baseline2.840/2.849s; candidate0.604/0.487s; every mask identical. This cost is incurred while populating the first-Jacobian mask cache, not on every later Jacobian evaluation.
- Complete Jacobian shape123363x7371:1,518,061 stored values; exact sparse difference zero. Profiled callback4.603s baseline/2.571s candidate is a single pair; use the balanced mask microbenchmark for repeatability evidence, not a claim of repeatable full-fit speed.
- Owning Jacobian and deadline tests:2 passed; production Python compilation and independent scoped review passed. Source input SHA256 and raw reports are in `build/exercise_motion/diagnostics/throughput_execution_20261008/` alongside `progress.md`.
- Change remains in isolated branch `experiment/motion-fit-throughput-20261008`; default promotion awaits representative accepted production-rendered/package comparisons. No generation/model calls occurred. Next: smallest matched production fit/bake comparison using qualified retained input, including OHP control; expand only for an exposed family risk. Do not rerun unchanged audits or microbenchmarks.


### Controlled-fit optimization check - retained RDL, 2026-10-08

The isolated branch `experiment/motion-fit-throughput-20261008` contains commit `ff857564`, which removes `np.unique` before a Boolean mask scatter in `hybrid_jacobian.pattern_joint_support`. The mask construction A/B/B/A preserved all three real RDL row masks and measured 2.840/2.849 seconds with deduplication versus 0.604/0.487 seconds without it. One complete profiled Jacobian measured 4.603 versus2.571 seconds; sparse matrix output matched exactly at1,518,061 values.

A four-run baseline/candidate/candidate/baseline fit comparison then used the same retained117-frame RDL input, the production CUDA interpreter and180-second fit limits. Every fit applied and passed all controlled-motion checks; all four output pose digests were identical. Mean reported fit time was61.327s baseline versus62.643s candidate (candidate +1.317s); mean launcher wall was63.588 versus64.895s. The per-pair direction reversed with run order. This shows timing is within larger run-to-run variation and does **not** establish a full-fit throughput improvement. Input/report: `build/exercise_motion/diagnostics/throughput_execution_20261008/retained_fit_ab_summary.json`.

The retained diagnostic input's source-cycle proposal was rejected as `selected_source_interval_source_evidence_incomplete`; the retained full interval passed. It has no complete source-captured/package lineage. This experiment qualifies controlled-fit check/output parity only. Do not promote the change to master or claim usable end-to-end throughput from it. The source change remains isolated for later disposition; don't repeat this four-run experiment.
