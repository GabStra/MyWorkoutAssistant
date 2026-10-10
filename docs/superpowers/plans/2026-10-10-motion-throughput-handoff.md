# Motion throughput handoff implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; execute and verify each task before proceeding.

**Goal:** Reduce duplicated fitting and idle CPU lanes without competing GPU phases or changing quality gates.

**Architecture:** Preserve candidate-owned preparation futures and expose a CPU-only preparation handoff to the persistent service. The service may prepare the next admitted request during that handoff, with one GPU phase owner and one shared bounded CPU executor. Source discovery publishes immutable primary-ready snapshots and bounded secondary results.

**Tech stack:** Python concurrent futures, existing file checkpoints/leases and resource budgets, PowerShell supervisor.

**Spec:** `docs/exercise_motion_throughput_handoff_design.md`.

## Global constraints

- Keep Q6, context settings, four-lane host policy, source diversity and all quality checks.
- Keep first suitable source immediately eligible; maximum two reconstruction attempts.
- Preserve Ctrl+C, request ownership, recovery and atomic result publication.
- Leave unrelated workspace changes intact; do not commit mixed work or launch the full library.

## Review focus

- A finalization waiting for its own preparation must not preempt that fit.
- Queued obsolete preparation must not delay a runnable primary candidate.
- CPU overlap must not make GPU sessions or per-request logs overlap incorrectly.
- Cancellation must stop secondary admission and drain owned active tasks.
- Repeated source discovery must not rewrite an admitted snapshot.

## Tasks

1. **Fit handoff** — `fit_runtime.py`, `wave_pipeline.py`, owning fit/wave tests.
   - [x] Reproduce a running preparation abandoned by finalization.
   - [x] Promote same-workspace preparation under existing priority registration; join with a bounded handoff and preserve leaf deadlines.
   - [x] Test same-workspace priority, timeout/cancellation, exactly-once preparation and unchanged final validation.
2. **CPU preparation milestone** — `wave_pipeline.py`, CLI manifest forwarding, wave tests.
   - [x] Add an optional service phase context after GPU release and CPU-only preparation submission, before final model review.
   - [x] Include ready primary candidates even for single-item waves when using the service handoff.
   - [x] Verify the phase context cannot execute while reconstruction ownership remains active.
3. **Service scheduling** — `staged_wave_service.py`, wrapper admission, service/scheduler tests.
   - [x] Use a bounded two-request CPU handoff with explicit request logging and durable suspended/request owner state.
   - [x] Keep GPU execution serial and permit the next admitted request during CPU-only work; retain serialized default until measured.
   - [x] Verify ordered admission, out-of-order completion, isolated logs, cancellation and ambiguous recovery.
4. **Source readiness** — workout-plan wrapper, discovery checkpoint path, focused wrapper tests.
   - [ ] Publish immutable primary-ready manifest; admit without waiting for target two.
   - [ ] Prepare at most one further suitable alternative under existing turn budgets; never rewrite the admitted snapshot.
   - [ ] Verify no duplicate exercise admission and no secondary work after acceptance/cancellation.
5. **Lifecycle attribution** — retained reports and existing request cache/session owners.
   - [x] Attribute request/server-start totals; change only a reproduced avoidable repeat with conservative cache identity.
6. **Verification** — focused tests, Python compilation, PowerShell parser, retained RDL/OHP.
   - [ ] Compare matched old/new retained inputs; inspect production rendering, wall time, duplicate work and ownership.
   - [ ] Keep overlap opt-in unless quality and usable-output timing improve; record limitations and review final changes.

## Execution ledger

- Initial state: architectural design approved by user. Implementation inline in existing dirty checkout to preserve earlier fixes. No commits or broad rerun authorized/needed.
- Candidate/source/model quality changes are outside this task. An audit count is not a measured throughput improvement.

- Task 1: reproduced active-prefetch abandonment and same-workspace self-preemption; focused regressions now pass. Useful primary workers keep priority through browser-thread contexts. Priority ownership is reference-counted; explicit abandonment still cancels promoted work.
- Task 2 ruling: use a service-provided phase context instead of a recursive handoff callback. It wraps source/generation and final review with one GPU mutex, and yields a cancellation probe during CPU preparation. Cost if wrong: service/CLI interface adjustment; quality checks unchanged.
- Task 3: two requests maximum, one shared bounded preparation executor, explicit active request/GPU owner state and ContextVar request logging. Serialized default preserved. Expired preparations drain before GPU final review. Wrapper still uses verified process-tree termination if a cancelled browser/fit does not drain promptly.
- Task 4 partial: admitted candidate JSON is copied into an immutable wave-owned snapshot; mutation-isolation test passes. Existing two-source portfolio and primary/secondary download queues retained. Primary-ready streaming and a separate secondary discovery turn are NOT implemented; increasing discovery target to two alone would violate first-source latency. This remains follow-up work, not a completed design objective.
- Task 5 ruling: retained totals show model handoff costs, not a proved redundant request with identical evidence. No speculative new model-response cache or model policy change. The reproduced duplicate CPU-work owner was fixed instead.
- Task 6: current production browser rendered retained RDL (133 frames) and OHP (124 frames), including first/middle/last-frame captures, under build/exercise_motion/run-audit-20261010/throughput-render-check. These are retained artifacts, not new accepted generation trials.
- Measurement limit: a user-owned full library run was already active (wrapper PID 1684, service PID 20992 at inspection). Do not stop it or compete for GPU merely for this test. No matched end-to-end A/B or measured library-wide speedup claimed. Harness now accepts shared-overlap; compare qwen-shared,shared-overlap with identical fixtures and --staged-wave-size 1 so the two-exercise base can form two waves. Observed high-water 1 remains a valid configuration but does not demonstrate overlap.
- Fresh review: addressed GPU-held duplicate timeout wait and harness impossible high-water assertion. Follow-up reviewer found no new important correctness issue; acknowledged source streaming and measurement omissions remain.

- Final scoped verification: 50 selected pytest cases passed (89 deselected) in 54.56s, with a separate machine-slot registry for synthetic tests so the live user's solver lanes do not control test ordering. An earlier run exposed transient Windows state-file sharing and live machine-slot contention; terminal-state inspection now follows test worker shutdown, and atomic service records retry transient replacement sharing violations for at most 0.48s. Added a focused retry regression. Python compilation, both launcher parsers, wave admission/run-isolation scripts and diff whitespace checks passed.

- Follow-up fix: live stacks exposed CPU reconstruction tail work inside both the service lease and the inner processing lease. The inner pipeline now receives its existing GPU-operation callback, including optional CUDA SpinePose extraction. Source review remains staged; reconstructed exercise portfolios stream into bounded final processing. Final model requests hold a shared per-wave VLM lease, extraction is exclusive, and ready reviews take priority. Warm-worker residency markers gate supervisor restarts until the worker is released. Completed checkpoint decisions enter the existing PowerShell export lane once before the wave returns. The discovery primary-ready work above remains separate and incomplete.
