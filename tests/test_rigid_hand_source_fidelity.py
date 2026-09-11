import json
from pathlib import Path

from exercise_motion_pkg import structural_refinement as refinement
from exercise_motion_pkg.motion_io import load_motion_json


def test_rigid_hand_proposal_cannot_replace_source_faithful_curl(tmp_path):
    fixture = json.loads((Path(__file__).parent / "fixtures/rigid_hand_curl_regression.json").read_text())
    path = tmp_path / "motion.json"
    path.write_text(json.dumps(fixture["motion"]))
    before = load_motion_json(path)
    proposed, _ = refinement._stabilize_rigid_paired_hand_spacing(before)
    assert proposed.frames != before.frames
    retained, audit = refinement._accept_source_preserving_refinement_step(
        before, proposed, source_pose_payload=fixture["sourcePose"],
        step_name="rigid_paired_hand_spacing", preserve_rigid_constraints=True,
    )
    assert not audit["accepted"]
    assert retained.frames == before.frames
    assert audit["articulationConstraint"]["reason"] == "rigid_proposal_requires_atomic_validation"
