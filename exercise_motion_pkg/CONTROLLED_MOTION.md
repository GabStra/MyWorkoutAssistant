# Controlled motion fitting

`controlled_motion.fit_controlled_motion` is the default final motion stage in
`constrain_baked_payload_to_source_articulation`. It consumes a complete, regularly
sampled SMPL joint sequence. The legacy path remains available through
`use_controlled_motion_fit=False`. Enabling this default does not resume a batch
run or publish existing comparison artifacts into the exercise library.

## Cycle selection and orientation continuity

For enabled loops, observed cycle proposals must match pose, direction and
stationary-contact state, retain at least 90% of each significant excursion,
and preserve root travel. The endpoint is exclusive to avoid duplicating a
sample at the join. Contact intervals and frame indices are rebased; original
source frame/time identity is retained. At most three proposals share one solve
time budget. Rejection retains the complete original input, not a cropped failure.

Bone orientation is transported continuously from frame to frame. Independently
aligning each downward bone to body-up introduced unobserved axial half-turns;
in the walking-lunge input the largest initial rotation step fell from 178 to
14 degrees with transport. This is a position-only orientation convention, not
an estimate of real axial twist.

The seam objective matches consecutive velocity increments, not identical end
poses. Playback compares seam displacement with neighboring frame steps so
ordinary fast motion is not mistaken for a teleport. Floor, contact and anatomy
checks still include the interpolated seam. No fades are generated.

## What it solves

- **Changing proportions:** calibrate each bone length once using its temporal
  median, then average matching left/right lengths. Hip and collar socket
  offsets are centered and fixed in the pelvis/chest frame. The neck attachment
  is initialized in the calibrated chest plane, preserving head direction.
  Forward kinematics reconstructs positions from root translation and local
  rotations, making bone-length variation zero by construction.
- **Malformed source anatomy:** before motion fitting, anatomical projection
  corrects invalid torso/joint configurations using fixed-length forward
  kinematics and the closest observed joint positions. Impossible segment
  proportions are clamped to the existing model bounds; feasible proportions
  and feasible poses are preserved. Root positions and the observed hip-center
  to neck direction remain fixed during this initialization. Pelvis rotation
  can adjust so repairing back curvature does not stand a forward-leaning
  torso upright. No world-up or general tilt limit is introduced. The subsequent trajectory solver restores observed contacts
  and enforces temporal quality. Both passes share the existing time budget.
  The smoothing target uses this corrected rig.
  Source-independent structure residuals constrain the torso and articulation
  during fitting and interpolated playback. Final validation rejects violations
  even when output and source agree. Limits for this simplified model are:
  bilateral length mismatch at most 5%, socket lateral offset at most 6% of
  socket width, spine deviation at most 15% of pelvis-to-neck distance, each
  spine segment within 60 degrees of that axis, hip-center/waist/neck bend
  at most 35 degrees (also checked against the shoulder midpoint), neck
  attachment within 30 degrees of the chest-to-collar direction, shoulder
  midpoint between 35% and 125% of the chest-to-neck rise, neck internal angle at least
  95 degrees, and knee/elbow internal angles at least 15 degrees. Bone-length
  drift beyond the larger of 5 mm or 1.5% is rejected independently of source.
  Broad display-rig length ratios also reject equally malformed left/right
  limbs: upper arm/thigh 0.4–1.2, forearm/upper arm 0.55–1.25, shin/thigh
  0.65–1.4, and ankle-to-foot/shin 0.15–0.65.
  These are conservative model acceptance bounds, not clinical ROM limits or
  proof of human feasibility. Position-only joints do not determine axial
  twist or all directional joint limits. Intentional unilateral movement,
  torso inclination, and world orientation remain independent of body symmetry.
  Failed fits retain their input for diagnosis but cannot pass final acceptance.
  If the WHAM articulation reference is itself malformed, it is corrected as
  well. `correctedAnatomicalReferenceJoints` and `anatomicalSourceRepair` carry
  the correction and its audit; original source fields remain available.
  Source-fidelity constraints use the corrected reference so they cannot force
  the solver back into the original error. The final gate validates that
  reference independently. Scene placement transforms it consistently, and
  reuse digests cover it. The v20 strategy invalidates earlier fit reports.
- **Rapid fluctuations and rebound:** a positive Gaussian kernel supplies a
  non-ringing target. Output acceleration and jerk are penalized in the fit;
  smoothing is not followed by an independent contact correction.
  Root-relative acceleration/jerk and unit body-axis acceleration receive
  separate costs. Reducing noisy root travel cannot compensate for new limb
  twitches or torso rotation noise in the acceptance checks.
- **Small secondary sway:** overlapping 1.2-second local PCA windows act in a
  fixed body basis after linear travel is removed. Only small components clearly
  subordinate to the main component are attenuated. There is no preferred world
  axis, exercise-name rule, or left/right pose mirroring.
- **Settling:** quiet intervals add a soft body-relative velocity cost. Small
  monotonic progress is excluded from holds, and holds never establish a contact.
- **Contacts:** explicit stationary episodes supply one anchor per connected
  stance. Releases are free, toe contacts constrain only the named point, and
  unrepresented heel contacts reject the fit. Contact errors, anatomy and smooth
  motion are solved together. The validator uses the same immutable source stance
  anchors; it never derives a new anchor from a repaired foot trajectory.
  Observations are placed using a common translation derived from those anchors,
  retaining body articulation. The translation correction is interpolated during
  releases, preserving flight and travel without inventing contacts. Pinned target
  points use the anchors directly; the original source-articulation reference is
  unchanged. This removes the conflict between trusting a drifting foot target
  and requiring the same foot to stay stationary.
  Before freezing the anchors, a small linear solve registers all observed
  stance episodes together with root translation. Its temporal reference comes
  from the original source root in the baked coordinate frame. Without that
  reference, continuous input root motion is preserved; only discontinuous input
  receives a smoothed reference. It preserves flight
  dynamics rather than minimizing root motion toward rest. This addresses
  discontinuities caused by independent placement of successive support episodes.
  A final constant height offset places the lowest registered stationary-foot
  anchor above the floor when needed. Relative support heights and articulation
  are unchanged; an airborne extremity cannot establish that offset.
- **Intersections and range loss:** capsule clearance contributes to the solve
  at stored frames and quarter-frame samples. Significant observed excursions have a soft
  lower bound, preventing stronger settling from shortening the exercise.

In the default bake path, the source-articulation guard supplies the initialization.
The unified fitter then owns contacts and temporal cleanup; the older positional
spike, foot-heading, contact and sequence-denoising passes are skipped. Existing
reports from those passes are archived as input provenance. No local repair runs
after fitting. Upstream WHAM reconstruction and browser preprocessing remain.

`controlledArticulationReferenceJoints` retains the original source articulation,
while `controlledSourceJoints` retains the registered fitter input in baked coordinates for
immutable stance anchors. This prevents successive repairs from accumulating an
unbounded change relative to the original articulation. Both references are
included in the accepted-output digest. A failed fit retains the original pose.

## Validation and limits

Results are accepted atomically. Validation checks source-relative articulation,
head orientation and temporally supported bend branches, collisions, fixed bone
lengths, contact error below 0.5 mm, trajectory fit error, retained significant
joint/root excursions, per-joint acceleration and aggregate jerk. Balance is an
advisory diagnostic only. Per-frame source bone-length matching is deliberately
superseded by the calibrated rig invariant; other anatomy checks remain active.

Default solve bounds are 25 evaluations and 1.5 seconds per input frame,
with a 150-second minimum and 300-second maximum. Explicit caller timeouts
override that default. Timeout/rejection returns
the original payload and an explicit report, never a partially accepted pose.
The pose digest prevents repeated fitting of the same accepted output.

This is a deterministic kinematic fit, not a physics simulator or a learned
exercise-form classifier. It cannot identify every unwanted slow sway from one
ambiguous sequence. It does not estimate equipment mass or invisible axial twist.
Looping clips use cyclic acceleration/jerk constraints and seam closure in the
same solve. Last-to-first quaternion interpolation is checked too. Unsafe seams
reject the candidate with `loop_requires_cycle_repair`; fades are never generated.
Clips with intentional net travel may need another cycle or a separate trajectory
representation rather than forced closure.

The comparison browser uses quaternion interpolation and forward kinematics for
`fixedRig` payloads, avoiding bone shrinkage between samples. Both Kotlin
viewers share the same optional rotation-based playback, verified against Python
FK samples. Validation samples four subdivisions per frame, including the loop
seam, and checks contacts, floor clearance and anatomy. Quarter-frame contact/floor
constraints are part of fitting, not an independent correction after smoothing.
Final acceptance revalidates playback and the rig/pose/loop digest.
It also independently screens abrupt root translation using the second difference
of pelvis positions, normalized to 30 Hz and leg length. Constant-speed travel is
unrestricted. This animation continuity policy is separate from balance or force
estimation. Root smoothing retains the aggregate translation weight of the full
skeleton when split from relative limb motion.

## Run a comparison

```powershell
$env:PYTHONPATH=(Get-Location).Path
$env:OPENBLAS_NUM_THREADS='1'
python -m exercise_motion_pkg.controlled_motion input.json build/controlled-comparison
```

Outputs: `motion.json`, `report.json`, and `preview.html`. A rejected comparison
has exit status 2 and displays the retained input. The bake API uses the fitter
by default; `use_controlled_motion_fit=False` selects the legacy path.

Focused tests cover fitting, placement registration, cycle selection, quaternion
playback, production integration and legacy rollback. They preserve deliberate
asymmetry, sideways travel, jumping, small slow articulation and original source
references. Run the timed fitting tests without concurrent large comparisons:
CPU contention can exhaust an explicit wall-clock budget even when an isolated
run passes. This does not change production timeout or validation requirements.

## Rollout evidence and limits

The current comparison set passes both internal fitting and independent final
validation: thruster, lateral lunge, walking lunge, woodchopper, Russian twist and
curtsy lunge. The walking-lunge comparison uses a fresh WHAM + SMPLify
reconstruction; the previous reconstruction was not repairable under the source
fidelity constraints. Input rejection must not be treated as successful repair.

Source/render contact sheets use matching source times and the production mesh
at two camera angles. The thruster source-video comparison completed two
continuous loops with opacity 1. These checks establish broad movement-phase
correspondence and measured continuity, not exact recovery of unseen 3D posture.

Current artifacts are under `build/smplify-trial/integrated-controlled-v17`,
`build/smplify-trial/walking-reconstruction`, and
`build/smplify-trial/controlled-rollout/integrated-v17`. The local thruster preview
is `build/smplify-trial/repaired-preview.html`; its previous version is backed up.
No comparison is automatically published into the exercise library.

Three distinct failures motivated the placement design:

- Global translation noise masked newly introduced limb jitter in a world-space
  average. Separate limb, body-axis and root checks prevent that masking.
- The thruster's drifting target required at least 3.24 cm RMS error to satisfy
  stationary contacts, above its 1.98 cm fidelity limit. Contact-consistent
  targets resolve that contradiction without relaxing articulation checks.
- Independently placed stance episodes caused a large root jump when support
  observations briefly disappeared. Joint registration removes that reset while
  preserving the gaps; it does not infer additional contacts.

Finite-iteration fitting also uses a small positive capsule-clearance margin;
independent subframe collision tolerances are unchanged. Balance remains
advisory, equipment is not inferred, and legitimate asymmetry is not mirrored.

Observed full comparison times on this host were approximately 85-304 seconds,
including final validation. This is a quality improvement, not evidence that the
entire library batch runs faster. The nonlinear fit remains the expensive stage.
