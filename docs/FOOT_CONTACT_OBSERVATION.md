# Observed foot contacts

The exact-source analysis runs a local MediaPipe Full pose pass to observe
ankle, heel and forefoot landmarks. It supplements the existing YOLO body pose;
it does not replace the reconstruction model. Install the `motion` extra in the
motion Python environment. The model is downloaded once to the existing pose
model cache. No video is sent to a remote service.

Decoded-frame observations are cached by video SHA-256 and observation policy.
`EXERCISE_MOTION_FOOT_LANDMARK_MODEL` can select a local model; its content hash
also enters the cache key. Exact-source validation policy 29 invalidates older
ankle-only evidence. Post-reconstruction loading incorporates available depth
alignment without repeating landmark inference.

The classifier reports `full_sole`, `toe_only`, `heel_only`, `airborne`, or
`unknown`. Image and world landmark geometry must agree relative to an observed
stance calibration. Low visibility, source-person mismatch, insufficient
calibration and disagreements remain unknown. Flight additionally requires
timestamp-local depth separation and visible clearance. Sparse depth is not
interpolated into a dense contact signal.

These remain inferred contact states, not force measurements. Calibration from
stationary support can be ambiguous, particularly when no flat stance is seen.
The landmarks cannot resolve the exact lateral-edge contact patch. Camera
motion, occlusion and monocular depth errors can still reduce reliability.

Full-sole constraints keep the rigid foot horizontal. Toe contact fixes the toe
height while permitting heel lift; heel contact uses a virtual heel pivot
consistent with the current shoe length. Tangential locking requires separate
stationarity evidence. Whole-body reach fitting preserves rigid leg lengths
and the existing shin-relative ankle envelope. Unknown/airborne intervals are
not silently filled by the preview's reconstructed-speed locking heuristics.

The selected-artifact repair script refreshes these observations, stores the
evidence with the skeleton and selection manifest, and rerenders the preview.
If MediaPipe is unavailable, `footPatchEvidence.available` is false with an
explicit reason; legacy evidence is retained, not presented as observed contact.
