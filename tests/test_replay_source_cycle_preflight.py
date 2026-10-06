import json
import sys

import pytest

from scripts import replay_source_cycle_preflight
from scripts.replay_source_cycle_preflight import fit_report_summary


def test_fit_report_summary_preserves_failure_owner_for_each_cycle():
    summary = fit_report_summary({
        "applied": False,
        "reason": "fit_validation_failed",
        "checks": {"anatomy": True, "loopSeam": False},
        "physicalReasons": ["anatomy_torso_bend"],
        "termination": "objective_stalled",
        "optimizerTermination": "evaluation_limit",
        "cycleRetryStopReason": "repeated_anatomical_cycle_failure",
        "cycleSelectionAttempts": [{
            "selection": {"startFrame": 2, "stopFrameExclusive": 60},
            "reason": "fit_validation_failed",
            "elapsedSeconds": 12.5,
            "fitReport": {
                "checks": {"anatomy": False, "loopSeam": True},
                "physicalReasons": ["anatomy_torso_bend"],
                "termination": "unreachable_conflict",
                "optimizerTermination": "converged",
            },
        }],
    })

    assert summary["failedChecks"] == ["loopSeam"]
    assert summary["cycleRetryStopReason"] == "repeated_anatomical_cycle_failure"
    assert summary["cycleSelectionAttempts"] == [{
        "selection": {"startFrame": 2, "stopFrameExclusive": 60},
        "reason": "fit_validation_failed",
        "elapsedSeconds": 12.5,
        "failedChecks": ["anatomy"],
        "physicalReasons": ["anatomy_torso_bend"],
        "termination": "unreachable_conflict",
        "optimizerTermination": "converged",
    }]


def test_production_constrained_fit_uses_production_constraint_and_gate(monkeypatch):
    calls = {}
    payload = {"frames": [{"timeSec": 0.0}, {"timeSec": 1.0}]}
    source_pose = {"frames": []}
    contract = {"exerciseName": "Retained Exercise"}

    def constrain(actual_payload, **kwargs):
        calls["payload"] = actual_payload
        calls.update(kwargs)
        actual_payload["controlledMotionFit"] = {
            "applied": True,
            "reason": "validated_controlled_motion",
        }
        return actual_payload, {"applied": True, "finalOwner": "controlledMotionFit"}

    monkeypatch.setattr(
        replay_source_cycle_preflight,
        "constrain_baked_payload_to_source_articulation",
        constrain,
    )
    monkeypatch.setattr(
        replay_source_cycle_preflight,
        "source_pose_reference_for_motion",
        lambda _source_pose, _payload: {"frames": []},
    )
    monkeypatch.setattr(
        replay_source_cycle_preflight,
        "pre_render_deterministic_gate",
        lambda *_args, **_kwargs: {"passed": True, "rejectionReasons": []},
    )

    fitted, report = replay_source_cycle_preflight.run_production_constrained_fit(
        payload, source_pose, contract, timeout_seconds=45.0
    )

    assert fitted["controlledMotionFit"]["applied"] is True
    assert calls["use_controlled_motion_fit"] is True
    assert calls["exercise_motion_contract"] is contract
    assert calls["source_pose_reference"] is source_pose
    assert calls["timeout_seconds"] == 45.0
    assert report["fit"]["reason"] == "validated_controlled_motion"
    assert report["preRenderGate"]["passed"] is True


def test_production_constrained_cli_separates_report_and_clip(tmp_path, monkeypatch, capsys):
    payload_path = tmp_path / "baked.json"
    source_pose_path = tmp_path / "source-pose.json"
    contract_path = tmp_path / "contract.json"
    clip_path = tmp_path / "output" / "fitted.json"
    report_path = tmp_path / "output" / "report.json"
    payload_path.write_text(json.dumps({
        "frames": [{"timeSec": 0.0, "sourceJoints": {}, "joints": {}}]
    }), encoding="utf-8")
    source_pose_path.write_text(json.dumps({"pose": {"frames": []}}), encoding="utf-8")
    contract_path.write_text(json.dumps({"exerciseName": "Retained Exercise"}), encoding="utf-8")

    monkeypatch.setattr(
        replay_source_cycle_preflight,
        "source_validated_cycle_proposals",
        lambda *_args: ([], []),
    )
    monkeypatch.setattr(
        replay_source_cycle_preflight,
        "run_production_constrained_fit",
        lambda *_args, **_kwargs: (
            {"frames": [], "fitMarker": True},
            {"fit": {"applied": False}},
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "replay_source_cycle_preflight.py",
        str(payload_path),
        "--source-pose", str(source_pose_path),
        "--contract", str(contract_path),
        "--fit-mode", "production_constrained",
        "--fit-timeout-seconds", "1",
        "--output-clip", str(clip_path),
        "--report", str(report_path),
    ])

    assert replay_source_cycle_preflight.main() == 0
    saved_clip = json.loads(clip_path.read_text(encoding="utf-8"))
    saved_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved_clip["fitMarker"] is True
    assert saved_report["outputClip"] == str(clip_path.resolve())
    assert json.loads(capsys.readouterr().out)["outputClip"] == str(clip_path.resolve())


def test_production_constrained_cli_rejects_cleaned_motion_without_source_joints(
    tmp_path, monkeypatch, capsys
):
    payload_path = tmp_path / "cleaned.json"
    source_pose_path = tmp_path / "source-pose.json"
    contract_path = tmp_path / "contract.json"
    payload_path.write_text(json.dumps({"frames": [{"timeSec": 0.0, "joints": {}}]}), encoding="utf-8")
    source_pose_path.write_text(json.dumps({"pose": {"frames": []}}), encoding="utf-8")
    contract_path.write_text(json.dumps({"exerciseName": "Retained Exercise"}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "replay_source_cycle_preflight.py",
        str(payload_path),
        "--source-pose", str(source_pose_path),
        "--contract", str(contract_path),
        "--fit-mode", "production_constrained",
        "--fit-timeout-seconds", "1",
    ])

    with pytest.raises(SystemExit) as error:
        replay_source_cycle_preflight.main()

    assert error.value.code == 2
    assert "sourceJoints and joints on every frame" in capsys.readouterr().err


def test_cli_rejects_abbreviated_output_clip_option(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "replay_source_cycle_preflight.py",
        str(tmp_path / "payload.json"),
        "--source-pose", str(tmp_path / "source.json"),
        "--contract", str(tmp_path / "contract.json"),
        "--output", str(tmp_path / "report.json"),
    ])

    with pytest.raises(SystemExit) as error:
        replay_source_cycle_preflight.main()

    assert error.value.code == 2
