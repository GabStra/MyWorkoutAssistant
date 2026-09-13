import copy

import pytest

from exercise_motion_pkg import bake_and_rank as bake


def anatomical_gate():
    return {
        "passed": False,
        "rejectionReasons": ["raw_wham_kinematic_artifact"],
        "kinematicPlausibilityMetrics": {
            "severeArtifact": True,
            "artifactReasons": ["physical_pose_constraint_violation"],
            "physicalConstraints": {
                "passed": False,
                "reasons": ["anatomy_bilateral_proportions", "anatomy_spine_deviation", "anatomy_torso_bend"],
            },
        },
    }


@pytest.mark.parametrize("extra", ["floor_penetration", "anatomy_degenerate_bone", "unknown_physical_failure"])
def test_unowned_physical_failure_cannot_enter_anatomical_repair(extra):
    gate = anatomical_gate()
    gate["kinematicPlausibilityMetrics"]["physicalConstraints"]["reasons"].append(extra)
    assert not bake.raw_wham_motion_gate_allows_cleaned_recovery(gate)
    assert not bake.motion_gate_allows_pending_anatomical_repair(gate)


@pytest.mark.parametrize("remaining_failure", [None, "raw_wham_source_pose_joint_mismatch"])
def test_generation_defers_only_anatomy_to_fitter_and_preserves_failed_validation(tmp_path, monkeypatch, remaining_failure):
    raw, cleaned = tmp_path / "raw.json", tmp_path / "cleaned.json"
    raw.touch()
    original = anatomical_gate()
    cleaned_gate = copy.deepcopy(original)
    if remaining_failure:
        cleaned_gate["rejectionReasons"].append(remaining_failure)
    calls = []

    def evaluate(path, **kwargs):
        calls.append(path)
        return copy.deepcopy(original if path == raw else cleaned_gate)

    monkeypatch.setattr(bake, "evaluate_raw_wham_motion_gate", evaluate)
    result = bake.evaluate_generated_motion_recovery_gate(
        raw_motion_path=raw, cleaned_motion_path=cleaned,
        source_pose_reference_path=tmp_path / "missing.json",
        exercise_motion_contract=None, exercise_name="Squat",
    )
    assert calls == [raw, cleaned]
    assert result["passed"] is (remaining_failure is None)
    assert result["cleanedRecovery"]["passed"] is False
    assert result["cleanedRecovery"]["cleanedMotionGate"]["passed"] is False
    assert original["passed"] is False
    if remaining_failure is None:
        assert result["pendingAnatomicalRepair"]["finalValidationRequired"] is True
    else:
        assert "pendingAnatomicalRepair" not in result


def test_unrepaired_temporal_noise_is_not_deferred_to_anatomical_projection():
    gate = anatomical_gate()
    gate["kinematicPlausibilityMetrics"]["artifactReasons"].append("root_translation_discontinuity")
    assert bake.raw_wham_motion_gate_allows_cleaned_recovery(gate)
    assert not bake.motion_gate_allows_pending_anatomical_repair(gate)


def test_grip_and_temporal_defects_reach_their_owner_but_source_mismatch_does_not():
    gate = {'passed': False, 'rejectionReasons': ['raw_wham_rigid_two_hand_spacing_instability',
        'raw_wham_kinematic_artifact'], 'kinematicPlausibilityMetrics': {
            'severeArtifact': True, 'artifactReasons': ['limb_velocity_spike_penalty'],
            'distalStep': {'thresholdExceedanceCount': 8, 'maxConsecutiveThresholdExceedanceCount': 5}}}
    assert bake.motion_gate_allows_pending_controlled_repair(gate)
    assert bake.raw_wham_motion_gate_allows_cleaned_recovery(gate)
    for reason in ['raw_wham_source_support_posture_mismatch', 'unknown_failure']:
        failed = copy.deepcopy(gate)
        failed['rejectionReasons'].append(reason)
        assert not bake.motion_gate_allows_pending_controlled_repair(failed)


def test_only_geometry_derived_leg_orientation_can_reach_controlled_repair():
    gate = {'passed': False, 'rejectionReasons': ['raw_wham_kinematic_artifact'],
            'kinematicPlausibilityMetrics': {'severeArtifact': True,
                'artifactReasons': ['bone_orientation_discontinuity'],
                'boneRoll': {'orientationSource': 'exported_forearms_and_rendered_leg_frames',
                             'events': [{'bone': 'right_hip->right_knee'}]}}}
    assert bake.motion_gate_allows_pending_controlled_repair(gate)
    assert gate['passed'] is False
    for events in ([], [{'bone': 'left_elbow->left_wrist'}], [{'bone': 'unknown'}]):
        failed = copy.deepcopy(gate)
        failed['kinematicPlausibilityMetrics']['boneRoll']['events'] = events
        assert not bake.motion_gate_allows_pending_controlled_repair(failed)


def test_pending_grip_repair_does_not_mark_cleaned_motion_valid(tmp_path, monkeypatch):
    raw, cleaned = tmp_path/'raw.json', tmp_path/'cleaned.json'
    raw.touch()
    gate = {'passed': False, 'rejectionReasons': ['raw_wham_rigid_two_hand_spacing_instability'],
            'kinematicPlausibilityMetrics': {'severeArtifact': False, 'artifactReasons': []}}
    monkeypatch.setattr(bake, 'evaluate_raw_wham_motion_gate', lambda *args, **kwargs: copy.deepcopy(gate))
    result = bake.evaluate_generated_motion_recovery_gate(raw_motion_path=raw, cleaned_motion_path=cleaned,
        source_pose_reference_path=tmp_path/'missing.json', exercise_motion_contract=None, exercise_name='Movement')
    assert result['passed']
    assert result['pendingControlledRepair']['finalValidationRequired']
    assert not result['cleanedRecovery']['cleanedMotionGate']['passed']
