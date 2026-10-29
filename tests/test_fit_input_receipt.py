from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import exercise_motion_pkg.bake_and_rank as bake_and_rank_module
import exercise_motion_pkg.controlled_motion as controlled_motion_module
from exercise_motion_pkg.sequence_stabilization import pose_digest


def test_controlled_motion_fit_receipt_captures_actual_working_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bake_and_rank_module,
        "constrain_to_source_articulation_envelope",
        lambda source, proposed, **kwargs: (proposed, {"applied": False}),
    )
    fit_calls = []

    def fake_fit(payload, **kwargs):
        fit_calls.append((copy.deepcopy(payload), dict(kwargs)))
        return payload, {"applied": False, "reason": "test_stub"}

    monkeypatch.setattr(controlled_motion_module, "fit_controlled_motion", fake_fit)
    receipt_paths = []
    for variant in ("loop-0-adaptive-baseline", "loop-1-adaptive-baseline"):
        payload = {
            "fps": 30.0,
            "frameCount": 2,
            "jointNames": ["pelvis"],
            "frames": [
                {
                    "timeSec": time_sec,
                    "sourceJoints": {"pelvis": [0.0, 1.0, 0.0]},
                    "joints": {"pelvis": [0.0, 1.0, 0.0]},
                }
                for time_sec in (0.0, 1.0 / 30.0)
            ],
        }
        original = copy.deepcopy(payload)
        result, _ = bake_and_rank_module.constrain_baked_payload_to_source_articulation(
            payload,
            timeout_seconds=12.5,
            fit_input_capture_directory=tmp_path,
            fit_input_variant_identity=variant,
        )

        receipt_reference = result["controlledMotionFit"]["fitInputReceipt"]
        receipt_path = Path(receipt_reference["path"])
        receipt_paths.append(receipt_path)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        captured_payload, captured_kwargs = fit_calls[-1]

        assert receipt["payload"] == captured_payload
        assert receipt["fitKwargs"] == captured_kwargs == {"timeout_seconds": 12.5}
        assert "controlledArticulationReferenceJoints" in receipt["payload"]["frames"][0]
        assert "controlledArticulationReferenceJoints" not in original["frames"][0]
        assert receipt["solverInputPoseDigest"] == result["controlledMotionFit"]["solverInputPoseDigest"]
        expected_payload_digest = hashlib.sha256(
            json.dumps(captured_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert receipt["solverInputPayloadDigest"] == expected_payload_digest
        assert result["controlledMotionFit"]["solverInputPayloadDigest"] == expected_payload_digest
        assert result["controlledMotionFit"]["fitInputPoseDigest"] == pose_digest(result)
        assert result["controlledMotionFit"]["fitInputPoseDigest"] != receipt["solverInputPoseDigest"]
        assert receipt_reference["sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    assert receipt_paths[0] != receipt_paths[1]
    assert len(list(tmp_path.glob("fit-*.json"))) == 2


def test_rejected_fit_retains_local_candidate_without_publishing_its_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bake_and_rank_module,
        "constrain_to_source_articulation_envelope",
        lambda source, proposed, **kwargs: (proposed, {"applied": False}),
    )

    def fake_fit(payload, **kwargs):
        candidate = copy.deepcopy(payload)
        candidate["frames"][0]["joints"]["pelvis"][0] = 0.25
        candidate["fixedRig"] = {"version": 1, "coordinates": [[0.25, 1.0, 0.0]]}
        report = {"applied": False, "reason": "sourceFootContactArticulation"}
        controlled_motion_module.retain_rejected_fit_candidate(candidate, report, payload)
        return payload, report

    monkeypatch.setattr(controlled_motion_module, "fit_controlled_motion", fake_fit)
    payload = {
        "fps": 30.0,
        "frameCount": 2,
        "jointNames": ["pelvis"],
        "frames": [
            {
                "timeSec": time_sec,
                "sourceJoints": {"pelvis": [0.0, 1.0, 0.0]},
                "joints": {"pelvis": [0.0, 1.0, 0.0]},
            }
            for time_sec in (0.0, 1.0 / 30.0)
        ],
    }
    original_joints = copy.deepcopy([frame["joints"] for frame in payload["frames"]])

    result, _ = bake_and_rank_module.constrain_baked_payload_to_source_articulation(
        payload,
        timeout_seconds=12.5,
        fit_input_capture_directory=tmp_path,
        fit_input_variant_identity="rejected-high-pull-fit",
    )

    fit_report = result["controlledMotionFit"]
    diagnostic_reference = fit_report["rejectedFitDiagnostic"]
    diagnostic_path = Path(diagnostic_reference["path"])
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    receipt = json.loads(Path(fit_report["fitInputReceipt"]["path"]).read_text(encoding="utf-8"))
    assert [frame["joints"] for frame in result["frames"]] == original_joints
    assert diagnostic["candidatePayload"]["frames"][0]["joints"]["pelvis"][0] == 0.25
    assert diagnostic["candidatePayload"]["fixedRig"]["coordinates"][0][0] == 0.25
    assert diagnostic["inputReceipt"] == fit_report["fitInputReceipt"]
    assert diagnostic["inputReceipt"]["sha256"] == hashlib.sha256(
        Path(diagnostic["inputReceipt"]["path"]).read_bytes()
    ).hexdigest()
    assert diagnostic["candidatePoseDigest"] == pose_digest(diagnostic["candidatePayload"])
    assert diagnostic_reference["candidatePoseDigest"] == diagnostic["candidatePoseDigest"]
    assert diagnostic_reference["sha256"] == hashlib.sha256(diagnostic_path.read_bytes()).hexdigest()
    assert receipt["fitKwargs"] == {"timeout_seconds": 12.5}
    assert diagnostic["solverInputPayloadDigest"] == receipt["solverInputPayloadDigest"]
