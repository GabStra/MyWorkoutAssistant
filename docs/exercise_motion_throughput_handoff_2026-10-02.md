# Handoff: exercise-motion throughput campaign — 2026-10-02, ~16:12 local

## Current completion audit — 2026-10-06, after CLEF integration

The overall architecture and generator goal remains incomplete. The statuses
below describe the current production owners, not a promotion verdict.

| Requested area | Status | Production evidence and remaining work |
| --- | --- | --- |
| Artifact state machine | Partial verification | `artifact_state.py` validates lineage and terminal classes; `bake_and_rank.py` binds the final review window and selected skeleton identity; `build_workout_plan_movement_package.py::validate_selected_movement` checks the packaged selection against review evidence. The corrected RDL fit/render/review/package checkpoint passed before CLEF integration. The current-code two-exercise production-script replay has not passed. |
| Source-evidence constraints in fitting | Implemented, verification partial | `controlled_motion_fit_source_evidence` binds selected interval, observed support, articulation, and projection evidence to the fit cache. Contact projection now preserves observed root posture and refreshes confirmed ground heights. The corrected RDL fitted and passed review. Corrected Press fitting and pre-render gates passed; its real final review and current-code pair acceptance remain unverified. Camera projection and strict endpoint coverage remain conditional on available evidence and declared intervals. |
| Queue-backed long-lived services | Partial implementation | `staged_wave_service.py::_execute_wave_request` accepts staged bake manifests and keeps the render executor alive across requests. Opt-in reconstruction workers are persistent. `Start-InitialDiscoveryJob`, prefetch, download, and legacy individual jobs still launch transient processes; the generator-wide service queue is not implemented. |
| Persistent infrastructure ownership | Partial implementation | Workspace/process leases, shared-model quiescing, machine-wide fit slots, durable queue claims, ambiguous recovery, and content-verified caches exist for the implemented services. VLM recovery now shares the request budget and avoids restarting a responsive server after a busy inference probe. CLEF owns its server per decision lease and releases it on failure; it is not a long-lived model service. External GPU experiments do not participate in this generator's ownership protocol. |

### Concrete retained quality evidence

- Corrected RDL: `20261006-inspected-rdl-spike-guard-fit-report.json` records an
  applied validated fit, all twenty checks passing, and 88.891 seconds inside
  fitting (91.421 seconds measured wall time). Its standing endpoint tilt is
  approximately 0.94 degrees, versus approximately eleven degrees introduced
  by the previous support projection. The production renderer, real review,
  and packaged-byte parity were checked in
  `build/exercise_motion/replays/20261006-rdl-corrected-posture-render`.
- This single retained result is not proof of library-wide quality or maximum
  throughput. The fit Jacobian comparison proved identical residuals and
  derivatives with a 39 percent reduction for that measured operation only.
- Corrected Press: retained parent frames 53–139 (87 frames) rebuilt with no
  reconstruction run, then passed all twenty fit checks and the production
  pre-render gates. The measured bake-and-fit wall time was 119.395 seconds;
  fitting reported 74.641 seconds and 29 evaluations. The review video and
  sampled production playback were inspected in
  `build/exercise_motion/replays/20261006-corrected-press-local-time-bake`.
  Final model review and packaging remain pending. An earlier preparation used
  parent-video pose timestamps with a zero-based cropped clip; the pre-fit gate
  rejected that invalid fixture in 15.663 seconds. The fixture was rebased and
  regenerated; no production gate was weakened.
- CLEF code is integrated into all production bake runners, including the
  workout-plan runner. Typed-answer mapping, uncertainty handling, CLI
  forwarding, managed-server cleanup, and existing equipment gates have focused
  coverage. Its managed startup had an undefined endpoint; commit `986ee0cf`
  fixes it. No current-code pair generation or throughput comparison proves
  the new backend's quality parity or total runtime benefit.
- `run_motion_retained_replay.py` preserves real model reviews while pinning
  source bytes and retained raw reconstruction. It bounds the process tree and
  verifies approved outputs and reviewed-versus-packaged bytes. It does not
  cover extractor inference/cache lookup, and a passing harness unit check is
  not a passing production-script replay.

## Generator architecture and retained-fit update — 2026-10-05

- The artifact-state path is implemented through bake, review, selection, and
  packaging. Source-evidence constraints reach fitting when selected-interval
  evidence is present, but remain optional for full-clip fits without a declared
  interval. The staged bake queue is a real workspace-scoped serial service;
  discovery, prefetch, and source-download callers still use per-item PowerShell
  jobs. Persistent ownership was audited in these paths and no ownership gap was
  demonstrated. These are current boundaries, not a completed queue-wide rewrite.
- The controlled-motion fit now sends a normal fit with an isolated nested
  playback-velocity miss through the existing bounded path repair. It preserves
  the normal strict validator, rejects any trial that adds a failed check or
  worsens jerk, and caps this normal-fit repair window at 20 seconds. Skipped-
  soft-solve repairs retain their existing broader path and budget.
- The retained RDL replay at
  `build/exercise_motion/replays/20261005-rdl-v66-velocity-path-report.json`
  ended with playback passing (C1 boundary jump 0.269 mm/s), but its initial
  failed checks contained only jerk and it did not record `playbackPathRepair`.
  It therefore does not exercise or validate this fix. The replay still failed
  the source-relative jerk gate: 0.000859 RMS against a 0.000413 source limit,
  so it remains a rejected fit and does not establish a successful RDL output.
- A failure-only jerk decomposition was added without retaining candidate
  poses. A CPU replay of the same 87-frame input (SHA-256
  `ad98554f6079dbe204b2d7b600bd0576bf8af6c0ec6147b9a9206f948a5e98a4`) took
  136.9s, made no model/reconstruction calls, and reproduced the same rejection.
  Collar, spine2, shoulder, and neck tracks contribute 62.3% of output jerk
  energy. The highest excess windows are source times 1.50–1.77s,
  2.40–2.67s, 1.07–1.33s, and 3.67–3.93s. These localize the defect to
  upper-body articulation and cycle transitions, but do not identify the exact
  repair that caused it. Reweighting and unconstrained smoothing have reopened
  other strict checks in prior diagnostics; no safe jerk repair is established.
- The support audit of that exact input found one mapped full-sole interval
  (fit frames 10–59) and `unknown` patch states elsewhere; it found no persisted
  `airborne` state. Source ankle candidates are not treated as full-XYZ pins,
  and incomplete patch spans are not promoted to full-cycle support. No generic
  contact-detector change is justified by this run's evidence.
- Verification: the three focused playback-repair regressions passed, and the
  production wrapper passed both cached and fresh-source-evidence cases
  (`2 passed in 309.22s`) before the diagnostic-only addition. After adding the
  jerk decomposition, all four focused repair/diagnostic regressions passed and
  edited Python modules compiled. No live model/GPU campaign or app tests were
  run.
- A focused retained-interval trace found that playback grip projection alone
  reduced interpolated bar-grip error from 11.32mm to 8.81mm (the gate is
  9.41mm), but the repair path then ran contact-plant projection unconditionally
  whenever any joints were pinned. That projection moved supported feet by
  23.3mm and failed support, discarding the grip correction. Contact repair now
  runs only when stored contacts exceed 0.5mm or interpolated contacts exceed
  the 3mm playback gate. The regression passes and the post-change replay no
  longer shows the support regression, but RDL remains rejected: final playback
  still reports 11.32mm grip error and right-wrist/hand shake is over its limits
  by 1.2%/0.3%. This is a bounded-path bug fix, not a successful generation.
  The same replay with soft LS forced on cleared grip and shake but introduced
  anatomy and playback-velocity failures, so the geometry-ready soft-solve skip
  remains enabled.
- The playback path report now distinguishes an attempted repair from one
  actually retained. The follow-up RDL replay recorded
  `playbackPathRepairKept=false`; Stage-C shake cleanup therefore no longer
  assumes it has a good path to preserve. Contact, support, and anatomy remain
  clear on the retained attempt, but it still fails interpolated grip at
  11.32mm and right-wrist/hand shake at 1.2%/0.3% over their limits. The
  rejected shake trial reopens multiple structural checks and is rolled back.
  Focused path/contact regressions passed, and the edited Python modules
  compiled; no model or reconstruction calls were made.

## Current-HEAD OHP production-path check — 2026-10-04

A fresh run of `scripts/run_exercise_motion_workout_plan.ps1` at `54ea944b`
completed the normal discovery-to-selection path for one Dumbbell Overhead
Press. It selected a 91-frame movement from the second of two reconstruction
attempts. The runner reported about 28 minutes end to end; the summary records
318.3 seconds for initial discovery and 1388.3 seconds for the bake attempt.

The first source passed review and reconstruction but its 211.4-second preview
bake failed the materialized loop seam gate (31.5 mm jump against a 3.1 mm
limit); its fallback artifact also lacked complete lineage. The second source
passed. Its preview bake took 399.7 seconds, with 112.5 seconds in GVHMR and
131.7 seconds in source preparation. These stage figures overlap other runner
work and should not be added as independent wall time.

Movement generation and selection succeeded. The optional mobile-package step
then failed because this run used an exercise-only plan fixture with a root
`exercises` array, while the package builder expects the WorkoutPlanPackage
shape (`exerciseDefinitions` or workout components). Running that builder with
a package-shaped input and the same completed summary attached the selected
skeleton by strict exercise ID and wrote one movement backup. This was an input
shape mismatch in the package smoke invocation, not a movement-generation
failure; the generated artifacts remain available in the ignored run workspace.

## Latest verification — 2026-10-04

The current checkout completed a production-path `shared` arm at
`build/exercise_motion/speed-harness/20261004-002720-2d0ca119/` in **1201.9s**.
The run used the fixed OHP + RDL pair, wave size 2, and `--skip-prewarm`; its
source identity records diff SHA-256
`892a17a16dd5fcba6c8f6f45931a4a7b850ce0093fbb4b925ed7c2f95a9cf29f`.
It produced one completed OHP and one RDL `no_selection`. OHP’s 85-frame
production-rendered movement passed final validation and package parity; the
selected and packaged skeleton SHA-256 is
`187fa6f632e4aefd07f64eee8bb3d8bc6a41e0ac06e8a1e0c2e64f672d1607a2`.
Rendered playback and the source’s press/lower sequence agree. First accepted
output arrived at 1189.8s and first materialized output at 1194.9s.

RDL passed source review and reconstruction, then failed independent fit and
materialized-motion quality checks: contact error 20.5mm (0.5mm limit), target
RMS 49.8mm, articulation change 26.7 degrees (20 degree limit), support drift
25.6mm, and support-plane error 14.3mm (5mm limits). Deterministic rejection
skipped its render. This is retained as a fit/reconstruction quality failure;
the evidence does not justify loosening gates.

### Architecture audit and fix

- Artifact state and evidence-linked identity now flow from bake through review,
  package parity, and package audit. PowerShell still builds package state with
  duplicated checks; the downstream audit validates the persisted state.
- Source-projection and interval-endpoint constraints are used by the normal
  preview-loop fitter. The audit found the selected time-range re-bake fitted
  before attaching its source camera and selection lineage. That path now
  attaches both before fitting and rebuilds artifact identity afterward; its
  bake cache version is 38. Focused verification passed: 5 selected-path/source
  fit tests, plus Python compilation.
- The production PowerShell runner publishes waves to a singleton persistent
  queue service; staged manifests execute through the real pipeline, and the
  browser render executor and warm model workers are reused within their
  resource-ownership limits. Broader scheduler APIs are not an asynchronous
  replacement for every pipeline caller; this vertical slice is complete, not a
  full multi-process rewrite.
- Persistent infrastructure includes workspace/process leases, worker identity,
  ambiguous-crash recovery, atomic state writes, and content-hash cache checks.
  The package-state duplication is cleanup work, not a demonstrated generation
  blocker.

This arm is a single configuration result, not a baseline comparison or a
maximum-throughput measurement. Cross-wave overlap remains disabled: it was
previously measured slower with lost acceptance parity. The production library
wrapper uses serial waves of 8; this two-item run cannot compare larger batch
sizes. Current measured throughput is 1 accepted output per 1201.9s (about
3.00/hour) on this fixed pair. Do not generalize that rate to the full library.
The selected-time-range fit fix was made after this E2E run, so its verification
is the focused regression rather than a second GPU campaign.

### Follow-up audit — 2026-10-04

- The production PowerShell runner reduces `MaxConcurrentStagedWaves` to 1 while
  the singleton staged-wave service is enabled; the service consumes one wave
  request at a time. This prevents the measured cross-wave fit contention in
  the current production path. Do not add fit-drain admission telemetry unless
  parallel wave execution is reintroduced.
- The retained library has 553 staged-wave reports, including many 6- and
  8-item waves, but those reports lack per-item ready/enqueue times. The 23
  retained scheduler timelines with item timestamps contain at most two items.
  They cannot support a truthful offline comparison of wave sizes 6 vs 8 or
  partial waits 300 vs 600 seconds. Maximum library throughput remains
  unmeasured; no synthetic replay is being treated as a production result.
- The current RDL source passes source review, but cached reconstruction remains
  unusable. Across the retained Oct. 3–4 runs, the baseline repeatedly fails
  spine/anatomy and source-confirmed foot-anchor checks; contact correction
  repairs the anchor check but still fails physical, support-surface, and loop
  seam gates. An earlier retained-interval fit also failed geometry checks.
  The evidence does not justify relaxing gates or removing the fit-budget
  heuristic; classify this as a fit/reconstruction quality defect for further
  generic work.
- No second GPU campaign or duplicate retained-interval fit was run for this
  audit. The selected-time-range source-evidence fix remains covered by the
  focused five-test regression and Python compilation recorded above.

### Post-audit generator fixes — 2026-10-04

- The renderer-contact-IK fallback rebaked a corrected sibling and entered its
  source fit before attaching the selected artifact state. It now attaches the
  same interval lineage as the baseline before fitting. The focused regression
  exercises the bounded-selection fallback and confirms its interval evidence
  is present at the fit call.
- A retained RDL bake had `bilateralAssignment=swapped`: source-left foot
  observations were projected onto the rig's right side, while contact pins,
  stance identities, and ground anchors stayed on the left. The fit/playback
  support path now derives a cached motion-space view for side-specific evidence
  and leaves the original source evidence unchanged. Its test checks pin side,
  shared stance identity, preserved source evidence, and cache identity across
  camera assignments.
- Focused validation passed: five contact-correction cases, two contact-mask
  cases, and `py_compile` for the edited generator modules. A CPU-only replay of
  the retained RDL bake completed in 83.8s but still returned
  `no_validated_loop_cycle`; no successful RDL generation is established by this
  fix. No GPU/model campaign was run.
- These fixes do not change the measured accepted-output throughput or prove
  maximum library throughput. The RDL anatomy/support/loop-quality issue and the
  missing arrival-time telemetry needed for a valid batch-size comparison remain
  open.

### Follow-up generator fixes — 2026-10-04

- The swapped-camera mapping now reaches browser contact locks, Python contact
  correction, and the final source-support stationarity gate. The export keeps
  source-labeled evidence and carries a separate mapped view for rig constraints;
  corrected-range rebakes use the already-cropped mapped evidence for that range.
- `_fit_observed_cycles` now preserves explicit retained-fit skip reasons. The
  persistent source-spine-fold skip is no longer reported as the generic
  `no_validated_loop_cycle`, which made the prior CPU replay ambiguous.
- A read-only constraint replay against the retained RDL checkpoint leaves its
  source-left labels unchanged and now pins the mapped rig-right foot/ankle
  (54/51 frames, with 12 right-ankle source-anchor observations). The retained
  full fit still records spine/neck anatomy, body-support, and temporal failures;
  this constraint check does not establish a successful RDL generation.
- Focused verification: seven preview/contact-correction cases passed, the
  retained-fit reason regression passed, the selected-section cache check
  passed, and edited Python modules compiled. No application tests, optimizer
  rerun, or GPU/model campaign were run.

## Latest update — 17:10 local

The user stopped the pending baseline arm before it completed. Its artifacts show
OHP in final validation, but there is no completed `results.json`; treat that arm
as interrupted and do not use it in an arm comparison. No more campaign run is
needed to finish the current code and evidence work.

The already completed `shared-overlap` arm is a measured regression against
`shared`: 1948.1s vs 1725.3s wall time (+13%), final validation 1267s vs 830s,
and OHP fell from completed to `needs_manual_review` because final render evidence
was unavailable. RDL was `no_selection` in both. Overlap reached 2 waves, so it
ran as configured, but it failed both the speed and output-parity promotion tests.
Keep overlap disabled by default.

Three follow-ups are now handled in code: the harness reports candidate-generation
time separately from GVHMR stage, runner, prediction, and startup timings; browser
worker metrics identify task and wave process; final-render evidence records the
skeleton hash and packaging checks that exact hash after copy. No tests were run,
per the user's instruction. The edited Python modules compile and the PowerShell
runner parses.

In the completed `shared` run, the old `gvhmrAttemptSeconds` value of 479.9s was
the sum of full candidate-generation attempts. Candidate manifests report 318.5s
in `whamRunSeconds` (the GVHMR stage wall time, including worker readiness/waits),
and only 1.757s in model `predictionSeconds`. Those are different scopes and must
remain separate in future comparisons.

Report for an LLM resuming this work. Everything below is verified against the repo
state unless marked ESTIMATE. Read `docs/exercise_motion_throughput_plan.md` first —
it is the governing plan with the decision rules; this report is the execution state.

## Mission

Execute `docs/exercise_motion_throughput_plan.md`: raise usable production-rendered
movements per hour. The method is measure-first: qualify fixed inputs, run a 3-arm
comparison (`baseline` / `shared` / `shared-overlap`), promote a change only on a
repeatable ≥10% wall-time reduction at unchanged usable output, then optimize the
largest measured costs (plan §4), then batching (§6) and defaults (§7). Hard rules:
never weaken a gate to pass, no per-exercise fixes, report genuine failures honestly,
commit before any measured run (uncommitted edits change policy stamps and cache keys),
45-min wall limit per two-exercise arm, and a failed replay means inspect the owning
layer, not regenerate.

## State at handoff

- 8 commits on master today (HEAD `2816a807`), all verified (py_compile, focused
  pytest subsets, PowerShell parse where relevant). Working tree clean except
  `vlm_review_debug.json` (UNRELATED pre-existing change — keep it out of commits)
  and untracked `scripts/gvhmr_image_parity.py` (A/B helper, worked, keep or delete).
- The campaign root is `build/exercise_motion/speed-harness/20261002-160139/`.
  `shared-overlap` completed. The user stopped the still-running `baseline` arm
  during OHP final validation; it is incomplete and was not compared. Do not treat
  its partial checkpoint as a result.
- The `shared` arm already completed separately: run root
  `build/exercise_motion/speed-harness/20261002-152827/` — wall 1725.3s,
  statuses `{completed: 1, no_selection: 1}`.

## Fixture pair (the measurement inputs)

`build/exercise_motion/speed-harness/fixtures/press-rdl-pair/fixture_manifest.json`
(hash-pinned; rebuild with `scripts/build_motion_fixed_fixtures.py`):
- Dumbbell Overhead Press `4f86a919-b6bf-51ec-afac-c61750b690f3`, video fSc8JcuPgtk —
  accepted by the Sep campaign; **produced a completed, validated, materialized
  movement in the 152827 run** (movementId `exercise-motion:4f86a919…`, contentHash
  `9d04ab63…`, embedded gzip+base64 wear_skeleton in `movements_out.json`).
- Barbell Romanian Deadlift `03b68a7c-fa03-57e2-b6d8-63092a6091ab`, video 4QT5iMY2dUM —
  **fails deterministically** at `source_confirmed_baseline_support_drift`
  (`left_source_confirmed_anchor_relocated`, identical numbers across two runs =
  genuine fit-drift rejection on the cycle span; known deferred quality class from
  the Sep campaign, same wall as back squat/lunge). Treat as genuine; do not tune
  around it. Consequence: attempts-per-usable-output = 2 on this pair.
- The plan's originally proposed Step-Up pair is dead as fixtures: both rejected at
  the final gate (barbell acutely: seam velocity mismatch 4.24 m/s). The step-up
  fixture set still exists at `speed-harness/fixtures/step-up-pair/` (unused).

## The three arms (plan §3)

Harness: `scripts/motion_speed_harness.py --fixtures <manifest> --arms <names>`
(prewarms the GVHMR worker first; each arm gets a fresh isolated workspace; results
in `<root>/results.json` with wall time, phase timings, vision/llama counters,
scheduler timeline, git+interpreter+plan-hash identity). Arm definitions:
`baseline` = `-WarmWhamWorker:$true -KeepLlamaCppServer:$true`; `shared` = baseline +
`-SharedLlamaServer`; `shared-overlap` = shared + `-MaxConcurrentStagedWaves 2`.
Wave size 1, partial-wave wait 300s, 45-min timeout, GVHMR-only reconstruction.

Measured so far:
- `shared` (152827): wall 1725.3s, completed 1. Phases: source 324s / gvhmr 480s /
  final 830s (fits dominate — known deadline-bound; solver levers exhausted per
  `throughput-audit-2026-10-01` negative-results list: batched FD, LSMR sweeps,
  x_scale, coarse-to-fine, within-fit parallelism all rejected). Startup-to-first-work
  67s. Wave admissions both `full_wave_ready`; wave 2 admitted at t=645s (serialized).
  The old `gvhmrAttemptSeconds=479.9s` mislabeled candidate-generation wall time;
  candidate manifests separate `whamRunSeconds=318.5s` and model prediction
  time `1.757s`.
- `shared-overlap` (160139): 1948.1s wall, final validation 1267s, overlap high-water
  2; OHP `needs_manual_review` (`final_render_evidence_unavailable`), RDL
  `no_selection`. This is a measured regression against `shared` and fails promotion.
- `baseline` (160139): interrupted by user during OHP final validation; no result.
  No baseline comparison or default recommendation about shared llama ownership can
  be made from this arm.

Decision rule once they land: compare wall time + first-usable-output time +
accepted-output parity (inspect rendered playback, not just gates). If overlap helps,
keep it (baseline arm then establishes combined benefit vs production default).
Concurrent-wave high-water must show 2 for shared-overlap to count (checkpoint
`metrics.runningStagedWaveCountHighWater` / harness `overlapHighWater`). Max 5
measured arms total for this decision; one reverse-order repeat allowed if noisy.

## What today's commits fixed (chronological, all root-caused from replay failures)

1. `a85286d4` plan steps 1–2: `scripts/build_motion_fixed_fixtures.py` (hash-pinned
   fixture builder), harness `--fixtures` mode (fresh exercise_plan-only workspaces,
   arm-local prepared-candidates manifest, SHA-256 re-verification, run identity,
   `--smoke-check`), runner `-PreparedCandidatesManifest` (bypasses discovery for
   validated identity-reviewed candidates; downstream unchanged), runner writes
   `<workspace>/scheduler_timeline.json` (item ready/enqueue/admit stamps, wave
   admission reason; parsed into harness results). Note: the plan's discovery-resume
   path was proven incompatible for fixed inputs (signatures hash the CLI args) —
   prepared-candidates is the sanctioned alternative.
2. `9885716a` wave contract path: reads the shared contract cache (identical key —
   verified) and gained the third `direct_repair` attempt; without it, contracts that
   prefetch rescued via repair got regenerated-and-failed in waves
   (`exercise_contract_invalid`). Cache dir plumbed via request field + bake CLI arg
   + ps1 `--exercise-motion-contract-cache-dir`.
3. `9cea4f5f` exact-pose validator: under `shared_cache_dir` the pose-reference write
   preceded the cache write's mkdir → FileNotFoundError swallowed as
   `validation_execution_failed` for EVERY confirmation candidate. One-line-class fix.
4. `e1b19bba` seam-gate premise: 4a35fe44 (Sep-29) added the loop-continuity check to
   the bake-time pre-render gate, where the artifact is the authoritative FULL-CLIP
   bake (contains walk-in/setup; can never satisfy a return-to-start seam). Fix: the
   hard-reject applies only when the payload declares a loop span
   (`loop.enabled` true); payloads without loop state keep the check (conservative).
   Evidence: the observed OHP cycle has a 1.1 cm seam (passes).
5. `db70c1a6` + `2816a807` endpoint provenance: the ranking payload's contract is the
   MODEL'S JSON ECHO of the prompt-shaped reduction (drops status/source), so the
   advisory classification of generated expectations saw unknown provenance and
   hard-blocked a window-boundary start-frame mismatch (OHP handHeight
   shoulder_chest vs above_head; fidelity otherwise 1.2% body ratio). Fix:
   `exercise_motion_contract_for_review_item` recovers provenance from the echoed
   contract, else from the candidate's raw contract. Classification semantics
   unchanged (unknown provenance still blocks; explicit exercise-definition
   requirements re-block independently).
6. `a2f3a5db` Windows `os.replace` race (WinError 5) on the shared llama in-flight
   counter → bounded retry; harness stall threshold 180→300s.
7. `2a890e2a` GVHMR worker pre-warm (one-shot container, waits for ready.json, stops)
   + stall threshold 300→600s. Why: cold in-container startup is ~350-460s and silent
   in run.log — the stall-kill fired before readiness and kept every restart cold.

All replay failure evidence is retained under `build/exercise_motion/speed-harness/
20261002-{092123,094639,100044,103708,111812,115659,120635,122110,123917,152827}/`.

## Docker image (user-requested side quest, DONE)

- Dockerfile `docker/gvhmr/Dockerfile` now bakes bytecode (`compileall /opt/gvhmr`;
  the COPY layer had zero .pyc) and `mmap=True` on the 5 big `torch.load` checkpoint
  sites. Rebuilt as the SAME tag `myworkoutassistant/gvhmr:torch2.3-cu121`; old image
  preserved as `myworkoutassistant/gvhmr:pre-startup-opt`.
- A/B verified: outputs BIT-EXACT on a reference clip (joblib pkl: pose_world,
  trans_world, betas, frame_ids all element-wise equal). Job execution 126.4s →
  39.0s; cold worker load 373s → 286s (page-cache states not perfectly controlled;
  parity is the decisive result).
- Parity tooling: `scripts/gvhmr_image_parity.py` requires an explicit `--video` and
  `--reference-pkl`, compares `pose_world`, `trans_world`, `betas`, and `frame_ids`,
  preserves existing run directories, and reports Docker/startup/job failures. Each
  run uses a new safe run id; artifacts are under
  `build/exercise_motion/speed-harness/prewarm/parity/`.

## Known open items / honest caveats

1. **OHP review/package parity is confirmed for the accepted `shared` output:** final
   validation and packaging used the same 85-frame cyclic rebake, with matching
   skeleton SHA-256
   `187fa6f632e4aefd07f64eee8bb3d8bc6a41e0ac06e8a1e0c2e64f672d1607a2` and
   `packagedSkeletonReviewParity.verified=true`. The 289-frame count belongs to the
   full-clip parent in its lineage, not the reviewed or shipped selection. Earlier
   notes conflated that parent with the selected movement. New selections carry the
   reviewed skeleton hash/frame count, and packaging verifies the copied file
   against that identity.
2. RDL's support-drift wall (see fixtures section) is the remaining quality
   bottleneck on this pair; fixing it is plan-§5-style next-layer work, not part of
   the arm comparison.
3. Pre-existing test failures (NOT from today's changes, verified on HEAD):
   `test_exact_source_phase_validation_cache_reuses_identical_clips_across_workspaces`,
   `test_loop_bridge_quality_detects_endpoint_mismatch_hidden_by_bridge`,
   2 more endpoint-related in `test_exercise_motion_pkg.py`, and 3
   `test_resource_budget` tests (core-count assumptions). Also the working-tree
   `vlm_review_debug.json` diff is unrelated — leave it alone.
4. Docker has wedged twice today (symptoms: container stuck `Created`,
   `docker start` hangs). Both times recovered by `docker rm -f` of the stuck
   container; cause was orphaned builds/kills during my parallel-build mistake. Do
   not run docker builds concurrently with arms; do not run two builds of the same
   tag (it cost the layer cache once — full rebuild was ~1h45m: 4.6GB context upload
   + apt 38min + pip).

## Environment facts

- Production interpreter: `C:/Users/gabri/miniconda3/envs/mwa-motion-cuda/python.exe`.
- GPU: RTX 4070 SUPER 12GB. Single GPU — never run arms or GPU jobs concurrently.
- PowerShell script checks: parse with the Parser::ParseFile snippet (quote carefully
  from Git Bash; `$` gets eaten — write a temp .ps1).
- Focused verification convention: `pytest -k <subset>` + `py_compile` for edited
  files; run under the production interpreter.
- The harness fast-fails an arm when run.log is silent 600s (cold GVHMR worker start
  is legitimately silent ~350-460s) and aborts remaining arms on early failure.
- Scheduler timeline schema (runner output, harness input): see
  `Add-SchedulerTimelineItemEvent` in `run_exercise_motion_workout_plan.ps1`.

## Current conclusions and next work

1. Close the overlap question at this pilot scale: it ran as intended but was 13%
   slower and broke OHP acceptance parity. Keep `-MaxConcurrentStagedWaves` at 1.
2. The baseline arm is incomplete, so the shared-llama-only decision stays open.
   Do not infer a baseline result from its partial checkpoint.
3. The 82.9s and 67.4s “Motion extractor ready” events are GVHMR warm-worker model
   loads, not llama startups. The pipeline stops GVHMR before VLM use to preserve
   single-GPU exclusivity, then restarts it before later extraction. A larger wave
   may amortize startup across multiple candidates; that is an unmeasured batching
   candidate, not a reason to overlap waves or keep both GPU models resident.
4. Browser worker totals previously omitted task names. Metrics now report jobs,
   launches, reuse, queue wait, and job time by task within each wave process. Pools
   are per wave process, so overlap multiplies host browser/CPU load; the old total
   of three jobs/three launches did not prove repeated rendering of one artifact.
5. RDL remains a fit/reconstruction quality failure. The current-code retained fit
   still rejects for anatomy, contacts, body support, trajectory, root continuity,
   and playback; no acceptance gate was relaxed. The exact source pose lacks foot
   landmarks, so the source-foot projection coverage fix below is not claimed to
   solve this RDL failure. No new model campaign or long fit was started.

Memory file `fixed-fixture-qualification-2026-10-02.md` in the project memory
directory has a condensed version of this state; update it after the arms land.

### Focused generator corrections — 2026-10-04

- Reselection now writes the durable selected-output manifest with
  `write_json_atomic`, matching the initial selection and later manifest updates.
  This prevents interruption during revalidation from truncating the last valid
  selection and its resume state.
- Source-camera fitting now keeps observations for pinned foot/ankle joints when
  the joint is independently confirmed by body-support evidence but has no
  contact-derived anchor group. Existing contact groups still control shared
  stance alignment; the 3D support geometry and all acceptance gates remain in
  force. A focused regression covers confirmed wrist and foot anchors.
- The retained RDL input has no 2D foot landmarks, so that coverage fix does not
  change its fit. The run still needs a separate generic source/anatomy/support
  feasibility fix before it can qualify as a successful fixture.
- Contract normalization now reconciles an explicit endpoint torso description
  with its structured torso-orientation enum, including candidate and cached
  contracts. This stays on the existing cache policy so valid library contracts
  are corrected in memory instead of forcing regeneration. The raw prepared RDL
  fixture had a start-state mismatch; the retained bake already had a matching
  upright start and only an advisory end-state mismatch, so this correction is
  not claimed as the cause or fix for the RDL fit rejection.

### Generator architecture and support fixes — 2026-10-04

- The artifact-state path remains wired through staged production generation,
  final review, selection, and packaging. The process E2E verifies reviewed versus
  packaged skeleton identity and frame-count parity.
- The production process E2E now exercises exact-source validation and body-support
  observation through their production cache readers, then runs the production
  final-output validator and response parser with a deterministic response. It
  continues through the real staged-wave worker, fit, render, artifact lineage,
  and package path. Candidate discovery/source acquisition and WHAM inference
  remain prepared-fixture boundaries.
- Fitting no longer lets swapped-side sole materialization mutate canonical
  source evidence and invalidate its mapped-evidence digest. A fit-scoped
  rig-side evidence view now reaches contact constraints and the fit-source
  digest; a focused regression verifies both the constraint and unchanged cache.
- RDL replay isolated a cleanup coordinate bug: support detection used an
  absolute floor-height band before `ground_to_floor` shifted the clip. For
  continuous-ground motions, cleanup now detects contacts again after this
  clip-wide shift. Intermittent and unknown support keep the original contact
  timing so elevated surfaces are not reclassified as the floor. Root smoothing
  now runs before support anchoring, allowing support constraints to own the
  final planted-foot positions.
- A CPU-only replay of the retained 98-frame RDL raw motion now detects both
  feet in all 98 frames after normalization; each foot's maximum horizontal
  displacement from its first frame is 11.3 mm. This establishes the cleanup
  support fix only. The retained fit and final review have not been rerun, so
  successful RDL selection is not yet established.
- The queued staged-wave service is a real production vertical slice and keeps
  its worker/model services within the workspace-owned run. A host-level service
  supervisor spanning separate runs and a common queue for discovery through
  packaging remain separate architecture phases. Unacknowledged staged results
  are retained because there is no waiter-liveness record proving they are safe
  to delete.
- Focused verification passed for the swapped-support regression, the cleanup
  support regressions (3 tests), Python compilation, and diff checks. The process
  E2E passed once in 165.86s after the root-smoothing order fix and before the
  continuous-only post-normalization detection change; that final branch was
  separately covered by the cleanup regression and retained RDL replay. No GPU
  campaign was run. The baseline remains stopped, so no maximum-throughput claim
  is made.

### Retained RDL fit and acceptance follow-up — 2026-10-04

- The profile replay helper now reads the candidate contract's contact mode,
  support orientation, and paired-hand requirement. It reports postprocess
  quality diagnostics separately from baked-artifact acceptance; a cleaned full
  clip is not itself a final baked artifact.
- The exact RDL contract exposed an ordering bug in support initialization:
  geometry and alignment passed, but a 36 mm rigid-grip spacing miss suppressed
  polish for a 1.45 mm shoulder-span residual. Root-continuity then rejected the
  reference before the later grip projector. Support anatomy/contact polish now
  depends on valid support geometry and alignment only; grip remains an
  independent gate and repair. A focused regression covers that separation.
- After this fix, the retained RDL loop fit reached the full controlled-fit stage
  instead of stopping at `support_reference_projection_incomplete`. The baseline
  controlled-fit variant ran 174.5s and failed its quality checks. Its sibling
  adaptive contact-sequence correction passed the production pre-render gate and
  produced a 95-frame review video. A 15-frame contact sheet showed the complete
  hinge and return with stationary feet.
- The production materialized-output metrics then passed on that correction
  artifact: source pose fidelity passed (P90 joint error 0.072 body ratios),
  source-confirmed support stationarity passed, final render evidence passed, and
  the acceptance decision was `valid`. That deterministic gate invocation used
  a replay-only review item and ranking wrapper to evaluate materialized metrics;
  it did not create production selection evidence. The optional visual-review
  callback was not invoked; the saved production render was inspected directly.
  This replay did not run discovery, WHAM/GVHMR inference, or the normal
  selection/package wrapper, so it establishes a valid retained artifact
  candidate, not a complete live source-to-package generation.
- The scoped PowerShell process E2E passed again after the repair: 1 passed in
  142.31s. It still uses a prepared candidate and normalized-motion fixture for
  upstream boundaries; live discovery, source acquisition, and reconstruction
  remain unverified by that process test.
- The fit remains a measured bottleneck: this RDL replay spent 174.5s in a
  controlled-fit variant that failed, before the 0.3s correction variant passed
  deterministic gates. Reordering or short-circuiting fit work could save time,
  but needs a separate quality-preserving comparison across the agreed exercise
  base. The stopped baseline was not restarted, and no maximum-throughput claim
  is made.

### Retained RDL stale-support replay — 2026-10-05

- A current-code read of the retained RDL fit payload found that
  `materialize_stationary_sole_support` could preserve cached bilateral
  `bodySupport` anchors without reapplying the temporal foot-patch gate. The
  mapped patch evidence contained intermittent full-sole intervals, a toe-only
  interval, and unknown spans on one side; the other side was entirely unknown.
  Full-span ankle tracks did not satisfy the existing full-sole corroboration
  rule, but stale derived anchors remained in the direct fit evidence view.
- The fitter now removes generated foot anchors that current temporal evidence
  does not corroborate, using the same rule as source preparation. Timed source
  contacts and unrelated support joints remain intact. A focused regression
  covers stale bilateral anchors, toe-only evidence, and an all-unknown side.
- Source preparation applies this cleanup before the intermittent/unknown-mode
  early return as well. That prevents retained full-cycle `bodySupport` anchors
  from surviving beside timed contacts when the current patch evidence is
  incomplete; the timed contacts themselves remain available to later stages.
- All 7 tests in `tests/test_body_support_observation.py` passed, Python
  compilation and `git diff --check` passed. The production workout-plan process E2E passed
  after the change (1 passed in 140.87s); it continues to use a prepared
  candidate, cached source/support evidence, normalized-motion fixture, and
  deterministic final-review response.
- A bounded CPU replay of the retained 93-frame RDL fit used the corrected
  support view and ended after 148.3s with `unreachable_conflict`. The `bodySupport`
  check now passes, while contacts, trajectory fit, anatomy, motion continuity,
  and playback/loop checks still fail. No successful current RDL selection or
  package is established by this replay.
- The retained 95-frame contact-sequence-correction render passes video
  encoding checks. Re-evaluating its corrected payload with current source
  support cleanup, contact correction, and the pre-render gate passes with
  source-pose fidelity P90 error 0.072 body ratios. This is a deterministic
  bake candidate only; no final visual review or normal selection/package path
  was run for this re-evaluation.
- Replaying the production preselection filters on the retained baseline and
  correction artifacts removes the failed baseline and keeps the corrected
  sibling. An independent evaluation of the correction's baseline-safety and
  source-stationarity metrics also passes. Normal final review,
  selection-manifest creation, and packaging remain unverified for this RDL
  candidate.
- The RDL stale-support replay itself did not run source search, WHAM/GVHMR
  inference, a visual-review model call, or a throughput campaign. At that replay
  checkpoint, the retained RDL artifact had not established production-path
  acceptance; the separate completed two-exercise arm is recorded below. Maximum
  throughput remains unverified, the interrupted baseline remains stopped, and
  the shared-overlap regression remains closed as recorded above.

### Retained Oct 5 fixed-source production arm — corrected evidence

- The completed shared arm at `build/exercise_motion/speed-harness/20261005-040656-a9f2ab42`
  took 1282.0 seconds and completed one serial two-exercise wave. Its phase
  totals were source 218.0s, generation 443.2s, and final validation 536.0s.
  Both selected artifacts passed acceptance and review-to-package hash parity:
  RDL (95 frames, `bb68faec0b5d65e0e343f9e8c98b24b5b28b6d6ac47d19e06884db5547fea510`)
  and OHP (89 frames, `224daa370203d04f9afcb3607edeac991e85adf38d92d8bcd7c74100fe0b5a43`).
- This arm did run GVHMR inference for both exercises. The selected finalization
  manifests say `reused_processed` because finalization reused the generation
  outputs; the authoritative generation records are under each selected
  artifact's `processing_evidence/generation_checkpoint.json`. They record
  backend `gvhmr`, successful `gvhmr-warm-worker` commands, and inference
  prediction timings. RDL records 320.8s in the reconstruction stage and 4.7s
  in model prediction; OHP records 360.0s in the stage and 1.4s in prediction.
- The harness reported zero reconstruction calls because candidate workspaces
  had been pruned before its post-run manifest snapshot. It did preserve the
  full candidate-generation elapsed sum of 840.4s, which includes cleanup and
  other generation work and must not be called GVHMR inference time. The staged
  wave checkpoint now retains a compact reconstruction timing record per
  candidate so future measurements survive retention cleanup.
- This arm used fixed prepared source candidates and did not measure YouTube
  discovery or downloads. It is a successful production generation/finalize/
  package run, not a search-inclusive E2E or a comparison against baseline.
  The stopped baseline remains stopped, and the earlier shared-overlap arm
  remains a measured regression. Maximum throughput is therefore still
  unproven; this result establishes a successful 1282-second serial reference
  for the two fixed inputs, not a global maximum.

### Oct 5 generator instrumentation and queue follow-up

- The source-funnel analyzer previously divided accepted outputs by summed
  per-manifest candidate time. On the retained shared arm that gave 9.176
  outputs/hour from 784.684 summed candidate seconds, even though the full arm
  wall was 1282.0 seconds. It now requires `--wall-seconds` for the wall rate,
  reports candidate-processing time separately, and correctly gives 5.616
  accepted outputs/hour for this arm. The wall duration comes from the shared
  arm's `wallSeconds` entry in `results.json`.
- Completed staged waves now retain the result of render-prefetch futures that
  had been marked abandoned for finalization, including worker status and
  elapsed time, plus `renderPrefetchDrainSeconds`. The persisted wave wall
  duration and accepted-per-minute metric include the post-finalization drain.
  Worker elapsed time may include queue waits; it is not CPU-time attribution.
  This adds future telemetry and does not retroactively recover the Oct 5
  worker duration.
- On Windows, staged-wave startup now uses a mutex derived from the normalized
  queue-root path, so starting a worker for one workspace no longer holds the
  same long startup lock as every other workspace. Queue publication and idle
  shutdown retain the short legacy lock handoff; queues owned by older workers
  continue using the original global mutex until a new worker advertises lock
  version 2. This structurally removes cross-workspace startup contention; no
  multi-workspace timing benchmark has been run.
- The retained 93-frame RDL fit payload was replayed through the current
  cleanup contact detector without models. Raw coordinates produced mixed
  support for all 93 frames; after the current floor normalization, the
  detector produced 74 double-support frames and 19 right-foot-only frames.
  This does not reproduce an all-airborne detector result. The separate
  retained RDL fit still ends in `unreachable_conflict`, so that fit remains a
  quality failure even though the fixed-source Oct 5 production arm accepted
  and packaged a different 95-frame RDL artifact.
- Focused checks passed for the metric calculation (6), render-prefetch overlap
  and drain accounting (4), and queue admission compatibility/idle handoff (2).
  The prepared-candidate production process E2E also passed (1 in 152.28s),
  covering the PowerShell queue, fit, render, final review adapter, selection,
  and package identity path. It does not exercise live discovery/source
  acquisition or run a fresh WHAM/GVHMR campaign. The interrupted baseline
  remains stopped, and maximum throughput remains unproven.

### Oct 5 height-only contact correction

- A stationary `verticalOnly` / toe-only contact was being admitted to the
  ordinary contact mask and pinned in XYZ, despite the foot-contact policy
  describing that evidence as height-only. The fit now uses a separate
  floor-normal residual at keyframes and playback subframes. Tangential
  coordinates remain free; independent playback validation checks the height
  error. Sequence stabilization follows the same split, and cycle ranking still
  treats these intervals as support when choosing boundaries.
- Fit and sequence-stabilization strategy versions were bumped so artifacts
  validated under the former full-XYZ interpretation are not reused.
- Focused source-evidence, fit-residual, playback, sequence-stabilization, and
  cycle-slicing checks passed (32 tests); edited Python files compile. No app
  tests, live model calls, or GPU campaigns were run for this correction.
- This does not add the separate ankle tangential-anchor constraint for unknown
  patch intervals. The fitter still lacks a shared per-axis projector for that
  evidence; the retained 93-frame RDL replay remains a fit-quality failure.
  Unknown patch spans are still not promoted to full-sole or floor contacts.

### 2026-10-05 architecture and generator audit follow-up

- The production process E2E passed before the airborne-anchor follow-up:
  `test_workout_plan_script_fits_renders_and_packages_reviewed_movement`,
  1 passed in 146.10s at commit `54f2bef4`. It exercises the real workout-plan PowerShell wrapper,
  staged-wave service, fit, render, review parsing, selection, artifact lineage,
  and package serialization. Search, downloads, WHAM output, and VLM decisions
  use deterministic adapters or seeded evidence; this is a process integration
  check, not a live model campaign or visual-quality proof.
- The production process E2E passed again on the final committed tree at
  `5a4e6277` (1 passed in 146.39s), covering both the airborne-anchor fix and
  synchronous active-wave publication. The anchor refactor also passed its
  focused regression and Python compilation; the queue change passed its
  deterministic fake-executor and adjacent lifecycle tests (2 passed).
- Architecture audit: artifact-state transitions and reviewed-to-packaged
  identity are connected and independently checked by the runner and package
  builder. Source-camera projection and endpoint constraints reach the active
  controlled fitter. The staged-wave queue is a workspace-scoped serial worker;
  discovery and source acquisition remain separate scheduler owners, so the
  proposed generator-wide service is still a separate phase.
- Audit correction: omitting `footContactCandidates` from 3D contact constraints
  is intentional because their stationarity is measured in source-image space
  and does not establish camera-depth stationarity. The retained 95-frame RDL's
  source-camera fit has 24 observations for each ankle across the selected
  0.000–3.070s interval, including unknown patch spans. Unknown spans remain
  unknown rather than becoming full-sole or floor contacts. A separate legacy
  identity edge could reuse the same ankle anchor across explicit airborne
  episodes; fit and sequence anchor grouping now scopes reused identities by
  airborne epoch. This does not resolve the retained 93-frame RDL fit failure.
- The retained 93-frame RDL replay is historical (before `2118c3bc` and
  `f26d691d`) and is not a current-code fit result. Its source-confirmed
  baseline-support gate already failed for both feet; the 240s-budget replay
  stopped after 147.6s at `unreachable_conflict`, with 9mm stored contact error,
  66mm playback contact error, 33mm floor penetration, and 47/50mm left ankle/
  foot target RMS. The candidate also had a severe open seam. The fitter returned
  the original pose; the evidence does not show that spending more solver time
  would yield a safe fit, so no support or acceptance gate was weakened.
- Queue retention now expires abandoned unconsumed results after 30 days and
  ambiguous crash records after 90 days, while retaining newer records for
  delayed consumers/recovery. Focused pruning regression passed; code is in
  commit `54f2bef4`.
- The staged-wave worker now synchronously publishes its active request and
  wave IDs before entering the executor. This closes the supervisor shutdown
  race where a fresh heartbeat could still say idle and model services could be
  stopped during an active wave. A fake-executor regression holds back
  heartbeat writes; it and the adjacent queue lifecycle check passed (2 tests).
  This is an ownership-safety fix, not a throughput result. The broader
  discovery-to-package durable scheduler remains a separate phase.
- Maximum throughput remains unverified. The accepted 1282s two-exercise Oct 5
  arm is one serial configuration point, while the overlap arm was slower and
  broke acceptance parity. Its recorded commit was `8a1ed1d3`; the arm also had
  a dirty worktree, so it is not a current-revision throughput measurement.
  The stopped baseline remains stopped. The retained shared arm sampled 99.9%
  RAM, 100% GPU, and 95.6% VRAM, so no extra-concurrency campaign was started;
  throughput promotion still needs a bounded, comparable run when GPU/resource
  budget is available.

### Oct 5 current-code fixed-source live diagnostic

- The `shared` arm at `build/exercise_motion/speed-harness/20261005-081407-439afbde`
  ran from HEAD `3734b1dd` with the fixed RDL+OHP inputs, wave size 2, CPU render
  prefetch enabled, and one serial staged wave. Arm wall time was 1206.6s; phase
  totals were source 246.0s, generation 388.1s, and final validation 504.3s.
  The worktree was dirty from unrelated exercise-library changes, and only one
  of two inputs completed, so the harness marked the arm unqualified.
- OHP completed and was packaged as an 89-frame movement. Its review render
  identity, selection parity hash, package content hash, and decompressed
  package bytes all match SHA-256
  `ad3c858e9b2388c387489e715db54cb7780007e3b931b2ac252275df353f5c37`.
  First accepted output was at 1189.7s; it was materialized at 1195.2s.
- RDL ended `no_selection` after 348.3s of final processing. The confirmed
  source-left foot maps to rig-right for this camera assignment (`swapped`); its
  reconstructed contact range ratio was 0.07796 against the 0.055 limit. The
  source-confirmed support gate rejected drift and the loop bridge also failed.
  The cyclic fit ended after 154.5s with `unreachable_conflict`; the contact
  sequence correction still failed `materialized_loop_bridge_pose_mismatch`.
  This reproduces the fit/support-fidelity failure, not an airborne result from
  the post-normalization continuous-contact detector. The support gate was not
  weakened.
- Although CPU render prefetch was enabled, the wave reported it skipped with
  `source_contact_observation_unavailable`. This arm cannot compare prefetch
  on versus off. The completed OHP and failed RDL do not establish maximum
  throughput; no additional arm was run from this diagnostic.

### Oct 5 current-code RDL continuity and fit follow-up

- Commit `827e5683` fixes the contact-correction seam admission bug. The
  correction gate now receives the exercise motion contract, and a return-to-
  start correction is not added to the review artifacts when it worsens the
  measured loop seam. The regression uses the retained RDL seam values
  (32.09mm baseline, 61.83mm corrected); the focused test, Python compilation,
  and `git diff --check` passed. This prevents a known bad sibling artifact; it
  does not by itself recover the failed RDL.
- Replayed the retained failed RDL's exact 87-frame cycle payload from
  `20261005-081407-439afbde` with the production Python environment, current
  fitter, and a 120-second fit budget. The replay report is
  `build/exercise_motion/replays/20261005-rdl-87-frame-current-fit-report.json`;
  it made zero model calls and ran no reconstruction. It ended in
  `unreachable_conflict` after 125.63s wall / 124.81s in the fit. Anatomy,
  contacts, trajectory fit, temporal quality, root continuity, and playback
  failed; source articulation, body support, support alignment, equipment,
  root travel, height-only contacts, and the loop seam passed. Maximum stored
  contact error was 16.69mm, maximum articulation change 19.29 degrees, and
  target RMS was 74.2mm. Source-camera projection had 22 frames and 286
  observations, including selected-cycle start/end coverage.
- The report has zero bounded-refinement evaluations and stops at the existing
  unreachable-conflict guard. The 120-second value is a solver/refinement
  budget rather than a strict wall cap: optimizer work checks between calls,
  and final validation runs to completion to classify and record the result.
  This replay does not identify a gate-preserving early stop or justify
  increasing the fit budget. A separate 123-frame full-interval replay was not
  used as evidence for this failure because it did not match the failed 87-frame
  cycle.
- No post-`827e5683` source-to-package RDL run or comparable throughput result
  exists. The correction regression is verified locally, but the current
  accepted two-exercise artifact remains the earlier 1282-second serial arm;
  throughput and current-revision package parity remain unverified.

### Oct 5 retained RDL source-support fit audit

- The exact rejected 87-frame fit payload includes one observed full-sole
  contact over frames 10-59 after cycle mapping (source-left mapped to rig
  `right_foot`). The fit pins that foot and ankle, uses 286 source-camera joint
  observations across 22 frames, and adjusts the shared source-projected anchor
  by at most 93.5mm. `supportAnchorObservationCount: 0` counts only confirmed
  body-support joints; it does not count ordinary foot-patch anchors. The fit
  therefore did consume the observed support evidence.
- Its visual body-support observation is `unknown` with
  `support_observation_unparseable`; all remaining foot-patch states are
  `unknown`. The evidence does not establish stationary support across those
  unknown intervals, so the fitter correctly does not promote them to hard
  contacts. The replay still fails anatomy, contact, trajectory, temporal,
  root-continuity, and playback checks, including 93.8mm dense playback contact
  error and 44.3mm floor penetration.
- The earlier accepted RDL package retains four mapped foot-patch intervals
  and an observed visual support response, but its original candidate workspace
  was pruned. The retained successful and failed artifacts are not a controlled
  fit comparison; the available evidence does not isolate support observation
  as the reason for their different outcomes. No support-gate relaxation or
  extra fit budget is justified from this data.

### Oct 5 RDL fit stop-classification correction

- The zero-refinement stop above exposed a control-flow bug in
  `unreachable_without_polish`: its articulation/contact heuristic could call a
  fit unreachable when the optimizer had ended at `time_budget`. On this RDL
  iterate, anatomy and contacts failed, source articulation passed, and
  articulation change was 19.29 degrees, but the optimizer had not completed
  its search. The heuristic returned before the reserved bounded-refinement
  path, so `unreachable_conflict` overstated the evidence.
- Commit `48616adf` requires convergence or explicit refinement-stop evidence
  before that heuristic is decisive. Budget-limited (`time_budget`,
  `solve_phase_budget`, and `evaluation_limit`) iterates remain eligible for the
  existing refinement path when budget remains. The focused regression passed,
  edited Python files compiled, and `git diff --check` passed.
- A post-fix replay of the same 87-frame input with the same explicit
  120-second cap is recorded in
  `build/exercise_motion/replays/20261005-rdl-87-frame-post-stop-fix-report.json`.
  It now ends as `fit_validation_failed` with no unsupported unreachable label,
  but no refinement block ran: initial validation took 18.85s after a
  102.53s solve phase and exhausted the 14.40s polish reserve (124.74s total
  wall). The output still fails anatomy, contacts, trajectory, temporal,
  root-continuity, and playback checks. The production default budget for 87
  frames is 217.5s; that path was not rerun, so any recovery benefit there is
  unverified.
- This is an early-stop classification fix, not an RDL quality repair. The
  retained fit still fails substantial anatomy, contacts, trajectory, temporal,
  root-continuity, and playback checks. Successful RDL generation remains
  unverified; acceptance gates were not weakened.

### Oct 6 retained-pair generator follow-up

- Source support now preserves explicitly observed airborne epochs through
  source-contact normalization, correction-anchor grouping, and reconstructed
  support fusion. Previously, reconstructed foot stationarity could promote a
  whole-clip contact over an explicit flight interval, undoing the source
  contact split. Short-gap anchor reuse is now scoped to the same airborne
  epoch; unknown source states remain unknown. Focused regressions cover
  support fusion and same, different, and missing anchor-group IDs across a
  short flight.
- The controlled fitter's high source-spine-fold stop now distinguishes a
  persistent source defect from a fold that its anatomical initializer has
  explicitly repaired. When initialization reports `passed: true` with no
  remaining violations, the fitter gets its existing bounded retained-interval
  attempt; all physical and playback acceptance gates remain required.
- A bounded CPU replay exercised the retained-interval fallback and improved
  contact, support, trajectory, temporal, equipment, and several anatomy
  checks, but did not pass. To force the retry path, the replay removed the
  persisted artifact state and installed a synthetic whole-clip cycle; its
  large loop-seam failure is therefore not evidence about the original
  production cycle. The replay still has a torso-bend violation at spine1 frame
  67 and a severe left-hand discontinuity. The retained production RDL artifact
  had no accepted cycle proposal and was rejected before final render/review on
  fit, body-support, and support-surface checks. The fallback fix has not yet
  been verified on a current end-to-end RDL generation. No GPU/model calls or
  full pair campaign were run.
- The retained process replay exposed a source-preparation bug when source
  segment detection is disabled: that branch returned before exact-source
  phase validation and pose-reference promotion. A full-source ranked window
  was also needlessly re-encoded, changing its digest and preventing the
  retained source evidence from matching the selected video. The production
  path now validates and promotes evidence in this branch, and copies a window
  byte-for-byte when it covers the full source. A self-contained focused
  regression passed using an exact content-addressed cache entry. The slow pair
  replay was not rerun: its retained OHP evidence has different contract
  semantics from the current generated contract, so re-keying it would be
  unsafe. This fix restores source evidence availability; it does not establish
  that OHP or RDL now passes fitting.
- The fitter's bounded anatomy-projection gate now permits an attempt when
  anatomy is the only structural failure and only playback/temporal checks
  also fail. All source-articulation, contact, trajectory, support, rig, and
  equipment checks must still pass; cyclic clips still need a passing seam.
  Open clips no longer require a seam check that does not apply. The existing
  five-second budget and strict full revalidation remain in force, and the
  projected result is kept only when it clears checks without introducing any
  failure. The focused eligibility regression passed. No retained RDL fit was
  rerun, so this is a safe repair opportunity, not proof of a successful output.
- A CPU-only replay of the retained 123-frame production RDL payload showed the
  eligibility gate could still miss its repair window: initial contact failure
  blocked projection, then bounded contact cleanup cleared the structural
  checks without reconsidering anatomy. The fitter now retries that decision
  once at the top of the bounded-polish loop, still capped at five seconds and
  still requiring a strict failed-check reduction or full acceptance. The
  176.4-second replay exercised the delayed projection and reduced the final
  failures from anatomy/contact/playback/discontinuity to relative-joint-shake
  and motion-discontinuity, with anatomy, contacts, and playback passing. The
  overall fit remains rejected (`applied=false`); this does not resolve RDL
  generation. Its remaining temporal spikes are at the left foot around 1.8s
  and 2.5s. No reconstruction or model calls were made.
- The same replay exposed a final-state regression: after bounded repair had
  reduced the fit to a motion-discontinuity-only failure, the terminal Stage-C
  evaluation continuation worsened the failed-check set and replaced that
  stronger state. Earlier polish already rolled back regressions, but this last
  continuation did not. Continuations now retain a result only when it passes
  or strictly reduces the failed-check set; rejected continuations restore the
  prior coordinates, report, rig state, and session warm start. A focused test
  covers unchanged, regressed, improved, and accepted reports. This preserves
  the best known state but does not repair RDL's remaining temporal failure;
  the retained replay was not repeated after this guard was added.
- Focused regressions passed (`6 passed`), and the edited Python modules and
  tests compiled with `py_compile`. No throughput promotion is claimed.
- Architecture status: reviewed render/package artifact identity is connected
  through the production path; source-evidence-constrained fitting is in place
  and the airborne-epoch integrity gaps above are fixed. The workspace-scoped
  staged-wave service is a concrete long-lived serial worker, not yet a
  generator-wide service for discovery, preview prefetch, or downloads. Queue
  ownership, atomic state, caches, and crash recovery were audited; no new
  persistent-infrastructure gap was found. Broader service migration remains
  a separate phase.
- The retained 123-frame RDL payload showed its source-observed bilateral
  ground stance was only partly materialized: the source-left ankle track was
  stable for the full clip, while source-right was stable over 22/31 samples
  but its leading 29% was occluded. Camera mapping correctly assigns
  source-left to fit-right. The generic 15% leading-coverage rule therefore
  left fit-left unsupported even though the hash-matched visual observation
  confirmed both feet grounded and no patch sample contradicted it. The
  confirmed-contact path now permits up to 30% leading occlusion only while
  retaining the 70% sample, endpoint, and stationary-displacement checks; all
  other callers retain the original 15% rule. Explicit release/partial-sole
  patch states, source-hash mismatch, and intermittent/none contact modes still
  block the added anchor. Focused support regression passed.
- The open-clip replay after bilateral support took 51.9s versus 151.6s for the
  preceding open-clip replay, but the retained artifact has `loop.enabled=false`;
  that replay does not exercise the required cyclic fit. The nested fit report
  showed the original production run had attempted full interval `[0,123)`:
  its source and output phase checks passed, but the fit failed anatomy,
  contacts, shake, playback, and loop seam. A captured-cycle replay after the
  support fix took 168.9s total (119.7s for `[0,123)`, then 46.5s for retained
  interval validation). On the cyclic attempt, fit-left ankle/foot target RMS
  fell from 32.2/45.5mm to 0.1/0mm, contact error fell from 2.04mm to 0.71mm,
  and motion-discontinuity now passes. The seam improved from 195mm and
  6.54m/s to 93.4mm and 3.08m/s, but still fails; anatomy also remains failed
  (`anatomy_chest_attachment`, `anatomy_spine_deviation`, and
  `anatomy_torso_bend`). The retained open interval passes anatomy and
  contacts, but still fails playback: interpolated grip spacing is 11.3mm
  against a 9.4mm limit. Its 176mm position difference and 5.06m/s boundary
  mismatch are open-interval diagnostics, not the cyclic candidate's seam
  target. Right-wrist and right-hand shake exceed their limits by 1.2% and
  0.3%. The cyclic attempt also misses playback body-support range (5.88mm
  against 5mm) and interpolated grip (20.6mm against 9.4mm), so its remaining
  failures are not isolated to seam closure. Phase preflight is not fit
  acceptance, and no output is promoted. The fit report now identifies joints
  failing the shake limit to make follow-up diagnosis direct.
- The next captured-cycle replay showed that the first fit's 120-second budget
  left too little time for bounded repair after validation. Soft-solve scheduling
  reserves a frame-scaled validation allowance (capped at 25s) and the normal
  polish window; the extra plant-polish allowance is opportunistic so it does
  not starve the main fit. Validation-local projections and later Stage-A/B/C
  repair use separate deadlines inside the same outer budget. The 123-frame
  CPU replay used a 60.3s soft-solve budget and 24.6s validation allowance;
  actual validation took 26.0s. Contact cleanup then ran, and the cyclic result
  passed contacts and motion-discontinuity, but remained rejected on anatomy,
  joint shake, playback, and loop seam. Its playback seam was still 118mm and
  3.84m/s. The retained open interval passed anatomy and contacts, but remained
  rejected on joint shake and playback; interpolated grip spacing was 11.3mm
  against a 9.4mm limit. Total replay time was 166.8s, with no model or
  reconstruction calls. The earlier 35.7s soft-solve allocation regressed
  motion-discontinuity, so reserving the optional 22s plant window up front was
  removed. The allocation change is not an accepted-generation or throughput
  win. Focused deadline regressions and `py_compile` passed; no GPU campaign was
  run.
- A 45-second CPU replay of the retained open RDL interval tested a smoothness
  residual on the rigid-pair playback grip projection. It retained the bar-grip
  repair without increasing jerk: interpolated spacing fell from 11.32mm to
  9.12mm, inside the 9.41mm limit, while contact and body-support checks
  remained valid. The fit still rejects on `relativeJointShake`; bounded shake
  cleanup reopened other checks and was rolled back. This is a safe partial
  playback improvement, not a successful RDL output. The generic projection
  change passed its focused regressions and Python compilation; no model or
  reconstruction calls were made.
- The follow-up exposed a quality-state bug in Stage-C free-temporal polish: it
  could replace a `jointShake` failure with a different `relativeJointShake`
  failure and keep the candidate. It now retains that block only when the full
  failed-check set strictly decreases. The bounded 45.1-second RDL replay now
  keeps the no-spike state and passes grip (8.81mm vs 9.41mm), contacts,
  playback, anatomy, and the relative-shake gate. It still rejects on the
  absolute joint-shake gate: right wrist is 1.0124× its limit and right hand is
  1.0009×. The output is improved but remains unaccepted; broader smoothing is
  not safe because it introduced severe local spikes.
- A follow-up source-support audit ruled out the suspected absolute-height
  detector bug: both RDL ankle tracks pass its pre-normalization ground cutoff.
  The right-side continuity gap is 0.667s (over the 0.5s merge limit), and
  unobserved foot-patch samples are `unknown`, not airborne. The current
  production path can reconcile hash-matched full-sole ground evidence with
  stable ankle tracks; the retained fit payload predates that rematerialization.
  Do not widen the generic floor threshold based on this stale payload.

### Oct 6 shake-aware grip projection and architecture status

- The retained 123-frame RDL fit failed only because the playback rigid-pair
  correction raised right-wrist/right-hand acceleration just beyond the existing
  absolute `jointShake` limit. The bounded projection previously optimized grip
  spacing and correction smoothness without seeing that limit. Commit
  `6199f736` passes the same per-joint RMS limits into that projection and adds
  a small excess-only residual with a 0.1% target cushion; the validator and its
  acceptance threshold are unchanged.
- Replayed the exact retained input (SHA-256
  `183ad0bc37647ad1dd632c4c2727f0c88d6fe335fce8d54aa5b3e3ea02249796`) with a
  139s candidate cap. The fit completed in 41.691s with `applied=true`, and all
  19 reported checks passed, including `jointShake`, `relativeJointShake`,
  equipment, playback, contact, anatomy, body support, and motion discontinuity.
  Interpolated grip spacing is 8.807mm against a 9.409mm limit, and playback
  contact error is 0.864mm. It used zero model calls and zero reconstruction
  runs. The exact replay report and payload are
  `build/exercise_motion/replays/20261006-rdl-grip-shake-aware-v4-report.json`
  and `build/exercise_motion/replays/20261006-rdl-grip-shake-aware-v4.json`.
- This qualifies the retained fit only. It does not establish a fresh source
  discovery/reconstruction run, reviewed render, selected artifact, package
  parity, or an end-to-end throughput change. The agreed OHP+RDL pair still has
  no current-code two-exercise production result; run that only after the
  bounded production-path verification stage.
- Current architecture audit: artifact lineage and final state transitions are
  connected through fit, final review, selection, package construction, and
  independent package audit. Source constraints reach the fitter; strict source
  endpoint coverage is conditional on a declared selected interval, while a
  full-clip fit can proceed without camera projection evidence. Staged-wave
  baking and opt-in WHAM/GVHMR workers are queue-backed long-lived services;
  discovery, prefetch, downloads, and legacy individual jobs remain transient
  PowerShell jobs. Persistent process/GPU/CPU ownership, ambiguous-job recovery,
  and content-verified caches are present for the implemented services. Thus the
  generator-wide service queue remains a separate phase; these audit findings
  do not claim it is implemented or prove maximum throughput.

### Oct 6 RDL fit-to-pre-render corrections

- The retained RDL showed two production-path mismatches. The final body-rotation
  screen compared fitted joints against raw `sourceJoints`, although controlled
  fitting had used `controlledArticulationReferenceJoints`. The screen now uses
  that exact fit reference when complete and keeps the raw-source fallback for
  legacy payloads.
- The rigid-pair grip projector described itself as distal-arm-only but omitted
  the shoulder joints from its torso lock set. It could rotate the shoulders,
  add a 10.8mm torso-bend violation to the support reference, then leave stale
  pre-projection anatomy status in the report. The shoulders are now locked;
  grip and interpolated-plant projections are retained only after anatomy,
  support geometry, alignment, grip, and contact checks all pass. Failed local
  projections roll back to their validated input pose.
- Final materialized acceptance now explicitly requires a terminal movement
  state. Intermediate pre-render checks still permit a nonterminal full-clip
  parent because cycle selection/rebake has not happened yet.
- Replayed the exact 123-frame RDL input (SHA-256
  `183ad0bc37647ad1dd632c4c2727f0c88d6fe335fce8d54aa5b3e3ea02249796`). The
  CPU-only fit completed in 43.658s, applied successfully, and passed all 19 fit
  checks. Both local support projections passed their complete reference gates.
  Current deterministic pre-render validation then passed in 2.059s with no
  rejection reasons; no model or reconstruction calls were made. Replay evidence
  is `build/exercise_motion/replays/20261006-rdl-grip-shake-aware-v7-report.json`,
  `build/exercise_motion/replays/20261006-rdl-grip-shake-aware-v7.json`, and
  `build/exercise_motion/replays/20261006-rdl-grip-shake-aware-v7-prerender.json`.
- This is still a validated full-clip parent, not an accepted final RDL
  movement: the contract requires a `cyclic_rebake`, while this artifact remains
  `full_clip_bake` with `terminal=false`. Its seam check correctly reports
  `requires_cycle_repair`. Cycle selection/rebake, reviewed render, package
  parity, and an OHP+RDL production-script E2E remain unverified. No throughput
  claim follows from this fit replay.

### Oct 6 correction: retained RDL fixture is not a valid acceptance base

Direct inspection of all three cached chronological contact sheets for the
`retained_pair_process_e2e_20261006_022134` RDL case shows a floor pickup,
standing lockout, and return to the floor. The fixture's contract instead requires
an upright start with the bar at hip height, a hip hinge, and return to that
upright posture. The selected clip does not establish that required repetition.

The cached source-review payload is a fixture response: all scores are 0.99,
all contract-match flags are true, and its reason is
`Retained Barbell Romanian Deadlift fixture.` This is not independent visual
approval. The cached video has 123 frames at 29.97 fps (about 4.1 seconds), with
SHA-256 `0cf054adb5d21c79ba3c91f30e555e9bf8ff30c3281504185462214e3f4ceb6b`;
there is no later repetition available in this cached file to select instead.

Exclude this retained case from successful RDL generation and accepted-output
throughput comparisons. Its solver profiles and focused processing regressions
can still demonstrate local implementation behavior, but neither successful
open-clip fitting nor repeated failed cyclic fitting establishes that the
generator meets the RDL contract. Do not tune fitting further to make this
fixture pass. Replace the source with an inspected contract-matching repetition
and make its deterministic review fixture reflect that actual evidence before
resuming the agreed OHP/RDL production-script acceptance comparison.

Replacement-source candidate found locally: `yQbSQCkhvTM`, retained in
`exercise-library/barbell-romanian-deadlift/selected/`. Its 124-frame input shows
an upright start, hip hinge, and continuous return to upright; denser inspection
of frames 100–122 confirms the return is visible. Source SHA-256 is
`8fc700728af368f782a6bd217bbe36beb99b46282cd3396ca5ae2a3607f4be01`.
The selected directory retains `processing_evidence/motion.raw.json` and
`motion.cleaned.json`, plus exact-source pose and phase evidence. Candidate
identities and hashes are recorded in
`build/exercise_motion/replays/20261006-replacement-rdl-source-candidate.json`.
Its old generated artifact is explicitly invalid (`supported_body_moves`,
`support_surface_geometry_mismatch`); reuse reconstruction evidence only after
checking its source/timeline identity, not that old generated acceptance. The
replacement has not yet passed the current production path or rendered review.

### Oct 6 replacement-source fit checkpoint

Commit `dba8d6e9` increases the bounded interpolated neck-clearance repair from
four to eight attempts, retaining its deadline and unchanged acceptance limits.
The measured guard overshoot was converging but the old cap discarded the repair.
Two focused neck-clearance regressions pass, including the extracted replacement
trajectory; dense interpolation clears the guard without moving limbs.

A replay through `fit_controlled_motion` on the freshly rebuilt replacement
full-input candidate, with a 120-second budget, completes in 32.04 seconds wall
time (29.67 seconds reported fit time). It reports
`validated_controlled_motion`, with all 19 fit checks passing. Existing playback
grip repair succeeds after the neck repair; playback velocity jump is
0.0000007901 m/s, contact error 0.00002170 m, and grip spacing error 0.00877323 m
against the unchanged 0.00891076 m limit. Evidence is retained under
`build/exercise_motion/replays/20261006-replacement-rdl-neck-fix-fit-{report,output}.json`.

This proves a valid full-clip intermediate fit, not terminal generation or an
accepted-output throughput improvement. Its cyclic seam still requires repair.
Cycle selection/rebake, production-rendered review, packaging, and the corrected
two-exercise production-script E2E remain unverified. The earlier 98.92-second
failed bake fit is a different invocation and is not a controlled speed comparison.

### Oct 6 replacement-source cyclic bake and render checkpoint

The production `bake_preview_loops_with_playwright` path was replayed on exact
source frames 6–122 of the inspected replacement, with the retained reconstruction
and matching support evidence, one adaptive variant, and a 180-second deadline.
The cyclic fit passed all 20 checks, but its first pre-render gate rejected reuse:
lineage rematerialization changed the selected start timestamp from `0.2` to
`0.19999999999999996`. Pose identity was unchanged. Commit `b124e2ee` canonicalizes
selected-interval identity timestamps to nanoseconds, finer than the existing
microsecond provenance checks. The regression preserves invalidation for a changed
interval; validation limits are unchanged.

A fresh production replay after the fix completed in 142.21 seconds, including
98.55 seconds reported fitting. All fit checks and the pre-render deterministic
gate passed. Artifact state is terminal `cyclic_rebake` with complete
`full_clip_bake → cycle_selection → cyclic_rebake` lineage. The actual production
renderer exported `source-1.adaptive-baseline.webm` (194765 bytes) and review metadata
under `build/exercise_motion/replays/20261006-inspected-rdl-cycle-bake/review/`.
An inspected chronological contact sheet extracted from that video shows the
upright/hinge/return sequence. A contact sheet does not establish temporal quality.
No final model approval, packaging, or corrected OHP/RDL production-script E2E is
claimed. These timings are checkpoint measurements, not a controlled throughput
comparison or proof of a successfully packaged movement.

### Oct 6 genuine replacement-source final validation

A single bounded local-model validation through `final_output_validation_metrics`
used the configured Qwen3.5-9B vision model, the actual replacement source window,
and both current-runtime final render views. It completed in 55.95 seconds with
`passed=true`, no rejection reasons, and required source evidence passing. The
independent source observations corroborate barbell equipment and upright start,
hip hinge, and upright return. Final render evidence binds the exact 117-frame
skeleton (SHA-256 `547c5a62692e148775e35524ce9e3bb851609e336a9269df28f52a3dd0d92617`)
and source frames 6–122. Evidence is retained in
`20261006-inspected-rdl-cycle-bake/genuine_final_validation_checkpoint.json`.

Visual findings are advisory under the existing production policy: low-poly
faceting and absence of rendered equipment. They are not a new motion approval
score or proof of temporal quality. This checkpoint uses genuine model responses,
not retained fixture approvals. Packaging and the corrected two-exercise
production-script E2E still remain unverified; no accepted-output throughput claim
is made from this isolated checkpoint.

### Oct 6 full acceptance and isolated production packaging checkpoint

The outer `apply_materialized_output_acceptance_gate` exposed missing fidelity
evidence despite the preceding fit and visual-review checks: without phase-file
metadata it redetected poses on the trimmed video, conflicting with the retained
parent-camera observations. Commit `8dc92b98` falls back to the hash-verified
`exact_source_pose_reference.json` and selects the artifact's explicit source-time
interval before computing phase evidence. Two focused reuse tests and compilation
pass. No fidelity thresholds or camera provenance checks changed.

The actual outer acceptance replay then returned `valid`, no rejection reasons,
and passing source-output fidelity with comparable-frame ratio 1.0. It took
179.82 seconds including genuine review; this is not a controlled speed result.
Its selection manifest is `production_acceptance_selection_manifest.json` in the
replacement cyclic-bake workspace.

An isolated packaging checkpoint executed the production PowerShell functions
`Assert-SelectedSkeletonReviewParity` and `Record-PackagedSkeletonReviewParity`,
extracted from the current generator script, on a copy of the accepted artifact.
The independent `audit_artifact_package_state` returns `passed=true`,
`approvedMovement=true`, `artifactClass=cyclic_rebake`, and
`packagedArtifactClass=packaged_movement`, with no rejection reasons. The copied
117-frame skeleton is byte-identical to the rendered and reviewed artifact.
Evidence and the copied package are under the cyclic-bake workspace's
`packaging-checkpoint/`. This verifies the owning packaging functions and parity,
not execution of the whole workout-plan script or the corrected OHP/RDL E2E.

### Oct 6 Press fixture source-boundary correction

The retained Press source (SHA-256
`72dd58149eda88169da0955b8a03609704e6c91fd8ac4dd1d664d5538877fb15`)
visibly contains complete dumbbell presses, but starts overhead and contains
multiple repetitions. The prior selected interval, source frames 187–271
(6.233–9.033 seconds), has overhead endpoints in the retained source pose evidence.
Its fixture contract requires hands at shoulder height and bent elbows at both
boundaries. Exclude that old selection from contract-matching acceptance evidence;
its local solver profiles remain local computational evidence only.

Observed shoulder-height extrema occur near 1.750, 4.625, and 7.375 seconds.
Those are boundary proposals for selecting an actual contract-matching repetition,
not newly approved clips. The full source can be retained for discovery, but
cannot receive an unconditional whole-clip approval. Audit evidence and the
inspected source contact sheet are retained as
`20261006-ohp-source-fixture-audit.json` and `20261006-ohp-retained-source-audit.jpg`
under `build/exercise_motion/replays/`. The corrected two-exercise E2E remains open.

### Oct 6 discovery-service queue decision

The production scheduler runs source discovery in separate PowerShell jobs,
bounded by `DiscoveryWorkers` (default up to four when the pose prefilter does
not use the GPU). Staged baking uses a separate durable, single-consumer queue
in `staged_wave_service.py`. Routing discovery through that bake queue would
serialize discovery behind unrelated bake requests and reduce the scheduler's
existing discovery width.

On the configured Python environment, five fresh-process samples importing
`exercise_motion_pkg.cli` and `exercise_motion_pkg.youtube` took 0.719–0.931
seconds (median 0.784 seconds). This is only process/import overhead; it does
not measure model startup, discovery wall time, or campaign throughput. The
measurement does not justify replacing parallel discovery with one serial
queue. Keep the existing discovery workers and independent bake queue unless
a multi-consumer discovery service can preserve the configured worker width
and a comparable production run shows startup overhead materially affects
wall time. Discovery queue service work therefore remains partial rather than
claiming the queue-backed-service architecture is complete.
