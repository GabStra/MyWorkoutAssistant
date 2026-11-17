import copy
import json


import pytest

from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION, POLICY_VERSION,
    _contact_timeline_candidates, _validated_contact_timeline_response,
    validated_body_support_contact_timeline,
)
from exercise_motion_pkg.support_geometry import support_contact_readiness


def _case(tmp_path):
    from nonfoot_support_fixture import build_nonfoot_support_fixture
    video, _reference_path, pose_ref, payload = build_nonfoot_support_fixture(
        tmp_path, frame_count=6, sides=("right",),
        observation_overrides={"leftFoot": "moving", "leftFootSurface": "unknown",
            "rightFoot": "stationary_forefoot", "rightFootSurface": "raised_surface"})
    evidence = payload["sourceFootSupportEvidence"]
    candidates = [r for r in _contact_timeline_candidates(pose_ref, evidence)
                  if r.get("landmark") == "region" and r.get("contactRegion") == "foot"]
    assert len(candidates) == 6
    for row in candidates:
        row["sourceFrameIndex"] = round(row["sourceTimeSec"] * 10)
        row["sourceFps"] = 10.
    normalized = _validated_contact_timeline_response(json.dumps({"samples": [
        {"sampleId": r["sampleId"], "contactState": "direct_contact",
         "surface": "raised_surface", "visible": True} for r in candidates]}), candidates)
    assert normalized and all(r["contactRegion"] == "foot" for r in normalized)
    evidence["bodySupportObservation"]["contactTimeline"] = {"schemaVersion": 1,
        "policyVersion": CONTACT_TIMELINE_POLICY_VERSION,
        "source": "exact_source_visual_contact_timeline", "sourceClock": "video_frame_zero_seconds",
        "status": "observed", "sourceVideoSha256": pose_ref["sourceVideoSha256"], "samples": normalized}
    return video, pose_ref, evidence


def test_raised_foot_region_rows_resolve_timed_support_without_joint_pins(tmp_path):
    video, pose_ref, evidence = _case(tmp_path)
    result = support_contact_readiness({"sourceFootSupportEvidence": evidence},
        source_pose=pose_ref, source_video_path=video)
    assert result["passed"]
    assert result["raisedFootRegionSupportSides"] == ["right"]
    coverage = result["stationaryContactCoverage"]["right"]
    assert coverage["observedSampleCount"] == 6
    assert coverage["intervalCoverageProven"] is True
    assert coverage["jointAnchorsCreated"] is False
    assert [r["side"] for r in coverage["timedEvidence"]] == ["right"] * 6
    assert not evidence.get("supportContacts")


@pytest.mark.parametrize("failure", ["hash", "clock", "gap"])
def test_raised_foot_region_readiness_fails_closed_on_provenance(tmp_path, failure):
    video, pose_ref, evidence = _case(tmp_path)
    corrupted = copy.deepcopy(evidence)
    timeline = corrupted["bodySupportObservation"]["contactTimeline"]
    if failure == "hash":
        timeline["sourceVideoSha256"] = "b" * 64
    elif failure == "clock":
        timeline["samples"][0]["sourceFrameIndex"] += 1
    else:
        timeline["samples"].pop(2)
    validated = validated_body_support_contact_timeline(
        corrupted["bodySupportObservation"], expected_video_sha256=pose_ref["sourceVideoSha256"])
    assert (validated is not None) if failure == "gap" else (validated is None)
    result = support_contact_readiness({"sourceFootSupportEvidence": corrupted},
        source_pose=pose_ref, source_video_path=video)
    assert not result["passed"]
    assert result["unresolvedSides"] == ["right"]
