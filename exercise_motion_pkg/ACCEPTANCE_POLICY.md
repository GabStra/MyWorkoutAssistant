# Motion acceptance safeguards

Generation and retained-artifact revalidation use `decide_acceptance` through the materialized acceptance gate. Numeric failures remain blocking even when visual review is uncertain. Required but unavailable evidence and unresolved reviews cannot approve a selection. Unresolved review does not count as a reconstruction failure or queue a source recut.

Retained verdicts bind source bytes, skeleton bytes, selection timing/settings, resolved contract/context, renderer signature, and validation policies. Old markers without this identity require revalidation. Refresh clears copied approvals before editing. `scripts/promote_validated_motion_artifact.py` checks the identity before and after copying and preserves the previous selection in a backup directory.

Generated contract fields are advisory in review prompts. Field authority is recomputed from the requested name, ignoring model-supplied provenance. Explicit single-implement and single-arm qualifiers remain separate. Equipment is inspected in the source; skeleton renders intentionally omit props. This is a conservative foundation, not a complete structured representation of every exercise-definition qualifier.

Visual responses require typed verdict fields. A rejected review gets at most one additional fresh review using the same evidence. Only common rejection tags supported by body-motion observations can be corroborated. Disagreement, malformed responses, unsupported claims, and review errors remain unresolved. Removing a contradicted rejection does not create approval. Both responses are retained. Agreement by the same model is not proof of correctness; correlated mistakes and false approvals remain possible.

The structural invariant runs after all refinement operations, including late equipment/contact corrections. It rejects changed frame topology, nonfinite joint coordinates, and increased maximum bone-length variation, rolling back the proposed refinement. This prevents that class of introduced damage; it does not repair existing source/reconstruction errors or replace visual validation.

## Verification checkpoint

The saved Curl replay preserved maximum bone-length variation (about 4.43%). The Thruster replay proposed increasing variation from about 5.60% to 39.34%; the final invariant rolled it back. Replays are under `build/exercise_motion/controlled-regeneration/acceptance-architecture-canary`. Neither replay was promoted or visually approved by this check.

Focused tests cover identity invalidation, guarded promotion, missing evidence, deterministic rejection priority, contract authority, review disagreement, malformed responses, source-recut suppression, final geometry rollback, and existing temporal/source-review behavior.

Four older materialized-gate assertions still fail, including with the new acceptance decision block removed: paired-hand baseline handling, complete-cycle endpoint mismatch, dominant-joint selection label, and parent-phase capture rejection tags. These require separate fixture/behavior reconciliation; the full Python suite has not been run.

## Repair implementation checkpoint

The late Thruster stretch was traced to `_align_core_for_same_phase_bilateral_travel`: independently moving spine, hip, and shoulder positions changed connected bone lengths. Core alignment now projects onto the original bone lengths and solves the connected chains with fixed endpoints. Leg-driven core alignment preserves shoulders and arms too, preventing a shoulder correction from introducing an elbow snap near extension. Infeasible corrections are reduced.

`repair_limb_bend_bursts` repairs isolated elbow/knee bend-direction reversals up to 120 ms, using stable surrounding poses. The solver preserves endpoints and per-frame bone lengths. It skips sustained rotations, insufficiently bent limbs, gaps, and invalid timelines. It runs through the existing temporal and source-fidelity transaction checks. It does not infer the correct direction of a persistent ambiguous twist.

Paired-hand correction now follows the moving body coordinate frame instead of pinning a shared implement to a world-space direction. In the saved Curl case, hand-spacing variation fell from 0.1072 m to numerical zero while passing source fidelity.

The current repair script saves spike-only and foot-contact-only changes, starts subsequent repairs from the current artifact rather than an old backup, and invalidates retained approval after modification.

The final repaired bakes are under `build/exercise_motion/controlled-regeneration/repair-canary-v2`. Both Curl and Thruster passed kinematic, source-pose fidelity, support, and structural-invariant checks. Source-reference SHA-256 values matched the retained source videos. Thruster's baseline limb-velocity failure was absent in the repaired bake. Metric inputs include joint names and fps; an earlier diagnostic summary omitted joint names and did not evaluate the intended joints.

These are repaired candidates, not promoted library selections. Remaining work includes independent final visual revalidation, source replacement/recutting for confirmed source defects, and broader typed definition/source-observation coverage. No claim is made that every outstanding exercise is repaired or that occasional VLM errors are eliminated.
