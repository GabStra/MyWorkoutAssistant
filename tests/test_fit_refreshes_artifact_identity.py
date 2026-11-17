from __future__ import annotations

import copy

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg import body_support_observation, controlled_motion, scene_placement
from exercise_motion_pkg import support_geometry
from exercise_motion_pkg.artifact_state import (
    cycle_selection_evidence,
    validate_artifact_state,
)


def test_applied_full_fit_refreshes_cyclic_identity_and_preserves_cycle_lineage(monkeypatch):
    contract = {
        "completionMode": "return_to_start",
        "bilateralExecutionAuthority": "structured_definition",
        "bilateralExecution": {"stance": "stationary_bilateral"},
    }
    payload = {
        "kind": "wearPreviewSkeleton",
        "fps": 30.0,
        "frameCount": 4,
        "jointNames": ["pelvis"],
        "rootJoint": "pelvis",
        "loop": {
            "enabled": True,
            "sourceStartFrame": 0,
            "sourceEndFrame": 3,
            "sourceStartTimeSec": 0.0,
            "sourceEndTimeSec": 0.1,
        },
        "frames": [
            {
                "timeSec": index / 30.0,
                "sourceTimeSec": index / 30.0,
                "sourceFrameIndex": index,
                "joints": {"pelvis": [0.0, 1.0, 0.0]},
                "sourceJoints": {"pelvis": [0.0, 1.0, 0.0]},
            }
            for index in range(4)
        ],
    }
    parent = copy.deepcopy(payload)
    parent["loop"]["enabled"] = False
    evidence = cycle_selection_evidence(
        parent,
        {
            "type": "detected_cycle",
            "startFrame": 0,
            "endFrame": 3,
            "startTimeSec": 0.0,
            "endTimeSec": 0.1,
            "durationSec": 0.1,
        },
    )
    bake.artifact_state_for_baked_payload(
        payload,
        contract=contract,
        selection_class=bake.CYCLE_SELECTION,
        selection_evidence=evidence,
        source_parent_payload=parent,
    )
    original_state = copy.deepcopy(payload["artifactState"])

    monkeypatch.setattr(bake, "exercise_motion_contract_requires_rigid_paired_hands", lambda _: False)
    def condition_source_articulation(_, proposed, **__):
        conditioned = copy.deepcopy(proposed)
        conditioned.frames[1].joints["pelvis"] = (0.0005, 1.0, 0.0)
        return conditioned, {"applied": True, "constrainedJoints": ["pelvis"]}

    monkeypatch.setattr(
        bake,
        "constrain_to_source_articulation_envelope",
        condition_source_articulation,
    )
    monkeypatch.setattr(support_geometry, "declare_support_requirements", lambda *_: None)
    monkeypatch.setattr(body_support_observation, "materialize_body_support", lambda *_: None)
    monkeypatch.setattr(body_support_observation, "materialize_hand_support", lambda *_: None)
    monkeypatch.setattr(body_support_observation, "materialize_knee_support", lambda *_: None)
    monkeypatch.setattr(body_support_observation, "materialize_ankle_support", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(body_support_observation, "materialize_observed_ground_contacts", lambda *_: None)
    monkeypatch.setattr(body_support_observation, "calibrate_material_sole_floor", lambda value: value)
    monkeypatch.setattr(controlled_motion, "can_reuse_controlled_motion", lambda _: False)
    monkeypatch.setattr(scene_placement, "normalize_scene_placement", lambda value: value)

    def fit(value, **_kwargs):
        validate_artifact_state(
            value["artifactState"], movement_payload=value, source_parent_payload=parent
        )
        conditioning = value["artifactState"]["selectionEvidence"][
            "controlledMotionFitInputConditioning"
        ]
        assert conditioning["kind"] == "source_conditioned_fit_input"
        assert conditioning["sourceArticulationEnvelope"]["applied"] is True
        assert conditioning["canonicalExecutionPolicy"] == {"stance": "stationary_bilateral"}
        assert conditioning["canonicalExecutionPolicy"] == value["canonicalExecution"]
        assert conditioning["sourceArtifactIdentity"] == original_state["selectionEvidence"]["cyclicRebake"]
        assert conditioning["preparedFitInputIdentity"] == value["artifactState"]["selectionEvidence"]["cyclicRebake"]

        unrecorded = copy.deepcopy(value)
        unrecorded["frames"][0]["joints"]["pelvis"][0] += 0.1
        try:
            validate_artifact_state(
                unrecorded["artifactState"], movement_payload=unrecorded, source_parent_payload=parent
            )
        except ValueError:
            pass
        else:
            raise AssertionError("unrecorded fit-input frame changes must invalidate lineage")

        fitted = copy.deepcopy(value)
        fitted["frames"][1]["joints"]["pelvis"][0] += 0.001
        return fitted, {"applied": True, "checks": {"fixture": True}}

    monkeypatch.setattr(controlled_motion, "fit_controlled_motion", fit)
    result, _ = bake.constrain_baked_payload_to_source_articulation(
        payload,
        exercise_motion_contract=contract,
    )

    validate_artifact_state(result["artifactState"], movement_payload=result, source_parent_payload=parent)
    assert result["artifactState"]["selectionEvidence"]["fullClipBake"] == original_state["selectionEvidence"]["fullClipBake"]
    assert result["artifactState"]["selectionEvidence"]["cycleSelection"] == original_state["selectionEvidence"]["cycleSelection"]
    assert result["artifactState"]["selectionEvidence"]["cyclicRebake"] != original_state["selectionEvidence"]["cyclicRebake"]
    assert result["frames"][1]["joints"]["pelvis"][0] == 0.0015
    assert payload["artifactState"] == original_state
