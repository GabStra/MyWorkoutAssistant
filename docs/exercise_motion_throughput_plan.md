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
| Speculative render preparation | Disabled | 52.803s OHP worker elapsed, abandoned for finalization | Abandoned work is observed; overlap with RDL finalization and any causal slowdown are unproven |

A's RDL `qwen-full/isolated/exercise_motion/workspace/barbell-romanian-deadlift/bake/barbell-romanian-deadlift-001-yqbsqckhvtm/baked_stage_checkpoint.json` separates:

- Articulation fitting: **228.253s**; two solver attempt reports: **112.656s + 106.015s**. They fit different selected intervals, so this is not proof of duplicate whole fits.
- Browser startup + page ready: **2.540s**. Export: **1.752s**. Review render: **1.799s**. Browser reuse has much less measured margin than fitting.
- Both attempts ultimately rejected. Valid source/repetition phase does not prove that fitted anatomy, playback or seam will pass.

The latest matched retained production-bake replay is in `build/exercise_motion/diagnostics/rdl-report-alias-replay/`: parent 294.672s versus fixed 255.085s. Both required two attempts and passed the retained fallback; their joint coordinates differed by at most 0.583mm. One pair does not establish a repeatable improvement. The separate direct fitter replay did not exercise the repaired anatomy-report branch, so its timing difference cannot be credited to that fix.

## Ranked work

### 1. Controlled-fit initialization and repeated attempt work

**Priority:** Highest measured cost: the accepted RDL's separate final controlled fit took 208s. Safely removable time is still unquantified; the 99s rejected cycle attempt is a lead, not a promised saving.

**Production owners:** `exercise_motion_pkg/controlled_motion.py::_fit_observed_cycles`, `fit_controlled_motion`; `articulation_trajectory.py`; source cycle proposal construction in `bake_and_rank.py`; existing candidate fit context/cache in `fit_runtime.py`.

**Relevant coverage/tools:** `tests/test_candidate_fit_session.py`, `tests/test_source_cycle_proposals.py`, `tests/test_controlled_motion.py`; `scripts/replay_controlled_motion_fit.py`, `scripts/replay_trajectory_fit.py`, `scripts/replay_baked_preview.py`.

- [x] Audit existing attempt/subphase reports and exact input identities. Separate anatomy/support initialization, residual/Jacobian computation, optimizer evaluations, final checks and repair. Check existing source/anatomy caches before proposing another cache.
- [x] Choose the largest proven repeated computation whose inputs and policy identities match across attempts. No uncached reuse across distinct RDL crop/full inputs was found; exact masks were the measured repeat work. Reuse only that computation in the shared production owner. Different crops, source bindings, contacts or budgets must invalidate reuse where they affect the result.
- [x] If no reusable work is demonstrated, inspect which subphase dominates and select one specific algorithmic optimization there. Do not start a collection of solver settings sweeps.
- [x] Audit the accepted RDL attempt sequence. The first source-preflight-valid cycle fit failed only after fitted anatomy/seam checks; the retained-interval fit reused 40 anatomy frames and shared support calibration. The exact prefit payload is absent, so no attempt-skip predictor can be evaluated on this fixture.
- [ ] Do not change attempt ordering, budgets, or fit reuse unless exact prefit captures across multiple qualified inputs demonstrate a predictive prefit signal and preserve a passing source-cycle case. Source-phase preflight and endpoint gap alone do not justify skipping a fit.

**Decision:** The 2026-10-08 bounded Run A replay captured the exact 117-frame object passed to `fit_controlled_motion`, proving the capture route works without discovery or reconstruction. Its raw/cleaned hashes differ from accepted Run B, and both fit attempts failed, so it is tooling validation only. Run B's prefit object is pruned; the recorded fit digest hashes the pre-transform payload and cannot establish equality with the fitter's `working` input. Do not repeat Run A or reconstruct Run B to manufacture a plausible substitute. Defer attempt-skip/budget changes unless a future quality-qualified accepted-stage capture provides the required identity and a predictive signal.

**Next action:** Continue with the next measured accepted production stage below. Preserve the captured Run A payload only as an exact replay fixture for fit diagnostics; it is not a quality or throughput baseline.

**First performance experiment, only after exact capture and a concrete predictor exist:** One retained-input baseline/candidate pair at the selected subphase, with identical evaluation/budget policy. No discovery, VLM, reconstruction or unrelated render. If promising, run one reverse-order pair plus a qualified source-cycle control. At most four timing runs for the primary input before a decision; no automatic retry.

**Keep only if:** Less measured computation and repeatable lower completed-fit time, unchanged fit/pre-render decisions, equivalent source articulation/support/temporal quality. Check the resulting production playback before claiming a usable improvement. Reject if the gain comes from dropping valid motion, bypassing a fallback, or moving a failure to a later gate.

### 2. Materialized selection and output acceptance

**Priority:** The accepted-output chooser/acceptance path took 47.519s for OHP in A, then 45.813s for OHP and 44.534s for RDL in B. This is stable elapsed time on three accepted outputs, but none of it is assumed removable.

**Production owners:** `bake_and_rank.py::choose_best_materialized_review_item`, `materialize_selection_candidate`, `apply_materialized_output_acceptance_gate`, `materialized_metrics_with_gpu_handoff`, and `final_output_validation_metrics`.

**Evidence:** `run.log` for A/B and B's `staged_wave_report.json` attribute the time separately from candidate processing, review ranking, manifest construction, and artifact retention. The saved selected-item reports provide nested timing: B RDL/OHP final visual review preparation was 24.163s/23.776s and final caption+parse was 6.562s/8.946s. A OHP's corresponding timings were 23.591s and 9.142s. Preparation includes the required two-scale source review as well as rendering, prompt/cache identity work and file hashing; it is not pure renderer time. B used four final-validation preview-sheet browser jobs totaling 16.678 job-seconds across both outputs; this is cumulative work, not wall time. The final-validation session made 22 Qwen requests totaling 181.672 request-seconds, also cumulative. Do not add these nested/concurrent values or credit them as removable savings.

The outer evidence capture and `validate_final_output_with_caption_images` both request the same materialized preview sheets; they use the same paths and cache identity, so the second call should reuse the render checkpoint. Do not treat that call pair as duplicate rendering. Source-clearance helpers also hash source inputs and frame evidence; measure file sizes and cache behavior before deciding that repeated hashes have meaningful cost.

**Completed diagnostic:** Profile root `build/exercise_motion/diagnostics/materialized_acceptance_profile_20261008/20261008T170817Z/`. Exact selected skeleton, source manifest, source video, and source-pose-reference hashes matched retained Run B. Source clearance reproduced `cleared` in 0.077s. Core deterministic metrics took 12.143s under cProfile; this includes about 5.47s of cold lazy imports. One 87-frame MediaPipe inference took 5.150s in the cold profile. No Qwen calls, contact-sheet rendering, or final-output validation ran.

The original selected review WEBM was pruned. After normalizing two file-path-only differences to their matching content hashes, omitting `exportedPreviewVideoQualityMetrics` and its derived `materialized_exported_preview_unreadable` rejection, and ignoring the private `_sourcePoseReference`, all 42 remaining gate fields match the retained accepted gate (`passed: true`, no core rejections). Video-quality parity remains unverified. The raw profile summary records a comparator mismatch because it failed to classify the missing-video rejection as derived from the excluded video metric; see `comparison_reconciliation.json` beside the profile output for the offline reconciliation.

**Measured repeated work:** Exact source validation had already analyzed the same clip hash (`b76c494e…01b48`) before materialization. A retained same-source replay, `build/exercise_motion/speed-harness/20261007-183657-ba82ab23/`, contains the same 248,485-byte landmark cache in both `segment_detection/pre_wham_source_candidates/deterministic_confirmation/source_candidate_A/foot_landmarks/` and `input/foot_landmarks/`; both cache files hash to `ED7F24F41B92DEE3EE49F3515DF7A67988134D2F65E76A8252CAB174E49B5D70`. Production copies the selected clip into `input/selected_segment.mp4` but leaves this adjacent cache behind. Since the cache defaults to `video_path.parent / "foot_landmarks"`, acceptance misses the preflight cache and reruns the 87-frame detector. `detect_for_video` accounts for 2.345s cumulative in the profile; use the paired wall-time result, not that profiler subcall, to decide whether the end-to-end saving is real.

**Next bounded experiment:** Use ignored local harness `build/exercise_motion/diagnostics/profile_materialized_acceptance_cache_ab.py`, invoked with `C:\Users\gabri\miniconda3\envs\mwa-motion-cuda\python.exe`. On the exact Run B OHP clip and skeleton above, generate a fresh preflight cache inside the isolated experiment using the current production interpreter/model configuration; do not seed the A/B from another run. Compare acceptance with its normal empty cache directory against the same acceptance with that same-process cache copied beside the materialized input. Warm imports on a disposable copy before timing, then keep one Python process/import state matched, run two sequential pairs in reverse order, and cap the whole replay at 120s. Require exact cache video hash and current model artifact/configuration, cache payload equality, zero `detect_for_video` calls in the cache-hit arm, identical deterministic metrics/decision after the same video-metric exclusion and path normalization, and a repeatable wall-time decrease beyond the observed timing spread. No source selection, Qwen, rendering, final-output validation, GPU inference, threshold changes, or full generation. The existing cache key hashes an explicitly configured model file but not the default model file, so keep cache reuse within this same run/configuration; do not broaden it to a persistent cross-run cache. The retained 2026-10-07 duplicate caches are evidence of the production path, not A/B inputs. Do not edit production until this passes; if it does, update the selected-source materialization path to carry the exact compatible landmark cache and add one focused regression.

**Keep a production optimization only if:** The profile identifies a concrete repeated or avoidable computation with measurable wall-time cost. Any isolated fix must preserve every deterministic metric and decision, then pass a matched accepted RDL/OHP production comparison with identical gates and rendered/package lineage. If the deterministic subphase is not a meaningful source of removable work, leave production unchanged and advance to the next evidence-backed area.

### 3. Speculative render scheduling and CPU contention

**Priority:** B records 52.803s of OHP speculative-worker elapsed before abandonment. The retained trace does not establish how much overlapped RDL finalization or caused slowdown. This is an independent bounded hypothesis, not evidence that prefetch should always be disabled.

**Owners:** `wave_pipeline.py::prepare_cpu_render_cache` and its submission/drain paths; `resource_budget.py`; `staged_wave_service.py`; `fit_runtime.py`. Coverage: `tests/test_wave_scheduling.py`, `tests/test_candidate_fit_session.py`, `tests/test_resource_budget.py`.

- [x] Read retained timestamps: OHP speculative preparation ran for 52.803s, then was abandoned for finalization; the worker drained. This is worker wall time, not CPU time or proven time saved/lost. The exact RDL-finalizer overlap and cause are unknown. `renderPrefetchWaitSeconds=0.0` for both exercises, so no finalizer wait was measured.
- [x] Verify exact retained pre-bake lineage in the 2026-10-08 12:28 run. `processing_evidence/motion.raw.json` and `motion.cleaned.json` match the generation checkpoint outputs. The selected HTML and wearable skeleton are post-bake and must not be reused. The exact source clips match the retained policy-v3 body-support observations. The matching cached WHAM outputs can regenerate the pruned retarget-source JSON without inference; the production preview writer can recreate the missing pre-bake HTML from the retained raw/cleaned clips.
- [x] Trace the production scheduling path: per-exercise finalizers run concurrently and abandon only their own unfinished prefetch before entering their priority context, so cross-exercise overlap is possible by control flow but was not established by the retained timestamps. Once speculative work reaches the fit slot, RDL priority makes it yield regardless of workspace. The retained launch used the `fast` profile: ranking off, adaptive settings on, maximum two variants, and six review frames (the wrapper's effective default). The original in-memory request was not retained.
- [x] Run the bounded replay through OFF1 and ON. OFF1 completed in 191.569s wall (112.172s process CPU); its RDL full-clip candidate passed the pre-render gate and had a review video. The detected 2.0s crop was correctly rejected. ON hit the external 300s cap, so OFF2 was not run and no OFF/ON comparison is valid.
- [x] Correct the RDL replay inventory before timing: the retained 2.0s detected crop was rejected in the selected production run; the full 117-frame candidate remained the selected fallback. Pass the complete production eligible-loop inventory so the comparison includes that full-clip path. A cycle-only replay would measure a fast rejection, not useful output.
- [x] Use base preview settings and full eligible RDL inventory. The replay starts after production generation, so its retained checkpoint-identical cleaned motion and regenerated pre-bake preview are stage inputs; it does not measure raw-to-clean generation. Seed only source-hash- and policy-matched support observations. Count an RDL result as usable only when a pre-render gate passes and its review video exists.
- [x] Add append-only, flushed event telemetry and run one bounded diagnostic ON arm (`runs/20261008T143015Z-359d45/on/live_events.ndjson`). OHP acquired its fit slot at 25.910s, yielded under RDL priority, and exited as abandoned at 44.148s. RDL's browser job started at 31.123s and acquired CPU admission at 31.336s; its fit-slot wait began at 49.491s and acquired immediately at 49.494s. No fit-slot release or RDL artifact appeared before the external kill at 300s. A mid-run process sample showed CPU time increasing, so this was active compute at that point, not an admission wait.

**Experiment bound and result:** The first sequence stopped after ON timed out at 300s; OFF2 was intentionally omitted. One fresh diagnostic ON arm with live telemetry also reached the external 300s cap. The timing arms made no LLM review calls, reconstruction calls, or downloads. Fresh fixture setup took about 68s, revalidated retained input/support evidence, and emitted local TensorFlow Lite logs; that setup is outside the timed arm and should not be repeated for this hypothesis. The external cap is below the 360s candidate-fit budget, and it killed RDL while that fit slot remained held. This explains the replay timeout as a harness bound; it does not establish a production deadlock or prove that OHP prefetch caused the long fit. No OFF/ON performance comparison is valid.

**Decision:** Defer production scheduling changes. The forced replay showed no browser scheduler or fit-slot admission delay, but it did not measure whether speculative work slowed the subsequent fit. Do not run OFF2 or repeat this replay without new production evidence or a diagnostic that can distinguish a specific cause inside the 300s cap. A faster fitted rejection still does not qualify promotion.

### 4. Reconstruction startup amortization

**Priority:** 53.899-108.102s measured startup versus only 2.441-3.838s reported prediction work across the pair. Prediction is only a subset of reconstruction; this does not mean all remaining reconstruction time is removable.

**Owners:** `wham_runner.py::ensure_warm_worker_ready`, `run_wham_with_warm_worker`; `gvhmr_warm_worker.py`; production PowerShell worker lifecycle. Coverage: `tests/test_wham_warm_worker_recovery.py` and existing worker ownership checks.

- [x] Inspect retained lifecycle events: container/process startup, import, checkpoint load, readiness, GPU acquisition, shutdown and existing warm-worker reuse. Determine whether the next request/wave can actually reuse this worker under exclusive GPU transitions.
- [x] Propose a change only for a demonstrated redundant startup/load or avoidable restart. The retained runs start one worker for two requests; final VLM requires the GPU handoff. The 53.899s/108.102s cold-load spread is unattributed, not proof of removable work. No lifecycle change is justified.

**First experiment:** None is currently justified: the worker already loads once for both requests and stops for the required final VLM handoff. Revisit only if new traces identify a redundant load subphase or unexpected restart.

**Decision:** Keep only measured setup reduction with safe GPU ownership, cancellation/recovery and deterministic source handling. Defer if exclusive transitions require the same reload or benefit exists only in an artificial warm state.

### 5. Review call identity and model handoffs

**Priority:** Material workload; zero recorded question-cache hits does not prove a defect or duplicate calls.

**Owners:** Existing source/review question caches, vision-session lifecycle, `shared_llama_server.py`; `scripts/motion_speed_harness.py` supports serial `qwen-full` / `qwen-shared` arms.

- [x] Compare retained request identities and lifecycle events: exact images, prompts, contract, interval, model and policy. Distinguish independent evidence questions from exact duplicates.
- [ ] Fix only proven duplicate submissions or missing safe cache/coalescing reuse. Preserve source-semantic and final-render review requirements.
- [ ] Consider serial shared-server ownership only if a retained lifecycle trace shows an avoidable restart compatible with exclusive GPU handoff. Multi-wave overlap is a separate architectural change and is deferred.

**First experiment:** Reuse a retained exact request sequence; establish identical decisions and fewer actual calls/restarts. Run one baseline/candidate pair, with reverse order only if a promising timing benefit needs confirmation. Defer when no duplicate or avoidable lifecycle event is demonstrated.

### 6. Browser and source-frame extraction

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

- The read-only fit, reconstruction-lifecycle and request-identity audits are complete. The sparse-mask optimization preserved outputs but did not produce repeatable full-fit savings. The structural-fit profile and follow-up screens are recorded below; no production throughput change has qualified.
- The scheduling diagnostic found immediate CPU and fit-slot admission, followed by an RDL fit that remained active when the 300s harness cap killed it. Since the cap is below the 360s fit budget and OFF2 was omitted, this hypothesis has no valid timing conclusion; defer it.
- The RDL lineage question is resolved below. Do not treat the rejected `x_scale="jac"` postprocess as a production regression or rerun a unit-scale control: it stops at a different stage from the accepted cyclic-rebake output.
- Controlled-motion fitting remains the largest single measured cost, but no safe attempt reuse/skip is supported. Run A capture validates the exact capture boundary only; accepted Run B prefit identity is not recoverable. The bounded selection/acceptance profile now matches the retained deterministic gate; test only the measured source-landmark cache duplication in section 2.
- Choose a new performance hypothesis only when retained evidence shows removable work or a concrete algorithmic mechanism. Record input hashes, intended change, skipped stages, metric, decision rule and runtime cap before launching it.
- Keep each timing comparison sequential and bounded as above. If its budget cannot discriminate a gain, report the limit instead of expanding it automatically.
- Maintain one short result per hypothesis: keep, reject or inconclusive, with evidence paths. No new full run to compensate for unexplained rejection; no repeated passing checks without changed evidence.
- Advance to the next ranked area when the current hypothesis is decided or its removable margin cannot be demonstrated. The current bounded test is limited to reusing hash-identical source landmarks during materialized acceptance. If it does not beat timing spread with exact metric parity, leave production unchanged and move to the next evidence-backed stage.
- Update the short handoff and commit only qualified changes. The broad goal remains unfinished until representative fresh quality and timing evidence satisfies it.

## Execution evidence — 2026-10-08

- Six bounded independent source/evidence audits completed. Exact crop/full-fit reuse is already implemented. Each retained wave already reuses one loaded reconstruction worker for two requests; exclusive final VLM handoff requires release. Review traces prove no duplicate requests or avoidable restart; per-call identity evidence is incomplete. Defer startup/review experiments.
- Current-state audit found selection/acceptance at 44.534–47.519s on three accepted outputs. B's nested visual review records 23.776–24.163s preparation and 6.562–8.946s final caption+parse; preparation includes source validation, not just rendering. The retained selected items use the same skeleton as the sole ranked item, with no selected-range cut or rescore. The original review video is missing, so its quality metric remains unverified; the deterministic profile result is recorded in section 2.
- One fit callback profile exposed redundant `np.unique` over sparse dependency row IDs immediately before a same-value Boolean scatter. Removing deduplication preserves the mask for repeated/unsorted/empty indices. This is generic production fitting work, with no changed objectives/gates/settings.
- Retained117-frame mask A/B/B/A: baseline2.840/2.849s; candidate0.604/0.487s; every mask identical. This cost is incurred while populating the first-Jacobian mask cache, not on every later Jacobian evaluation.
- Complete Jacobian shape123363x7371:1,518,061 stored values; exact sparse difference zero. Profiled callback4.603s baseline/2.571s candidate is a single pair; use the balanced mask microbenchmark for repeatability evidence, not a claim of repeatable full-fit speed.
- Owning Jacobian and deadline tests:2 passed; production Python compilation and independent scoped review passed. Source input SHA256 and raw reports are in `build/exercise_motion/diagnostics/throughput_execution_20261008/` alongside `progress.md`.
- Change remains in isolated branch `experiment/motion-fit-throughput-20261008`; default promotion awaits representative accepted production-rendered/package comparisons. No generation/model calls occurred. The later speculative-scheduling replay and its limits are recorded in section 2; do not repeat unchanged audits or microbenchmarks.
- Accepted Run B OHP materialized-acceptance profile: deterministic fields match the retained gate after normalizing the selected-source and pose-reference paths by their verified hashes and excluding only the missing review-video metric plus its derived rejection. Source clearance matched. The cold profile took 12.143s (5.47s cold lazy imports); its 87-frame landmark observation took 5.150s. Full raw evidence is under `build/exercise_motion/diagnostics/materialized_acceptance_profile_20261008/20261008T170817Z/`; comparator reconciliation is separate because the raw summary treats the excluded video-derived rejection as core.
- A retained 2026-10-07 OHP replay contains two byte-identical, 248,485-byte MediaPipe caches for the same clip: one beside deterministic-confirmation input and one beside materialized `input/selected_segment.mp4` (cache SHA256 `ED7F24F41B92DEE3EE49F3515DF7A67988134D2F65E76A8252CAB174E49B5D70`). The production copy changes parent directory without carrying the cache. Next: run the section 2 isolated A/B, generating a fresh same-process cache under the current model, with a 120s total cap, exact gate parity, and zero detector calls for cache hits; no Qwen, rendering, full replay, or production edit until timing beats spread.


### Controlled-fit optimization check - retained RDL, 2026-10-08

The isolated branch `experiment/motion-fit-throughput-20261008` contains commit `ff857564`, which removes `np.unique` before a Boolean mask scatter in `hybrid_jacobian.pattern_joint_support`. The mask construction A/B/B/A preserved all three real RDL row masks and measured 2.840/2.849 seconds with deduplication versus 0.604/0.487 seconds without it. One complete profiled Jacobian measured 4.603 versus2.571 seconds; sparse matrix output matched exactly at1,518,061 values.

A four-run baseline/candidate/candidate/baseline fit comparison then used the same retained117-frame RDL input, the production CUDA interpreter and180-second fit limits. Every fit applied and passed all controlled-motion checks; all four output pose digests were identical. Mean reported fit time was61.327s baseline versus62.643s candidate (candidate +1.317s); mean launcher wall was63.588 versus64.895s. The per-pair direction reversed with run order. This shows timing is within larger run-to-run variation and does **not** establish a full-fit throughput improvement. Input/report: `build/exercise_motion/diagnostics/throughput_execution_20261008/retained_fit_ab_summary.json`.

The retained diagnostic input's source-cycle proposal was rejected as `selected_source_interval_source_evidence_incomplete`; the retained full interval passed. It has no complete source-captured/package lineage. This experiment qualifies controlled-fit check/output parity only. Do not promote the change to master or claim usable end-to-end throughput from it. The source change remains isolated for later disposition; don't repeat this four-run experiment.

### Structural-refinement profile and bounded follow-ups - 2026-10-08

The retained 117-frame RDL postprocess profile took 80.801s, including 71.451s in structural refinement. Profiling attributes that cost to `_align_body_to_source_pose` and its trajectory fit. Although the profile reports five `least_squares` calls, only one was the expensive trajectory solve (~53.386s); the other four were tiny camera-registration fits (~0.027s combined), so this is not evidence of repeated full solves. The trajectory fit used 69 Jacobians, 108 color groups, 8,424 variables and 7,535 residual evaluations. The source-preserving acceptance checks cover distinct proposals; no safe duplicate check or solve was identified.

Two exact-pattern coloring screens kept all 108 valid groups: descending column nonzero count and descending distinct-conflict degree. The pattern was 31,491 x 8,424 with 734,451 nonzeros. Neither screen invoked the optimizer, so no fit replay is justified by coloring.

The retained accepted production run B reports RDL/OHP structural-refinement stages of 66.805s/37.275s. Its captured RDL source-guided fit ran 60.016s, hit `time_limit`, and was not applied; the OHP fit ran 34.922s, reached its 80-evaluation limit, and was applied inside an outer selection that ultimately chose the cyclic rebake. These are distinct exercise outcomes, not evidence for reusing one result across them.

An isolated `x_scale="jac"` RDL postprocess replay on run B's retained input took 30.525s overall (28.658s structural refinement; 24.547s trajectory fit). The fit applied after 80 evaluations and reduced its reported objective from 151,166 to 3,725, but postprocess diagnostics failed `root_translation_discontinuity`, `physical_pose_constraint_violation`, and `limb_velocity_spike_penalty`. This is not an accepted or packaged output and is not a production timing win.

The direct same-input fitter A/B, repeated in reverse order, consistently favored Jacobian scaling by only 0.669-1.401s per fit (unit: 27.719s/27.409s; Jacobian: 26.318s/26.740s). Both arms stopped at the same 80-evaluation limit; the Jacobian arm had a modestly lower objective and source-target RMS, but produced a different pose (maximum coordinate delta 3.80cm). The downstream replay failure means this fit-only edge does not qualify as equal-quality throughput.

A missing-camera preflight candidate rejected the stripped diagnostic interval before anatomy initialization, but the retained accepted RDL and OHP artifacts have source camera references. No qualified production incidence was found, so keep that change isolated and do not promote it.

**Decision:** No change from this batch qualifies for production. The accepted package is a terminal `cyclic_rebake` with complete lineage and a passing pre-render gate. Its separate final `controlledMotionFit` was applied and passed all checks. The earlier unit-scale source-guided trajectory fit timed out and was discarded. The isolated `x_scale="jac"` replay applied a different fit but failed three diagnostics at postprocessing, so it neither explains nor contradicts the accepted production output. Do not launch another solver sweep or a full generation run to reconcile these distinct paths.

### Accepted RDL controlled-fit attempt audit - 2026-10-08

The accepted run B RDL artifact records a separate final controlled fit lasting 208.266s. The first attempt was the only source-preflight-valid cycle proposal: full interval `[0,117)`. Source phase preflight passed, but its fitted candidate took 99.078s and failed anatomy (`anatomy_torso_bend`) and `loopSeam`; its anatomical initialization itself passed. The retained-interval fit then took 108.922s and passed. The two attempts use different fit modes and endpoint constraints, so the failed candidate cannot safely stand in for the retained fit.

The second attempt reused the 40 cached anatomy-repair frames, and support calibration is already shared. This rules out the obvious repeated-initialization opportunity. Source-only preflight cannot predict the observed fitted anatomy or seam failures, and one failure does not satisfy the existing generic stop guards. The 99.078s is a measured failed-attempt cost, not a qualified removable saving.

The exact enriched skeleton entering this controlled fit is absent from retained run B: only raw/cleaned motion, source evidence, the final cyclic-rebaked skeleton, and attempt summaries/digests remain; the original bake workspace and pre-bake payload were pruned. `replay_controlled_motion_fit.py` on the final artifact would start from already fitted/rebaked poses, while the other replay routes would regenerate a non-identical upstream payload. Neither can reproduce this attempt faithfully.

**Decision and next step:** No code or fit-budget experiment is justified from this artifact. Run B's exact pre-controlled-fit payload is pruned, and Run A is not a valid substitute. Defer fit-attempt changes. The bounded deterministic selection/acceptance profile is complete; the next action is the cache-sharing A/B in section 2. Preserve the existing anatomy, seam, fallback, and packaging gates.
