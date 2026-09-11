# Sequence stabilization

`sequence_stabilization.py` runs after anatomical and contact repair. It has no
exercise-name rules. The animation policy removes rapid variation even when it
is periodic, coordinated across joints, or a large single-frame spike.

A fourth-order zero-phase Butterworth low-pass creates the joint-position target
at 3 Hz (limited to 20% of the sample rate for low-rate inputs). Filtering uses
seconds, not a fixed frame count. No residual decomposition, amplitude exemption,
or raw-extremum restoration can reintroduce rapid fluctuations. Slow trajectories
remain; rapid intentional motion is also attenuated by the requested policy.

The target uses Cartesian joint tracks so changing parent frames cannot convert
directional corrections into endpoint motion. A bounded sequence projection
preserves incoming bone lengths, source articulation limits and explicit stationary
contacts. Skeleton coordinates independently check that at least 95% of the
filtered movement range remains. Noise acceptance measures the same Cartesian
high-frequency residual that the target removes.

Acceptance also requires independent physical and final kinematic checks. A
rejected proposal retains the incoming clip and reports the reason; it must not
be described as successfully cleaned. Large corrections can require reconstruction
when source anatomy constraints prevent filtering. A pose digest prevents repeated
processing. The solve is bounded to 35 evaluations and 30 seconds.

Shoulder structural repairs use the SMPL upper-chest-to-collar attachment, not a
neck-to-collar surrogate. Head/neck edits must not drag shoulder attachment points.
This preserves the rig connection; shoulder-to-head distance can still change with
head and clavicle articulation.

Looping remains independent of filtering; this does not construct a seamless loop.
Unrepresented heel contacts, irregular sampling, unresolved upstream anatomy and
synthetic loop bridges are retained. Axial rotation not present in joint tracks is
not inferred. No VLM or new model inference is triggered.

Bake cache version 31 and module fingerprints identify this policy. Focused tests
cover rapid coherent and isolated motion, single-frame spikes, slow motion,
multiple frame rates, asymmetric travel, anatomy, contacts, and repeat-processing.
