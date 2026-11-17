from copy import deepcopy
import json
import pytest

from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION,
    POLICY_VERSION,
    _contact_timeline_candidates,
    _validated_contact_timeline_response,
    observed_body_support_contacts,
    validated_body_support_contact_timeline,
)
from exercise_motion_pkg.bake_and_rank import body_support_contract_evidence_status


DIGEST = "a" * 64
UPPER_BACK_CONTRACT = {"bodySupportRequirements": {"required": [
    {"region": "upper_back", "side": "center", "surface": "bench"},
]}}


def _pose(*, moving_shoulders=False):
    frames = []
    for index in range(6):
        dx = index * .02 if moving_shoulders else 0.
        joints = {
            "left_shoulder": [.35 + dx, .30], "right_shoulder": [.65 + dx, .30],
            "spine1": [.50 + dx, .34], "spine2": [.50 + dx, .42],
            "spine3": [.50 + dx, .50], "pelvis": [.50 + dx, .62],
            "left_hip": [.43 + dx, .62], "right_hip": [.57 + dx, .62],
        }
        frames.append({"sourceTimeSec": index / 10., "joints": joints,
                       "jointConfidence": {name: .95 for name in joints}})
    return {"coordinateSpace": "normalized_image_xy", "imageWidth": 640,
            "imageHeight": 480, "frames": frames}


def _evidence(pose, candidates, *, choice="direct_contact", surface="bench"):
    for row in candidates:
        row["sourceFrameIndex"] = round(row["sourceTimeSec"] * 10.)
        row["sourceFps"] = 10.
    response_rows = [{"sampleId": row["sampleId"], "contactState": choice,
                      "surface": surface if choice == "direct_contact" else "none",
                      "visible": choice != "unknown"}
                     for row in candidates]
    rows = _validated_contact_timeline_response(
        json.dumps({"samples": response_rows}), candidates)
    observation = {
        "status": "observed", "source": "exact_source_visual_support_observation",
        "sourceVideoSha256": DIGEST, "policyVersion": POLICY_VERSION,
        "sourceClock": "video_frame_zero_seconds",
        "observation": {"upperBack": "stationary_support",
                        "upperBackContactSurface": "bench"},
        "contactTimeline": {
            "schemaVersion": 1, "policyVersion": CONTACT_TIMELINE_POLICY_VERSION,
            "source": "exact_source_visual_contact_timeline",
            "sourceVideoSha256": DIGEST, "sourceClock": "video_frame_zero_seconds",
            "status": "observed", "samples": rows,
        },
    }
    return {"bodySupportObservation": observation, "sourceVideoSha256": DIGEST}


@pytest.mark.parametrize('timeline_policy', [6, CONTACT_TIMELINE_POLICY_VERSION])
def test_region_owned_upper_back_evidence_clears_requirement_without_joint_anchors(timeline_policy):
    pose = _pose(moving_shoulders=True)
    evidence = {"bodySupportObservation": {
        "status": "observed", "source": "exact_source_visual_support_observation",
        "sourceVideoSha256": DIGEST, "policyVersion": POLICY_VERSION,
        "sourceClock": "video_frame_zero_seconds",
        "observation": {"upperBack": "stationary_support",
                        "upperBackContactSurface": "bench"},
    }, "sourceVideoSha256": DIGEST}
    candidates = _contact_timeline_candidates(pose, evidence)
    regions = [row for row in candidates if row.get("landmark") == "region"]
    assert len(regions) == 3
    assert [row["poseFrameIndex"] for row in regions] == [0, 3, 5]
    assert all(row["side"] == "center" and row["contactRegion"] == "upper_back"
               and row.get("jointName") is None and row["expectedSurface"] == "bench"
               and row["sourceTrackStationary"] is False for row in regions)
    assert all(row["regionPoints"] for row in regions)
    evidence = _evidence(pose, regions)
    evidence['bodySupportObservation']['contactTimeline']['policyVersion'] = timeline_policy
    pose_reference = {"sourceVideoSha256": DIGEST, "pose": pose}
    assert validated_body_support_contact_timeline(evidence["bodySupportObservation"],
                                                   expected_video_sha256=DIGEST)
    assert body_support_contract_evidence_status(
        UPPER_BACK_CONTRACT, evidence, source_pose=pose_reference)["status"] == "passed"
    assert observed_body_support_contacts(evidence["bodySupportObservation"], pose_reference) == set()
    from exercise_motion_pkg.body_support_observation import (
        BODY_SUPPORT_ANCHORS, materialize_body_support,
    )
    payload = {"sourceFootSupportEvidence": deepcopy(evidence),
               "jointNames": [*BODY_SUPPORT_ANCHORS, "neck", "spine1", "spine2", "spine3"],
               "frames": []}
    materialize_body_support(payload, pose_reference, UPPER_BACK_CONTRACT)
    assert "bodySupport" not in payload["sourceFootSupportEvidence"]
    assert not payload["sourceFootSupportEvidence"].get("supportContacts")

    wrong_pose_clock = deepcopy(evidence)
    wrong_pose = deepcopy(pose)
    wrong_pose["frames"][3]["sourceTimeSec"] += .02
    assert body_support_contract_evidence_status(
        UPPER_BACK_CONTRACT, wrong_pose_clock,
        source_pose={"sourceVideoSha256": DIGEST, "pose": wrong_pose})["status"] == "insufficient_evidence"


def test_regional_evidence_fails_closed_for_unknown_surface_source_or_clock():
    pose = _pose()
    observation = {"status": "observed", "source": "exact_source_visual_support_observation",
                   "sourceVideoSha256": DIGEST, "policyVersion": POLICY_VERSION,
                   "sourceClock": "video_frame_zero_seconds",
                   "observation": {"upperBack": "stationary_support",
                                   "upperBackContactSurface": "bench"}}
    candidates = [row for row in _contact_timeline_candidates(
        pose, {"bodySupportObservation": observation}) if row.get("landmark") == "region"]
    pose_reference = {"sourceVideoSha256": DIGEST, "pose": pose}

    unknown = _evidence(pose, deepcopy(candidates), choice="unknown")
    assert body_support_contract_evidence_status(
        UPPER_BACK_CONTRACT, unknown, source_pose=pose_reference)["status"] == "insufficient_evidence"

    wrong_surface = _evidence(pose, deepcopy(candidates), surface="floor")
    assert body_support_contract_evidence_status(
        UPPER_BACK_CONTRACT, wrong_surface, source_pose=pose_reference)["status"] == "insufficient_evidence"

    foreign = _evidence(pose, deepcopy(candidates))
    foreign["bodySupportObservation"]["contactTimeline"]["sourceVideoSha256"] = "b" * 64
    assert validated_body_support_contact_timeline(
        foreign["bodySupportObservation"], expected_video_sha256=DIGEST) is None
    assert body_support_contract_evidence_status(
        UPPER_BACK_CONTRACT, foreign, source_pose=pose_reference)["status"] == "insufficient_evidence"

    wrong_clock = _evidence(pose, deepcopy(candidates))
    wrong_clock["bodySupportObservation"]["contactTimeline"]["samples"][0]["sourceFrameIndex"] += 1
    assert validated_body_support_contact_timeline(
        wrong_clock["bodySupportObservation"], expected_video_sha256=DIGEST) is None


def test_region_positive_without_verified_source_pose_remains_insufficient():
    pose = _pose()
    observation = {"status": "observed", "source": "exact_source_visual_support_observation",
                   "sourceVideoSha256": DIGEST, "policyVersion": POLICY_VERSION,
                   "sourceClock": "video_frame_zero_seconds",
                   "observation": {"upperBack": "stationary_support",
                                   "upperBackContactSurface": "bench"}}
    candidates = [row for row in _contact_timeline_candidates(
        pose, {"bodySupportObservation": observation}) if row.get("landmark") == "region"]
    evidence = _evidence(pose, candidates)
    assert body_support_contract_evidence_status(
        UPPER_BACK_CONTRACT, evidence)["status"] == "insufficient_evidence"


def test_legacy_bilateral_shoulder_point_evidence_remains_compatible():
    pose = _pose()
    observed = {"status": "observed", "source": "exact_source_visual_support_observation",
                "sourceVideoSha256": DIGEST, "policyVersion": POLICY_VERSION,
                "sourceClock": "video_frame_zero_seconds",
                "observation": {"upperBack": "stationary_support",
                                "upperBackContactSurface": "bench"}}
    candidates = [row for row in _contact_timeline_candidates(
        pose, {"bodySupportObservation": observed}) if row.get("landmark") == "joint"]
    for row in candidates:
        row["sourceFrameIndex"] = round(row["sourceTimeSec"] * 10.)
        row["sourceFps"] = 10.
    response = json.dumps({"samples": [
        {"sampleId": row["sampleId"], "contactState": "direct_contact",
         "surface": "bench", "visible": True} for row in candidates]})
    rows = _validated_contact_timeline_response(response, candidates)
    observed["contactTimeline"] = {
        "schemaVersion": 1, "policyVersion": 5,
        "source": "exact_source_visual_contact_timeline", "sourceVideoSha256": DIGEST,
        "sourceClock": "video_frame_zero_seconds", "status": "observed", "samples": rows,
    }
    evidence = {"bodySupportObservation": observed, "sourceVideoSha256": DIGEST}
    assert body_support_contract_evidence_status(
        UPPER_BACK_CONTRACT, evidence,
        source_pose={"sourceVideoSha256": DIGEST, "pose": pose})["status"] == "passed"


def test_side_specific_joint_contact_path_is_unchanged():
    observed = {"status": "observed", "source": "exact_source_visual_support_observation",
                "sourceVideoSha256": DIGEST, "policyVersion": POLICY_VERSION,
                "sourceClock": "video_frame_zero_seconds",
                "observation": {"leftHand": "stationary_support",
                                "leftHandContactSurface": "fixed_bar"},
                "contactTimeline": {
                    "schemaVersion": 1, "policyVersion": CONTACT_TIMELINE_POLICY_VERSION,
                    "source": "exact_source_visual_contact_timeline",
                    "sourceVideoSha256": DIGEST, "sourceClock": "video_frame_zero_seconds",
                    "status": "observed", "samples": [{
                        "sampleId": f"wrist-{i}", "sourceTimeSec": i / 10.,
                        "sourceFrameIndex": i, "sourcePoseFrameIndex": i, "sourceFps": 10.,
                        "side": "left", "landmark": "joint", "jointName": "left_wrist",
                        "contactRegion": "hand", "contactState": "direct_contact",
                        "surface": "fixed_bar", "visible": True,
                        "sourceTrackStationary": True,
                    } for i in (0, 1)],
                }}
    evidence = {"bodySupportObservation": observed, "sourceVideoSha256": DIGEST}
    contract = {"bodySupportRequirements": {"required": [
        {"region": "hand", "side": "left", "surface": "fixed_bar"},
    ]}}
    assert body_support_contract_evidence_status(contract, evidence)["status"] == "passed"
