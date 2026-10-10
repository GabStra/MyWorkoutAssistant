# Exercise motion throughput and work handoff

## Objective

Produce usable, production-rendered movements sooner across the exercise library.
Preserve existing quality checks, source diversity, bounded attempts, cancellation,
cache identity, and exclusive ownership of GPU models. Keep Q6 and current model
context settings. Increasing automated acceptance or accelerating rejection alone
does not demonstrate success.

## Evidence checked on 10 October 2026

The overnight run produced 12 packaged movements in approximately 9 hours 47 minutes.
Its 27 retained wave reports include 10 waves with one exercise and 11 waves with
one final-validation worker. Source preparation requested two-source portfolios,
but 42 exercise entries had one usable source and 14 had two. Ten entries did not
record portfolio counts. These are stage entries, not independent quality trials.

Source sessions recorded 1,281 model requests and 135 server starts. Summed startup
time was approximately 20 minutes; it is not an exclusive wall-time partition.
Render-prefetch reports record 27 `abandoned_for_finalization` and 12 `prepared`
outcomes. An abandoned outcome does not establish how much CPU work was completed.

Current `run_exercise_motion_workout_plan.ps1` forces deferred discovery's suitable
target to one. The staged pipeline already supports up to two diverse alternatives.
The persistent service executes whole requests serially and clamps concurrent waves
to one. Final validation includes both CPU fitting and model-backed review. Whole-wave
concurrency cannot safely be enabled by removing that clamp: service log redirection
is process-wide, and model shutdown/handoff assumes a single GPU phase owner.

## Design

### Source preparation

Keep the first suitable source eligible immediately. Use the existing discovery-turn
time/candidate bounds to prepare one additional suitable alternative when capacity is
available. Do not make reaching two a prerequisite for admission or expand first-pass
reconstruction beyond the existing two-attempt cap. Prefer existing portfolio diversity
selection; add no exercise-name rules. Stop further preparation after acceptance.

This needs an explicit primary-ready milestone in the wrapper's discovery job rather
than simply changing the target from one to two and waiting for the process to exit.
Primary-ready publication must reference a complete immutable candidate snapshot so
discovery cannot rewrite a manifest being read by an admitted wave. Secondary results
are published separately and become eligible only before their reconstruction begins.

### Preserve fitting work

Keep one owner/future per candidate workspace. A running primary preparation is
promoted to finalization priority and awaited within its remaining candidate deadline;
final validation consumes its existing artifacts. Cancel queued obsolete work and
abandon a running preparation only on cancellation, deadline exhaustion, invalidated
inputs, or confirmed acceptance of another candidate. An incomplete preparation is
never sufficient for acceptance. Failures retain the normal owning-stage classification.

### Continuous CPU fitting across wave boundaries

Retain the persistent service and existing machine-wide fit budget. Separate its
GPU phase admission from candidate CPU preparation/completion. Completed reconstruction
feeds a bounded shared fit queue; free CPU lanes can take candidates from the next wave.
Do not increase the four-lane host policy or create a fit pool per wave.

Discovery/pose filtering/reconstruction/model-backed final review continue to obtain
exclusive GPU ownership. A CPU fit can overlap a GPU phase only after its source/contact
observations are materialized and its remaining work is verified CPU-only. Merely
being in `final_validation` is insufficient. Model review is queued after deterministic
artifact preparation and uses the existing managed model session and handoff protocol.

Use explicit per-request logging for concurrent CPU tasks; do not execute simultaneous
whole-wave `redirect_stdout` contexts. Durable service state lists active candidate tasks
and the current GPU owner. Results remain published atomically per original request.
Publish wave completion only after all its candidate tasks have reached a terminal
state and all approved outputs have passed existing packaging checks.

### Review reuse and model lifecycle

Before adding a cache or restart optimization, attribute repeated requests and server
starts to their owners. Reuse only an existing successful review whose model, prompt,
images, source interval, contract and policy identities match. Do not cache incomplete
answers or keep a resident vision model during a reconstruction handoff. This step
must report request/start reductions separately from usable movement throughput.

## Implementation scope

- `scripts/run_exercise_motion_workout_plan.ps1`: primary-ready discovery publication,
  bounded secondary preparation, admission and completion tracking.
- `exercise_motion_pkg/wave_pipeline.py`: candidate task handoff, separation of CPU
  artifact preparation from GPU-backed final review, preservation of running fits.
- `exercise_motion_pkg/staged_wave_service.py`: bounded task scheduling, explicit
  logging, durable active-task/GPU-owner state, cancellation and recovery.
- `exercise_motion_pkg/fit_runtime.py`: promote an existing preparation without
  abandoning its workspace or allowing duplicate ownership.
- Existing focused wrapper, wave, service and fit-runtime tests: regression coverage
  for primary readiness, handoff, exclusive GPU admission and cancellation/recovery.

Do not change model quantization, quality thresholds, rig/contact fitting algorithms,
renderer geometry, or unrelated Android code. Do not restart the full library as a
verification shortcut.

## Verification and rollout

First reproduce the current handoff cancellation with an event-controlled test. Verify
the same preparation completes exactly once under finalization, and failures/timeouts
still classify normally. Use event-controlled scheduling tests to demonstrate CPU
overlap while asserting at most one GPU phase owner. Verify Ctrl+C/cancel during each
phase, queue draining, request ownership, log isolation and crash recovery.

Run only owning focused pytest subsets, PowerShell parser checks and Python compilation.
Then use retained RDL and OHP inputs for matched before/after runs with identical model,
source, cache availability, renderer and validation policy. Inspect production-rendered
outputs and compare wall time, accepted output count, fit/render duplication, GPU phase
waits and model request/start counts. Expand only for a demonstrated scheduling or
generalization risk. Do not claim library-wide gains from the two-exercise test.

Do not enable the new overlap path by default until the controlled run demonstrates
preserved quality and improved time to usable output. If overlap introduces GPU
contention, duplicated work or ambiguous recovery, retain the serialized admission
while fixing the owner; do not compensate with more retries or weaker validation.

## Review status

Architectural design approved; fit preservation and opt-in bounded CPU-wave overlap
implemented and reviewed. Immutable wave-owned candidate snapshots are implemented.
Primary-ready streaming / a secondary discovery turn remain unimplemented. Current
production-rendered retained RDL/OHP artifacts were checked; a matched end-to-end
throughput comparison remains pending because an existing user-owned library run was
active. The serialized default is retained, and no measured speedup is claimed.

Opt in on a subsequent library run with `-MaxConcurrentStagedWaves 2`; the library
launcher enables the required shared model server for that path. Resume omitting
`-Fresh` to retain useful work. For a controlled two-exercise harness comparison,
use `--arms qwen-shared,shared-overlap --staged-wave-size 1` with pinned fixtures.


### Follow-up: streamed reconstruction completion (2026-10-10)

Live stacks showed the second wave holding the service GPU lease during CPU pose-fidelity validation and trajectory fitting, while the first wave waited for final review. Reconstruction completion now feeds a bounded final executor per exercise as soon as its candidate portfolio finishes. Candidate priority, quality checks, retained stages and retry budgets remain unchanged. Final decisions are checkpointed immediately and the PowerShell completion lane promotes each completed exercise once while its wave is still running.

Source review still uses a batch GPU phase. During generation and finalization, leases cover extraction and model calls only. Final VLM calls share the existing parallel slots within a wave; extraction remains exclusive, and queued reviews take priority. CPU preparation waits observe cancellation and drain expired workers before another fit uses the same workspace. GPU queue waits preserve candidate deadlines.

The warm extractor's residency marker remains until a model handoff stops the worker. The supervisor checks that marker before restarting llama.cpp, so releasing a compute lease does not imply VRAM has been released. CLI waves use the same local gate. Generation and final review share one vision session, and overlapping phase times must not be summed as sequential wall time.

This removes the reconstruction batch barrier, not the separate discovery primary-ready barrier documented above. Focused scheduling/ownership regressions verify ordering and handoff safety; a production speedup and acceptance rate still require a resumed run with the updated worker. The active user-owned run was not stopped or used as a benchmark.

### Follow-up: export queue and discovery starvation

The completion helper now accepts the wrapper's actual `System.Collections.Queue`.
Its previous generic queue parameter coerced that queue into a copy, losing streamed
completion entries while marking them handled. The regression uses the production
queue type and verifies exactly one export while a sibling remains pending.

At the opt-in wave cap of two or more, shared-server discovery may run alongside
baking. Its YOLO calls use the existing shared vision session's CUDA admission,
co-residency probe and exclusive drain/restart protocol, releasing transient YOLO
allocations before the admitted operation exits. Standalone discovery, the default
wave cap of one and explicit `-GpuDiscoveryBakeOverlap avoid` retain serialization.
This supplies the next wave without removing GPU residency protection. The separate
primary-ready discovery barrier remains; no full-library speedup has been measured.

Contact checks distinguish movement within an observed plant from relocation between
episodes. Explicit foot patches retain the stricter planted-contact limit rather
than inheriting the full-clip ankle-proxy allowance. Horizontal torso poses no longer
trigger export inversion from head/foot height alone; an explicit rendering floor
also prevents presentation pitch/roll changes. Python export retains that floor
even without detected contact episodes. Refinement blocks must afford their measured
minimum update time in every stage. These changes do not waive failed fit or playback
checks, and retained poor reconstructions can still require another candidate.
