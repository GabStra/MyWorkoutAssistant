# Whole-body contact repair

The frame-83 thruster regression was introduced by contact IK. Pinning both feet
preserved knee flexion while changing hip and ankle articulation enough to fold
the shins almost onto the feet. Temporal smoothness and constant bone lengths
did not detect it.

## Runtime order

1. Preserve the pre-contact pose as the immutable repair reference.
2. For stationary full-sole contacts, construct foot targets directly from the
   supplied contact episodes. Do not first solve the legs to reach those targets.
   Mixed toe/heel cases can still use the existing geometric proposal generator.
3. Evaluate the proposal independently. If needed, optimize all available body
   joints together over the sequence: source displacement, output acceleration,
   bone lengths, hip/knee/ankle/shoulder/elbow articulation, inner collision
   capsules and floor clearance. Balance is diagnostic only and does not alter
   the objective or the pose.
4. Contact coordinates are removed from the free variables. Releasing or rolling
   contacts are not converted into stationary contacts. A contact manifold the
   optimizer cannot represent is rejected rather than silently released.
5. Evaluate the resulting coordinates independently of optimizer cost/success.
   Acceptance requires bone errors <= 2 mm, exact pinned contacts, floor errors
   <= 2 mm, torso pair-distance errors <= 5 mm and no anatomical/collision
   failure. Balance warnings do not block.
6. On rejection or timeout, retain the pre-contact pose and emit
   `requiresReconstruction`. This is a diagnostic fallback, not an approved
   animation. The final materialized gate blocks it. A favourable VLM verdict
   cannot override anatomical failures. Balance-only warnings remain advisory.
7. The final kinematic gate repeats physical checks after later processing.
   Policy/cache identity includes the new modules and bake version 31.

Knees and elbows are dependent two-bone coordinates, using a transported source
bend plane instead of independent Cartesian hinge positions. Pole corrections
stay within 60 degrees of that plane and have a temporal correction-speed cost.
Near-straight source poles use transported reliable neighbors. A coupled reach
seed initializes the body within both leg constraints; knee/elbow angle envelopes
come from the same source bounds used by final validation. The independent check
also rejects body-relative hinge branch flips even when joint angles match.
All articulation tolerances use the original pre-repair pose, so intermediate
heading or smoothing passes cannot spend the same tolerance twice. The solver
also constrains introduced root-relative wrist/ankle jitter against that source.

When no torso point is pinned to a support, the source torso is represented by
one translation and rotation per frame. Spine, hip and shoulder attachment
points cannot shear independently. The observed shape can still flex and twist
across frames; this does not flatten legitimate spinal curvature or impose
bilateral symmetry. Supported torso points retain the Cartesian representation
and must pass the same final torso shape check. Output acceleration is penalized
for every joint, including the pelvis and reconstructed hinges. Smoothing only
the correction had retained source noise and allowed visible root shaking below
the old spike thresholds. These constraints prevent repair-induced deformation;
they do not correct every error already present in the reconstructed source.

Position acceleration alone underweights rotation about a narrow hip axis. The
solver therefore also regularizes second differences of dimensionless lateral
and up body axes, without Euler angles or wrap discontinuities. Both solver
acceptance and the final export gate check introduced body rotation roughness
against the pre-repair source, with a sampling-rate-normalized absolute floor.
This catches coherent torso wobble that neither bone lengths nor isolated limb
spike checks detect. Source-relative comparison only detects added noise; it
does not certify the original reconstruction or treat it as video evidence.

The unsupported head follows the torso transform with its per-frame source
articulation. It cannot wobble freely while chasing its previous world position;
intentional head movement remains in the source-relative trajectory. A supported
head remains pinned and is not overwritten. Independent final validation limits
added head articulation relative to the body to 15 degrees (plus numerical room),
as a repair budget rather than a clinical neck limit. The root acceleration
penalty is stronger inside consecutive bilateral stationary support frames;
source knee/hip envelopes still preserve the exercise's phase and depth.

The solver uses sparse sequence optimization, at most 80 objective evaluations,
and a 90-second deadline checked between residual evaluations. It does not start
new video/model inference on its own or resume a paused library run.

## Limits of the current implementation

- Anatomical checks are conservative repair limits and source-relative angular
  limits, not a complete learned or clinical joint-limit manifold. Hip/shoulder
  axial rotations cannot be fully characterized from joint centres alone.
- Collisions use inner capsules, including distal foot/shin overlap. They do not
  certify that every triangle of the displayed mesh is collision-free.
- The dynamic support screen includes COM acceleration and skips flight/contact
  gaps. It uses approximate body mass fractions and a conservative foot support
  envelope, without equipment mass, angular momentum, contact forces, friction,
  or a full inverse-dynamics model. Its warnings are non-blocking diagnostics,
  not a claim that the motion is mechanically impossible. Hand/seat support and unilateral/partial
  foot support are not evaluated by this reduced balance screen.
- A failed bounded numerical solve is **unresolved**, not proof that the motion
  has no feasible solution. Do not relax anatomical limits just to clear it.
- Full inverse dynamics, exact renderer mesh collision, a learned joint prior,
  and automatic alternate reconstruction are follow-up architecture work, not
  capabilities claimed by this implementation.

## Regression evidence

`tests/fixtures/thruster_contact_frame83.json` retains pre-contact and broken
coordinates. Tests cover the smooth/frozen bad pose, source coordinate rotation,
constant bone stretching, contact release/rolling, airborne support exclusion,
repair success, timeout rejection, and final acceptance independent of VLM
approval. The original thruster artifact must be revalidated; prior favourable
smoothness/contact reports are not sufficient acceptance evidence.
