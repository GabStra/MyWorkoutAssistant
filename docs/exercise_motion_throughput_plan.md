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
- Use the agreed two-exercise base for iteration. The Step-Up fixtures below are a provisional valid-source option: reconcile them with the agreed base before running, rather than silently replacing it.
- Initial two-exercise arms have a 45-minute wall limit. Stop after a failed qualified-source replay and inspect the owning layer; permit one rerun after a concrete fix. Do not regenerate until a pass appears.

## Current state

Already present in the checkout:

- Sparse-Jacobian zero removal in `articulation_trajectory.py`.
- Conservative conclusive-question reuse across source-review contexts.
- Speculative CPU bake submission only while reconstruction remains unfinished.
- A four-slot CPU fit pool, up to six source-validation lanes, and a warm reconstruction-worker path.
- Optional shared llama ownership and optional two-wave admission in the normal PowerShell scheduler.

The current library wrapper uses wave size 8 and partial-wave wait 300 seconds. The workout-plan runner defaults to one active staged wave. Two-wave admission requires shared llama and only occurs while every active wave reports `final_validation` and the other admission conditions pass. This checkpoint includes final VLM work; it does not imply that the GPU is free for all operations.

The speed harness now exposes wave size/wait, preserves unsuccessful artifacts, remaps copied workspace references, and gives each arm an isolated WHAM cache. Its default exercise pair is a smoke pair, not an established successful throughput fixture. Older harness results may contain shared-cache or absolute-path contamination.

Historical run `9dcc77393c744c62a548c165cb05768b` identifies scheduling opportunity, not a speedup estimate: queued work was held while wave 5 spent approximately 6m34s in final validation, and wave 7 provides another approximately 4m06s interval. At least one partial wave started about 302 seconds after the first visible ready item. Other inter-wave gaps include discovery and preparation.

## 1. Build and qualify fixed source inputs

Files to work in: `scripts/motion_speed_harness.py`, the existing staged-manifest CLI, and the discovery-resume path in `scripts/run_exercise_motion_workout_plan.ps1`.

- [ ] Record the agreed pair explicitly in a fixture manifest. Preserve the original exercise IDs, equipment, exercise contracts, and motion context.
- [ ] For the provisional valid-source pair, retain these exact identities:

| Exercise | Exercise ID | Video ID | Full cached source |
| --- | --- | --- | --- |
| Barbell Step-Up | `2e58bcbc-072b-5057-a5e0-09fa1e2374ff` | `s564zFjF3nU` | `build/exercise_motion/youtube-source-cache/s564zFjF3nU-2291a862b53a.mp4` |
| Bench Step-Up | `ad47ab15-6ce3-5214-b1be-131394063a94` | `Xa_buzDE5AM` | `build/exercise_motion/youtube-source-cache/Xa_buzDE5AM-927f5fc8c92c.mp4` |

Both retained selections currently have policy-121 `valid` markers. These markers describe the retained artifacts; they do not guarantee a new reconstruction passes.

- [ ] Build candidate fixtures from each `selected/debug/youtube_candidates.full.json`, retaining the matching exercise and one identity-reviewed recommended candidate, including its complete review payload. Verify that its video ID matches the table. Save SHA-256 hashes of candidate JSON, full source MP4, contract, and reference output.
- [ ] Keep saved selected clips and skeletons as output-quality references. Their previous exact intervals were 5.6–9.2s and 14.64–20.24s respectively. Do not impose these intervals on the current source gate or substitute trimmed clips for the full source; review timestamps refer to the full video.
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

Use the same two inputs as two singleton waves, keep partial wait at 300 seconds, and leave all quality/reconstruction settings unchanged. Inputs must be prepared so the next item can be ready before the current wave completes.

| Arm | Shared llama | Maximum active waves | Purpose |
| --- | --- | --- | --- |
| `baseline` | Off | 1 | Current library-equivalent ownership |
| `shared` | On | 1 | Isolate shared-server cost/benefit |
| `shared-overlap` | On | 2 | Isolate overlap with shared ownership held constant |

- [ ] Run `shared` versus `shared-overlap` first. Stop this comparison if the fixture fails or overlap high-water never reaches 2. Resolve a failed admission/queue condition before another expensive attempt.
- [ ] If overlap helps, measure `baseline` to establish whether the combined change improves the current production configuration. Shared ownership could cost more than overlap saves.
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
| Browser/rendering or repeated materialization | Identify duplicate content-identical renders and conversions; audit existing content-addressed reuse and prefetch ownership. | Less actual rendering/conversion with the same production renderer and complete artifacts. |
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
