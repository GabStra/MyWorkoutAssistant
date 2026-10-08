# Exercise movement generator: remaining throughput work

Prepared 2026-10-02. This plan defines the remaining implementation, measurements, and conditions for changing production defaults.

## Objective and decision rules

Increase usable, production-rendered movements per elapsed hour and reduce time to the first usable movement. Preserve exercise identity, valid motion range, articulation, support geometry, temporal quality, and the current acceptance gates.

- Primary metric: production-accepted outputs that also pass rendered-playback review / total arm wall time. Include startup, queueing, retries, rendering, validation, and materialization in that time.
- Also report first usable output time, candidate attempts per accepted output, acceptance rate, manual-review count, phase intervals, model calls, cache hits, and CPU/GPU/VRAM high-water marks.
- If an arm produces zero usable outputs, report zero usable throughput. A faster rejection is diagnostic evidence, not an optimization success.
- Treat fixed-source processing, cached resume, and discovery-inclusive generation as separate measurements. Phase totals can overlap and must not be added to infer wall time.
- A 10% repeatable wall-time reduction at unchanged usable output is the practical promotion threshold for this plan, not a predicted speedup. Smaller or noisy gains do not justify more orchestration complexity.
- Run timing comparisons sequentially under the production Python environment. Hold model, model files, inference settings, contracts, policies, renderer, candidate inventory, and initial cache state fixed except for the named variable.
- Use the agreed Dumbbell Overhead Press + Barbell Romanian Deadlift pair for iteration. Do not substitute the older provisional Step-Up pair.
- Initial two-exercise arms have a 45-minute wall limit. Stop after a failed qualified-source replay and inspect the owning layer; permit one rerun after a concrete fix. Do not regenerate until a pass appears.

## Current state

Already present in the checkout:

- Sparse-Jacobian zero removal in `articulation_trajectory.py`.
- Conservative conclusive-question reuse across source-review contexts.
- Speculative CPU bake submission only while reconstruction remains unfinished.
- A four-slot CPU fit pool, up to six source-validation lanes, and a warm reconstruction-worker path.
- Optional shared llama ownership and optional two-wave admission in the normal PowerShell scheduler.

The current library wrapper uses wave size 8 and partial-wave wait 300 seconds. The workout-plan runner defaults to one active staged wave. Two-wave admission requires shared llama and only occurs while every active wave reports `final_validation` and the other admission conditions pass. This checkpoint includes final VLM work; it does not imply that the GPU is free for all operations.

The speed harness now exposes wave size/wait, preserves unsuccessful artifacts, remaps copied workspace references, and gives each arm an isolated WHAM cache. Its default exercise pair remains a smoke pair; the fixed v4b pair below is the measured fixture. Older harness results may contain shared-cache or absolute-path contamination.

Latest current-policy run is `build/exercise_motion/speed-harness/20261008-floorpress-policy62/`: source review passed 1/1, but output acceptance was 0/1 after 212.112s of preview bake/fit and support/endpoint rejection. This is a fixed candidate, not fresh discovery or a throughput result. The retained v4b Qwen pair is policy61: OHP is visually usable, while RDL remains pending source-projection fidelity, so it is not a current-policy usable-throughput control. Keep source-frame caching off; its latest paired wall gain was 1.3% and not repeatable.

The 2026-10-08 migration audit found artifact-state lineage and fit-source evidence are already enforced in production; guarded legacy compatibility is not the measured bottleneck. The staged service is a single inline queue consumer under process-wide stdout/stderr redirection, and the PowerShell runner clamps active waves to one. GPU/server ownership guards exist, so removing only the clamp would not make overlapping waves safe. Production review and the harness are now Qwen-only; the harness has `qwen-full` and `qwen-shared` serial arms, neither yet qualified or measured on current-policy outputs.

The retained Floor Press fitter input A/B is recorded in `build/exercise_motion/diagnostics/floorpress_support_polish_ab_20261008/experiment_summary.json`. The same 114-frame input and source-evidence digests were used at `f3814659` and `c703059a`, with one main solver evaluation, no model calls, and no reconstruction. Both runs passed the support-contact and anatomy gates; the old path performed a no-op contact projection at 0.217 mm, while the fixed path skipped it. The capped solver later failed playback/source-support checks, so neither run produced a usable movement. The original production failure recorded a 0.611 mm pre-projection contact error and a 32.605 mm right-ankle anatomy residual, but its transient fit-input digest differs from the retained fallback replay. Treat the A/B as confirmation of the skipped no-op path, not an exact reproduction or a throughput result.

The later 184-second `full-fit-current` replay is not a valid production comparison: the replay script treated the contract-cache envelope as the contract, so it missed the return-to-start policy and fitted the noncyclic full clip. The replay loader now unwraps cached contracts. A 0.313-second, model-free preflight with the corrected loader finds the source-confirmed `[35,104)` cycle; the actual production run already attempted that cycle and rejected it on strict fit/playback checks. See the handoff for the recorded failure evidence. No throughput gain or accepted Floor Press output is established.

The isolated browser-render A/B in `20261007-191208-5ffb3392/qwen-full/render_reconfigure_ab.json` produced byte-identical PNGs and matching sampled renderer states. Batching cut the 119-frame RDL render from 16.019s to 5.957s and the 85-frame OHP render from 9.038s to 3.840s. This is a measured render-stage saving, not an end-to-end throughput claim; browser frame batching is enabled by default in production, with `EXERCISE_MOTION_BROWSER_FRAME_BATCH=off` available for the legacy path.

A pre-fix fresh-discovery attempt routed a Floor Press plan under the Step-Up output key and was aborted. The filter fix is committed as `a151da7b`, with 8 focused tests and exact exercise-ID checks passed. This repairs the routing defect; fresh source/family qualification remains separate work.

### Current fixture audit — 2026-10-07

The current source-ready pair is pinned in `build/exercise_motion/throughput_goal_fixtures_20261007_v4b/fixture_manifest.json`:

| Exercise | Exercise ID | Video ID | Fixed source | SHA-256 |
| --- | --- | --- | --- | --- |
| Dumbbell Overhead Press | `4f86a919-b6bf-51ec-afac-c61750b690f3` | `fsc8jcupgtk` | `https-www.youtube.com-watch-v-fsc8jcupgtk-standard-f9e26804454064c2.mp4` | `b76c494eb6ec44b3c16f4f27e1526d1274d3969f81d0bba2a70eeecda9b01b48` |
| Barbell Romanian Deadlift | `03b68a7c-fa03-57e2-b6d8-63092a6091ab` | `yQbSQCkhvTM` | `https-www.youtube.com-watch-v-yQbSQCkhvTM-standard-be008f80035b3f29.mp4` | `9974382fe00395022f2586fb9c2fa311b3c9a13bb073599f7c7a47bd6d195bde` |

V4b pins both genuine policy30 contract bodies generated by normal production prefetch, actual library exercise IDs and current equipment capabilities. The actual mini-library model-free preflight returned 2/2 reused contracts with exact context matches. See its model_free_cache_preflight.json receipt. Source/candidate bytes match v3; copied quality references remain historical. The 204724/210427 source61 pair validates both current sources and package bytes; see the current comparison receipt above. Automated approval is not sufficient to promote a throughput result while RDL source-projection fidelity remains pending.

The v3 fixture failed actual-plan cache qualification in `speed-harness/20261007-170052-c3fb29e6`: the real mini-library adds authoritative primary-equipment capabilities absent from its old seeded contexts, so both contracts were regenerated. The owned run was stopped and is not a comparison arm. Preserve its two genuine policy30 contracts for a new fixture and validate against the actual mini-library before launching models. The v2 fixture remains historical, with policy-29 contracts.

`fresh_inference_pair_20261007/fresh_production_pair` ran fresh WHAM inference and production review/package checks, accepting both pinned sources, but skipped source-segment detection and did not measure discovery. The normal fixed-source harness run `speed-harness/20261007-092322-d271b71b` ran the prepared candidates with source-segment detection and accepted 0/2. Keep that failed arm as diagnostic evidence; it is not a qualified successful throughput fixture.

In the failed arm, both source and raw-motion gates passed, then the independent pre-render gate rejected the fitted outputs. OHP's controlled fit failed `rootTravel` after five evaluations; stationary-foot range was 48.6mm and maximum support-surface error was 54.6mm against a 5mm tolerance. Its fitted root range was 34.47mm versus a 42.25mm source target (0.816 preserved; 3.55mm shortfall). The accepted fit preserved 0.879 of its 42.23mm target and passed within the 1mm preservation tolerance (0.88mm shortfall). After undoing the accepted output's recorded scene-placement translation, its 83 frames of `sourceJoints` match the failed fit input to floating-point precision. Thus the pre-fit motion coordinates match, while the root-travel outcome differs.

The successful fresh-inference OHP has the same source MP4 hash and identical 87-frame raw WHAM joint coordinates, but a different fit-input pose digest and passed support error at 0.04mm. The failed path also records `exact_pre_wham_return_cycle_validated`, while the successful replay skips source-segment detection. Both exact source-pose references cover 22 samples from 0.0–2.8 seconds and map to the same 0.0–2.9 second interval, but the accepted reference is bound to the original source hash while the failed reference is bound to the re-encoded selected clip; its pose samples are close but not identical. Source-pose/support swap diagnostics on the saved failed artifact remained rejected (the corrected camera-reference swap measured 34.29mm root range, 0.812 preserved, 3.74mm shortfall), but this artifact is only the fallback pre-fit payload: the production pipeline constructs a separate in-memory `working` payload before `fit_controlled_motion`, and the optimizer coordinates are not retained on rejection. Treat the swaps as directional diagnostics, not exact-input fit comparisons or proof of the remaining cause.

The code-level OHP owner was an objective/validator mismatch: `controlled_motion.py` scored supported pelvis tracking as a soft target, but the fit residual had no explicit root-span preservation term; the validator separately required 90% of target root travel, with 1mm slack. The captured 83-frame fitter input (pose digest `0ce3b64a…379c1e`, source-evidence digest `0b37d8a5…402f993`) failed direct replay at 80.01s with 34.90mm fitted root range (0.826 preserved; 3.13mm shortfall). Adding a generic one-sided root-span residual to the same fit objective, while keeping all validators unchanged, now passes that exact input: `root_span_candidate_report.json` records 67.17s, 27 evaluations, 38.03mm fitted root range (0.90023 preserved), and every controlled-motion check true. More decisively, replaying the failed OHP bake manifest through the production preview path with the new objective (zero model calls, zero reconstruction runs) fit the failed candidate's 83 frames (pose digest `b320493e…1beb054`) in 109.10s, passed root travel at the same 0.90023 ratio, playback, support geometry, and the pre-render gate. Visual review of that rendered contact sheet found the same press motion as the accepted reference. This establishes the OHP failure mechanism and a bounded fit/pre-render correction for the actual failed bake input. The full two-exercise package/review replay has not yet been repeated with this code, and the change does not address RDL.

RDL's saved controlled fit ends `playback_validation_failed`. The ranked subinterval [22,104) is rejected as a one-way partial repetition; the full [0,117) interval passes source-phase checks but is not spatially closed (65.14mm right-hand, 49.84mm pelvis, and 38–44mm foot endpoint gaps). The cyclic fit fails anatomy/seam validation. The open retained-interval fit passes most body checks but fails playback: internal knot velocity jump 0.1149m/s; wrap seam position jump 31.45mm, 29.40mm beyond a 3.13mm limit; seam velocity mismatch 0.940m/s against 0.195m/s. Plant/grip repair leaves velocity failing. The velocity repair raises contact error from 2.16mm to 216mm and jerk RMS from 0.00352m to 0.08313m, so it is rejected by existing gates. The pre-render gate separately reports a left-foot discontinuity at frame 108 / 3.6s (0.03493 body-height ratio vs 0.03), root second difference 42.83mm vs 39.07mm, and support range/surface errors 102.76/114.13mm vs 5mm. `loopTransition=requires_cycle_repair` is a seam diagnostic; the rejected retained-interval fit was not applied and the saved artifact has `loop.enabled=false`. No safe generic repair is justified by this artifact. The source MP4 hash and selected interval (0.0–3.9 seconds) match, but failed and successful retained RDL replays use different raw motion (SHA prefixes `c1fc68ff` and `433ac79b` respectively). The successful run's prepared inference clip was not retained, so the first upstream divergence cannot be isolated. Cold/warm mode is ruled out for the failed input by the byte-identical reconstruction replay below. The root-span objective is inactive for RDL because its root travel already passes; do not relax seam, velocity, contact, or source-phase gates.

A controlled replay of the failed run's retained 117-frame sanitized input (`00a4a2c8…9f9cd4`, 669,469 bytes, read-only copy) produced the same exported `wham_output.pkl` hash through one-shot Docker and the warm worker; both also match the failed harness artifact byte-for-byte, including pose and translation arrays. Their materialized `0_input_video.mp4` hashes match. One-shot reported 150.43s script time (82.27s preprocessing, 2.90s prediction); the warm request took 15.93s (14.02s preprocessing, 1.12s prediction), plus a 24.81s worker load. This rules out cold/warm execution as the cause of failed RDL motion for this exact input, but cannot explain the accepted-run divergence because its prepared input is missing. In fact, the successful retained replay imports a different raw-motion JSON (`433ac79b…7f561e`) than the failed harness (`c1fc68ff…f00e89`); the first retained divergence is upstream at raw WHAM coordinates, and the successful run's prepared inference clip is unavailable, so its cause remains unresolved. The failed RDL fit's owning rejection is downstream playback validation: its cycle seam jumps 31.45mm (29.40mm beyond the 3.13mm limit) and velocity mismatch is 0.940m/s (above the 0.195m/s limit), with `loopTransition=requires_cycle_repair`. These are reconstruction-stage measurements; RDL still fails playback and pre-render quality gates, so they are not usable end-to-end throughput.

The original normal-path RDL source divergence is now traced one stage earlier: exact-pose confirmation called `materialize_source_cut_candidate_for_exact_validation()`, which always transcoded the selected [0.0, 3.9]s full-source interval; the deterministic-selection branch then copied that altered file. The failed selected clip was 237,721 bytes (SHA `bec2377e…d7cc7a`) versus the 302,969-byte source (SHA `9974382f…d195bde`), while the successful selected clip matched the source bytes. The RDL root-span retained replay cannot confirm this fix because it skips source-segment detection. The earlier root-span retained replay's seam regression was also not caused by that objective: its RDL fit took the existing `supported_geometry_ready` soft-solve skip (`evaluations=0`), whereas the prior run evaluated the solver 30 times; source-evidence digests differed, and the retained inputs lacked the exact prefit payload for a clean comparison. The exact-confirmation materializer now uses the shared full-range copy/partial-window trim path, bumps confirmation policy 23 to 24, rejects stale materialization metadata, and records the selected materialization in the segment manifest. Focused materialization/selection tests pass, and a direct call on the pinned RDL source confirms matching source and output SHA `9974382f…d195bde`. The subsequent normal-path replay below verifies the fix on both exercises; it does not establish a repeatable broad throughput gain.

### Post-fix pair replay — 2026-10-07

The bounded baseline arm `speed-harness/20261007-122540-483b2cad` reran the same two pinned prepared fixtures through normal source detection with policy 24 and the root-span fit objective. Both exact-confirmation candidates were `source_copy_full_range`, and their hashes matched the pinned RDL and OHP source hashes. Both exercises completed, passed `is_approved_summary_item`, retained production-rendered previews, and were included in a package whose compressed movement bytes matched the reviewed selected JSON and whose packaged artifact-state lineage validated. I inspected both final-render contact sheets: the RDL shows the down-and-return hinge cycle, and the OHP shows the press and controlled lowering. RDL root travel preserved 0.981 of target; OHP preserved 0.912, both above the 0.90 gate. Arm runtime was 735.2s; the harness separately spent 134.9s on GVHMR prewarm, for 870.1s command-to-output and about 8.3 approved packaged outputs/hour on this fixed pair. The prior run took 815.1s but accepted 0/2, so this demonstrates recovery on the pair, not a repeatable 10% throughput gain. The successful arm used configured wave size 8 (one actual wave of two items), while the failed arm used size 1; that scheduler difference also prevents attributing elapsed-time changes to the root fixes. The fresh RDL raw-motion hash (`6765a168…e8d34`) still differs from the earlier accepted retained replay (`433ac79b…7f561e`); the normal-path output now passes despite that difference. Keep the broader throughput goal active until a controlled repeat and stratified exercise-family confirmation establish the required general gain.

Historical run `9dcc77393c744c62a548c165cb05768b` identifies scheduling opportunity, not a speedup estimate: queued work was held while wave 5 spent approximately 6m34s in final validation, and wave 7 provides another approximately 4m06s interval. At least one partial wave started about 302 seconds after the first visible ready item. Other inter-wave gaps include discovery and preparation.

## 1. Build and qualify fixed source inputs

Files to work in: `scripts/motion_speed_harness.py`, the existing staged-manifest CLI, and the discovery-resume path in `scripts/run_exercise_motion_workout_plan.ps1`.

- [ ] Record the agreed pair explicitly in a fixture manifest. Preserve the original exercise IDs, equipment, exercise contracts, and motion context.
- [ ] Retain these exact source identities and original exercise IDs:

| Exercise | Exercise ID | Video ID | Full cached source |
| --- | --- | --- | --- |
| Dumbbell Overhead Press | `dumbbell-overhead-press` | `fsc8jcupgtk` | `build/exercise_motion/current_code_fkreuse_scopebug_pair_20261007/youtube-source-cache/https-www.youtube.com-watch-v-fsc8jcupgtk-standard-f9e26804454064c2.mp4` |
| Barbell Romanian Deadlift | `barbell-romanian-deadlift` | `yQbSQCkhvTM` | `build/exercise_motion/current_code_fkreuse_scopebug_pair_20261007/youtube-source-cache/https-www.youtube.com-watch-v-yQbSQCkhvTM-standard-be008f80035b3f29.mp4` |

The fixture manifest pins the source, candidate, contract, workspace seed, and output-reference hashes. The accepted fresh-inference run is a useful pinned-source control, not proof that the normal source-segment path passes.

- [ ] Build candidate fixtures from each `selected/debug/youtube_candidates.full.json`, retaining the matching exercise and one identity-reviewed recommended candidate, including its complete review payload. Verify that its video ID matches the table. Save SHA-256 hashes of candidate JSON, full source MP4, contract, and reference output.
- [ ] Keep the hash-pinned selected skeletons, rendered previews, and source inputs in the fixture manifest as quality references. Do not force old intervals onto current source-gate results or substitute trimmed clips for the full cached source.
- [ ] Use fresh per-exercise bake workspaces. Exclude completed selections, reconstruction results, terminal verdicts, and old staged reports. Seed only explicitly declared retained inputs and equal cache snapshots.
- [ ] Add a fixed-input harness mode that exercises the real scheduler. First use the existing discovery-resume path if the retained signatures are compatible. Never forge current discovery signatures. If incompatible, add a generic prepared-candidates input that validates identity-reviewed candidates and enqueues normal work items; downstream source validation and reconstruction remain unchanged.
- [ ] Use the existing `bake-and-rank --staged-wave-manifest` entry point for focused stage replay when needed. Directly launching two such commands does not test the production scheduler's overlap admission.
- [ ] Qualify the inputs as part of the first measured arm: source preparation, exact source validation, reconstruction, final validation, materialization, and actual production-rendered playback must run. `-ReuseExistingSelected` is excluded from this comparison because it skips that work.

Exit: fixed input hashes, current source-gate evidence, retained failure evidence if any, and a successful current output for both exercises before claiming usable throughput. If either fails, inspect its source, reconstruction, or fit evidence and fix the actual owner before resuming the comparison.

## 2. Complete measurement and isolation

Files to work in: `scripts/motion_speed_harness.py`, `exercise_motion_pkg/wave_pipeline.py`, and existing scheduler/session timing code. Reuse existing metrics before adding instrumentation.

- [ ] Record Git revision and diff identity, effective production interpreter and package versions, model/checkpoint hashes, policy/renderer identity, full request settings, fixture hashes, and initial cache hashes in each result.
- [ ] Copy the same frozen outcome-index and relevant reusable cache snapshots into every arm. Keep mutable question/review caches, reconstruction caches, output indexes, and session directories arm-local. Shared full source videos may be read-only inputs; no arm may download or alter them during a fixed-source comparison.
- [ ] Ensure metrics include only the new run ID. Copied historical wave reports must not contribute. Retain artifacts on failure or missing metrics.
- [ ] Record item ready/enqueued timestamps, wave admission time/reason, phase transitions, first accepted/materialized output, and actual concurrent-wave high-water mark.
- [ ] Separate llama startup, inference, slot/queue wait, drain/quiesce, restart, and GPU-lock wait. Separate CPU-fit execution/queue time from render/browser time and speculative work consumed/abandoned.
- [ ] Record GPU utilization/VRAM and CPU/RAM at a low-overhead interval, plus fatal errors, malformed/truncated model responses, timeouts, and OOMs.
- [ ] Verify cache/path isolation and stage entry before a model run. A focused harness smoke check and existing relevant tests are sufficient; do not add a parallel benchmark framework.

Exit: a result whose wall time, accepted artifacts, queue intervals, effective configuration, and cache state can be audited without summing overlapping phase totals.

## 3. Measure shared ownership and two-wave overlap

Current implementation limitation (verified 2026-10-08): the persistent service executes each request inline under process-wide stdout/stderr redirection, and the PowerShell runner clamps staged-wave concurrency to one. The harness rejects `shared-overlap`. Its supported arms are now `qwen-full` and `qwen-shared`, both using Qwen for source and final review; the second changes shared-server ownership while keeping wave concurrency at one. First qualify both fixed inputs under current policy62 and resolve RDL's pending rendered-fidelity review, then measure these two arms. Removing only the concurrency clamp cannot create safe overlap; threading whole waves also conflicts with process-scoped generation markers and model-session ownership. Treat two-wave overlap as future work requiring an isolated process/ownership design, not as an executable current configuration.

Use the same two inputs as two singleton waves, keep partial wait at 300 seconds, and leave all quality/reconstruction settings unchanged. Inputs must be prepared so the next item can be ready before the current wave completes.

| Arm | Shared llama | Maximum active waves | Purpose |
| --- | --- | --- | --- |
| `qwen-full` | Off | 1 | Current Qwen production ownership |
| `qwen-shared` | On | 1 | Isolate shared-server cost/benefit with Qwen held constant |
| `qwen-shared-overlap` | On | 2 | Future overlap test with Qwen and shared ownership held constant |

- [ ] After current-policy fixture qualification, run `qwen-full` versus `qwen-shared` first. Stop if either fixture fails or any output lacks visual/package qualification.
- [ ] Only if shared ownership helps, evaluate `qwen-shared` versus `qwen-shared-overlap`; stop if overlap high-water never reaches 2. Resolve failed admission/queue behavior before another expensive attempt.
- [ ] If overlap helps, compare the combined candidate against `qwen-full` to establish improvement over current production. Shared ownership could cost more than overlap saves.
- [ ] Inspect the source clips and generated playback of both outputs in each arm using the actual production renderer. Automated acceptance alone is insufficient.
- [ ] If promotion is plausible or timing noise obscures the result, run one reverse-order comparison of the two finalists with reset initial caches. Maximum for this first decision: five measured arms; no retries beyond the stated diagnostic fix.
- [ ] Choose the fastest arm with the same usable output and no resource or lifecycle regression. Keep concurrency 1 if contention or restart/drain costs erase the benefit.

Exit: measured current-default versus candidate wall times, acceptance/playback parity, observed overlap, and an explained time breakdown. Two singleton waves establish only a pilot result; they do not justify library-wide defaults.

## 4. Optimize the largest remaining measured costs

After step 3, rank avoidable costs by their contribution to time per usable output. Work on one owning layer at a time, retaining inputs from the pilot rather than reconstructing again for every local experiment.

| Measured cost | Exact next investigation | Promotion condition |
| --- | --- | --- |
| Duplicate source/final model calls | Trace existing question and verdict cache misses. Compare identical prompt/image/contract/model/policy identities; fix missing safe reuse or duplicate work. | Avoided real calls with identical decisions; changes to any semantic identity still invalidate reuse. |
| llama request or queue time | Replay the same saved real requests with 4 versus 6 slots, keeping at least 8192 context tokens per slot and the current image budgets/model. Test a second batch/microbatch setting only if profiling identifies that limit. | Better completed-request throughput, no truncation/OOM/decision loss, followed by the full fixture comparison. |
| Repeated model startup/handoff | Count effective worker lifetimes and cold constructors. Audit whether the existing warm GVHMR path is actually reused across requests/waves and how llama-exclusive transitions behave. | Fewer measured cold starts with unchanged output and exclusive GPU ownership preserved. |
| CPU fitting/queueing | Profile solver evaluations, sparse operations, native thread pools, and slot waits. Sparse zero removal is already applied. Compare fit-lane cap 4 versus 6 only if fit slots are saturated and the host has the documented coding headroom. | Same objectives/output decisions, lower completed-work wall time, and no browser/CPU oversubscription regression. |
| Browser/rendering or repeated materialization | Browser frame batching is already enabled by default after exact PNG/state parity and a retained render-time A/B. Continue only with evidence of duplicate content-identical renders or conversions. | Less actual rendering/conversion with the same production renderer and complete artifacts; the isolated batching win does not establish an end-to-end gain. |
| GVHMR setup/checkpoint loading | Reuse the exact source/weights for a constructor or extraction-only comparison. Test a loading change only after separating cold setup, filesystem cache, and inference. | Tensor/result parity and a completed counter-order timing comparison; then output-quality verification. |
| Discovery/download queueing | Separate search, review preparation, network, and model-slot waits. Prefetch/search caps already exist; tune only the measured starvation source. | Reduced time to a usable input without reducing required source coverage or identity checks. |

Each local candidate gets one baseline/candidate comparison and, only if needed for a decision, one counter-order confirmation. Keep unchanged passing checks. Do not pursue artifact-inventory cleanup as a throughput priority: the retained audit found only tens of milliseconds of savings.

Exit: each implemented optimization has a measured saving, focused correctness evidence, and a clear place in the final combined configuration. If no cost is material and safely removable, leave that layer unchanged.

## 5. Improve time to a usable source

Files to inspect: `scripts/analyze_exercise_motion_source_funnel.py`, `scripts/audit_exercise_motion_candidate_stages.py`, the existing source-outcome index, discovery ranking, `bake_and_rank.py`, and current source gates.

- [ ] Aggregate the retained current-policy funnel without launching models: first-candidate source pass, reconstruction pass, final acceptance, attempts per usable output, and rejection categories with their consumed time.
- [ ] Distinguish unavailable/no candidate, incorrect exercise identity, unsuitable source geometry/visibility, reconstruction defects, fit defects, and final-output defects. Fix processing bugs at their owner; do not compensate by rediscovering the same source.
- [ ] Check whether existing outcome-informed ranking already handles repeated bad sources. Introduce a generic ranking/ordering correction only for a demonstrated missing signal, using observed visibility, support evidence, and explicit equipment/contract requirements.
- [ ] Validate ranking changes on a frozen retained candidate inventory. The two successful Step-Up examples cannot establish improved source-selection yield. Add only the smallest retained failure cases needed to test the affected rejection categories, and state that expansion's purpose.
- [ ] Re-run only changed work. Preserve valid downstream caches when the source/contract/model/policy identities match; preserve fallback candidates and bounded attempts when they do not.

Exit: fewer costly failed attempts per usable output on the declared set, unchanged false-accept safeguards, and rendered confirmation. A higher model recommendation count is not enough.

## 6. Tune batching, then confirm under production-sized load

Batching follows the overlap decision because larger waves can improve utilization but also delay the first output and change contention.

- [ ] Replay retained ready-item arrival timestamps through the actual queue/admission logic without inference. Compare wait 300 versus 600 seconds, and wave size 6 versus 8, changing one setting at a time. Respect the current rule that active upstream work can extend the flush threshold to twice the configured wait.
- [ ] Advance only a candidate predicted to reduce idle/model-startup time without unacceptable first-output delay. If the trace gives no such opportunity, keep the current batching defaults.
- [ ] If the two-exercise pilot shows a promotable scheduler/resource gain, expand once to a frozen 16-exercise cohort, two full waves of 8. This expansion answers one specific risk: simultaneous source-VLM and final-fit/review demand under full production wave sizes.
- [ ] Choose retained inputs with current quality evidence and varied motion/support/equipment demands; document the cohort before running. Do not duplicate the same source under invented exercise names to fill waves.
- [ ] Compare the current production configuration and the final combined candidate using identical initial cache/outcome-index states and normal bounded candidate budgets. Declare a wall limit before starting, capped at 180 minutes per arm. Stop on an unexplained quality/lifecycle regression rather than extending the run.
- [ ] Keep fixed-source and discovery-inclusive results separate. Any claim about the whole generator requires a bounded normal discovery-inclusive comparison on the declared frozen exercise/search set; source-only replay cannot support that claim.
- [ ] Inspect actual rendered outputs and explain changed failures/attempts. Require observed overlap at production wave sizes, unchanged usable yield, improved wall throughput, and preserved CPU/VRAM headroom before enabling new defaults.

Exit: a stated, bounded performance/quality result for the measured cohort. Sixteen exercises still do not prove every exercise works. No full 262-exercise rerun is needed for this investigation.

## 7. Ship verified defaults and the evidence

- [ ] Apply only the measured winners to the owning runner/library defaults. Retain flags/environment overrides for the previous safe configuration.
- [ ] Add or extend only focused regressions for concrete risks: scheduler admission/GPU ownership, cache invalidation, fixture isolation, or a specific processing bug. Reuse `tests/test_wave_scheduling.py`, `tests/test_shared_llama_server.py`, `tests/test_source_question_cache.py`, and `tests/test_resource_budget.py` where applicable.
- [ ] Batch related edits, then run the smallest relevant pytest subset under the production interpreter, `py_compile` for edited Python, PowerShell parser checks for edited scripts, and `git diff --check`. This work requires no Android build unless app/runtime-renderer sources are also changed.
- [ ] Update the generator runbook and save a compact before/after report: exact command/settings, input/cache identities, usable outputs/hour, first usable output time, attempts, quality findings, resource limits, and remaining failures.
- [ ] Keep the unrelated `vlm_review_debug.json` working-tree change outside this work. Do not delete retained fixtures or failure evidence to obtain cleaner benchmark results.

Completion means measured practical improvement plus usable rendered output and reproducible settings. If no safe candidate beats the baseline, document that measured limit and the remaining owning bottleneck. The result must not imply that a harness fix or an unexecuted scheduling opportunity is a production speedup.
