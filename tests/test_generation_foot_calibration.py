import copy

from exercise_motion_pkg import controlled_motion


def _native_geometry():
    return {
        "version": 1,
        "source": "named_smpl_rest_heel_and_toe_vertices",
        "modelSha256": "a" * 64,
        "sides": {
            "left": {
                "ankleToFootJointLengthMeters": 0.14,
                "heelFromAnkleLocalMeters": [-0.04, -0.022, -0.055],
                "toeFromAnkleLocalMeters": [0.181, 0.009, 0.016],
            },
            "right": {
                "ankleToFootJointLengthMeters": 0.135,
                "heelFromAnkleLocalMeters": [-0.03, 0.015, -0.06],
                "toeFromAnkleLocalMeters": [0.18, -0.01, 0.01],
            },
        },
    }


def test_generation_calibrates_working_geometry_but_validation_preserves_it(monkeypatch):
    observed_prior = {"source": "untouched observation evidence"}
    raw_geometry = _native_geometry()
    payload = {
        "nativeFootGeometry": raw_geometry,
        "sourceFootMarkerPrior": observed_prior,
    }
    seen = []

    def stop_at_readiness(working_payload):
        seen.append(working_payload)
        return {"reason": "test_readiness_stop"}

    monkeypatch.setattr(
        controlled_motion, "source_foot_patch_pose_binding_failure", stop_at_readiness)

    generated, generation_report = controlled_motion.fit_controlled_motion(payload)

    assert generation_report["reason"] == "test_readiness_stop"
    assert "anatomyCalibration" in seen[-1]["nativeFootGeometry"]
    assert seen[-1]["nativeFootGeometry"]["anatomyCalibration"]["sourceGeometry"] == raw_geometry
    assert "anatomyCalibration" not in payload["nativeFootGeometry"]
    assert payload["nativeFootGeometry"] == raw_geometry
    assert generated["sourceFootMarkerPrior"] is observed_prior

    validation_payload = {
        "nativeFootGeometry": copy.deepcopy(raw_geometry),
        "sourceFootMarkerPrior": observed_prior,
    }
    validated, validation_report = controlled_motion.fit_controlled_motion(
        validation_payload, _validation_candidate={"fixedRig": {}})

    assert validation_report["reason"] == "test_readiness_stop"
    assert "anatomyCalibration" not in seen[-1]["nativeFootGeometry"]
    assert seen[-1]["nativeFootGeometry"] == raw_geometry
    assert validated["nativeFootGeometry"] == raw_geometry
    assert validation_payload["nativeFootGeometry"] == raw_geometry
    assert validated["sourceFootMarkerPrior"] is observed_prior
