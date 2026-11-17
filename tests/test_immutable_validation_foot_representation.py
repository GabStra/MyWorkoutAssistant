import copy
import json
from pathlib import Path

from exercise_motion_pkg import controlled_motion
from exercise_motion_pkg.native_foot_geometry import native_foot_geometry_from_prior

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/native_foot_geometry_v1.json").read_text(
        encoding="utf-8"))


def _capture_validation_payload(monkeypatch):
    seen = []

    def stop_at_readiness(working_payload):
        seen.append(working_payload)
        return {"reason": "test_readiness_stop"}

    monkeypatch.setattr(
        controlled_motion, "source_foot_patch_pose_binding_failure", stop_at_readiness)
    return seen


def test_legacy_validation_does_not_inject_inferred_foot_geometry(monkeypatch):
    seen = _capture_validation_payload(monkeypatch)
    prior = copy.deepcopy(FIXTURE["sourcePrior"])
    payload = {"sourceFootMarkerPrior": prior}

    validated, report = controlled_motion.fit_controlled_motion(
        payload, _validation_candidate={"fixedRig": {}})

    assert report["reason"] == "test_readiness_stop"
    assert "nativeFootGeometry" not in seen[-1]
    assert seen[-1]["sourceFootMarkerPrior"] is prior
    assert "nativeFootGeometry" not in validated
    assert "nativeFootGeometry" not in payload


def test_generation_still_promotes_and_calibrates_inferred_foot_geometry(monkeypatch):
    seen = _capture_validation_payload(monkeypatch)
    payload = {"sourceFootMarkerPrior": copy.deepcopy(FIXTURE["sourcePrior"])}

    controlled_motion.fit_controlled_motion(payload)

    geometry = seen[-1]["nativeFootGeometry"]
    promoted = native_foot_geometry_from_prior(FIXTURE["sourcePrior"])
    assert geometry["anatomyCalibration"]["sourceGeometry"] == promoted
    assert geometry["anatomyCalibration"]["method"] == "bilateral_normalized_mean_v1"
    assert "nativeFootGeometry" not in payload


def test_authoritative_candidate_geometry_is_preserved_exactly(monkeypatch):
    seen = _capture_validation_payload(monkeypatch)
    candidate_geometry = copy.deepcopy(FIXTURE["reference"])
    payload = {"sourceFootMarkerPrior": copy.deepcopy(FIXTURE["sourcePrior"])}

    validated, report = controlled_motion.fit_controlled_motion(
        payload, _validation_candidate={
            "nativeFootGeometry": candidate_geometry, "fixedRig": {}})

    assert report["reason"] == "test_readiness_stop"
    assert seen[-1]["nativeFootGeometry"] == candidate_geometry
    assert "anatomyCalibration" not in seen[-1]["nativeFootGeometry"]
    assert candidate_geometry == FIXTURE["reference"]


def test_invalid_explicit_candidate_geometry_is_rejected():
    validated, report = controlled_motion.fit_controlled_motion(
        {}, _validation_candidate={
            "nativeFootGeometry": {"version": 1}, "fixedRig": {}})

    assert report["applied"] is False
    assert report["reason"] == "native_foot_geometry_invalid"
    assert validated == {}


def test_validation_reports_context_geometry_conflict():
    context_geometry = copy.deepcopy(FIXTURE["reference"])
    candidate_geometry = copy.deepcopy(FIXTURE["reference"])
    candidate_geometry["sides"]["left"]["ankleToFootJointLengthMeters"] += 0.001
    payload = {"nativeFootGeometry": context_geometry}

    validated, report = controlled_motion.fit_controlled_motion(
        payload, _validation_candidate={
            "nativeFootGeometry": candidate_geometry, "fixedRig": {}})

    assert report["applied"] is False
    assert report["reason"] == "native_foot_geometry_conflict"
    assert validated is payload
