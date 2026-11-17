from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "replay_exercise_motion_fit", ROOT / "scripts" / "replay_exercise_motion_fit.py"
)
replay = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(replay)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _minimal_payload(tmp_path: Path) -> dict:
    source = _write(tmp_path / "source.mp4", b"source-video")
    source_pose = _write(tmp_path / "source_pose.json", b'{"frames": []}')
    clock = _write(tmp_path / "clock.json", b'{"clock": true}')
    selection = _write(tmp_path / "selection.json", b'{"selection": true}')
    manifest = _write(tmp_path / "manifest.json", b'{"manifest": true}')
    exact = _write(tmp_path / "exact.json", b'{"exact": true}')
    prefit = _write(tmp_path / "prefit.json", b'{"prefit": true}')

    pose_reference = {
        "jointNames": ["pelvis"],
        "rootJoint": "pelvis",
        "frames": [{"sourceTimeSec": 0.0, "joints": {"pelvis": "0 0 0"}}],
    }
    contract = {
        "contractPolicyVersion": 39,
        "contractScope": "definition_only",
        "exerciseName": "Synthetic Test Movement",
    }
    payload = {
        "fps": 30.0,
        "frameCount": 2,
        "renderFloorY": 0.0,
        "jointNames": ["pelvis"],
        "sourceFootSupportEvidence": {},
        "frames": [
            {
                "timeSec": time,
                "joints": {"pelvis": [0.0, 1.0, 0.0]},
                "sourceJoints": {"pelvis": [0.0, 1.0, 0.0]},
            }
            for time in (0.0, 1.0 / 30.0)
        ],
        "sourcePoseReference": pose_reference,
        "exerciseMotionContract": contract,
        "sourcePoseCameraReference": {
            "sourceTimelineMapping": {
                "sourcePoseReferencePath": str(source_pose),
                "sourcePoseReferenceSha256": _sha(source_pose),
                "clockReceiptPath": str(clock),
                "clockReceiptSha256": _sha(clock),
                "selectionReceiptPath": str(selection),
                "selectionReceiptSha256": _sha(selection),
                "selectedSegmentPath": str(source),
                "selectedSegmentSha256": _sha(source),
            }
        },
        "artifactState": {
            "selectionEvidence": {
                "cycleSelection": {
                    "selectionId": "synthetic-selection",
                    "interval": {
                        "startFrame": 0,
                        "endFrame": 1,
                        "startTimeSec": 0.0,
                        "endTimeSec": 1.0 / 30.0,
                    },
                }
            }
        },
    }
    preflight = {
        "status": "ready",
        "sourceManifestSha256": _sha(manifest),
        "contractPolicyVersion": 39,
        "contractUsable": True,
        "phasePassed": True,
        "phaseSourceSha256": _sha(source),
        "selectedSourcePath": str(source),
        "selectedSourceSha256": _sha(source),
        "sourcePoseReferenceSha256": _sha(source_pose),
        "sourcePoseFrames": 1,
        "sourceSupportEvidenceSha256": replay.canonical_digest({}),
        "prefitPath": str(prefit),
        "prefitSha256": _sha(prefit),
        "prefitLineageValidated": True,
        "sourceClearance": {
            "status": "cleared",
            "sourceManifestPath": str(manifest),
            "sourceManifestSha256": _sha(manifest),
        },
        "sourceIntervalAuthority": {
            "authoritative": True,
            "selectionPath": str(selection),
            "exactValidationPath": str(exact),
        },
    }
    return {
        "payload": payload,
        "preflight": preflight,
        "source": source,
        "source_pose": source_pose,
        "clock": clock,
        "selection": selection,
        "manifest": manifest,
        "exact": exact,
        "prefit": prefit,
    }


def _receipt_fixture(tmp_path: Path) -> dict:
    fixture = _minimal_payload(tmp_path)
    payload = fixture["payload"]
    receipt = {
        "schemaVersion": 1,
        "variantIdentity": "synthetic-variant-current39",
        "solverInputPoseDigest": replay.current_pose_digest(payload),
        "solverInputPayloadDigest": replay.canonical_digest(payload),
        "sourceEvidenceDigest": replay.current_source_evidence_digest(payload),
        "fitStrategy": "synthetic_strategy",
        "fitKwargs": {"timeout_seconds": 5.0},
        "payload": payload,
        "sourcePoseReference": payload["sourcePoseReference"],
        "exerciseMotionContract": payload["exerciseMotionContract"],
    }
    receipt_path = tmp_path / "fit-input.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    proof_path = tmp_path / "preflight.json"
    proof_path.write_text(json.dumps(fixture["preflight"]), encoding="utf-8")
    return {
        **fixture,
        "receipt": receipt,
        "receipt_path": receipt_path,
        "receipt_sha256": _sha(receipt_path),
        "proof_path": proof_path,
        "variant": receipt["variantIdentity"],
        "payload_digest": receipt["solverInputPayloadDigest"],
    }


def _seal(fixture: dict, output: Path, **overrides) -> dict:
    kwargs = {
        "receipt_path": fixture["receipt_path"],
        "receipt_sha256": fixture["receipt_sha256"],
        "variant_identity": fixture["variant"],
        "payload_digest": fixture["payload_digest"],
        "proof_path": fixture["proof_path"],
        "output": output,
    }
    kwargs.update(overrides)
    return replay.seal_input(**kwargs)


def test_seal_exact_named_variant_and_hash(tmp_path):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / "sealed")
    bundle = json.loads(Path(sealed["bundlePath"]).read_text(encoding="utf-8"))

    assert sealed["status"] == "ok"
    assert sealed["bundleSha256"] == _sha(Path(sealed["bundlePath"]))
    assert bundle["content"]["selection"]["variantIdentity"] == fixture["variant"]
    assert bundle["content"]["selection"]["solverInputPayloadDigest"] == fixture["payload_digest"]
    assert bundle["content"]["fit"]["payload"] == fixture["payload"]
    assert bundle["content"]["fit"]["kwargs"] == {"timeout_seconds": 5.0}
    assert bundle["content"]["references"]["contract"]["policyVersion"] == 39
    assert bundle["contentDigest"] == replay.canonical_digest(bundle["content"])
    roles = {entry["role"] for entry in bundle["content"]["dependencies"]}
    assert {
        "exercise_motion_pkg/joint_plant_initialization.py",
        "exercise_motion_pkg/contact_interpolation.py",
        "exercise_motion_pkg/supported_contact_rig.py",
        "exercise_motion_pkg/anatomical_repair.py",
        "exercise_motion_pkg/trajectory_restoration.py",
    } <= set(bundle["content"]["code"]["baselineModules"])
    assert {
        "source_pose_reference",
        "source_frame_clock_receipt",
        "selection_receipt",
        "selected_segment",
        "normal_preflight_proof",
        "fit_input_receipt",
        "source_manifest",
        "normal_proof_prefit_artifact",
    } <= roles

    with pytest.raises(replay.ReplayError, match="variant mismatch"):
        _seal(fixture, tmp_path / "wrong-variant", variant_identity="other-variant")
    with pytest.raises(replay.ReplayError, match="payload digest mismatch"):
        _seal(fixture, tmp_path / "wrong-digest", payload_digest="0" * 64)
    with pytest.raises(replay.ReplayError, match="receipt hash mismatch"):
        _seal(fixture, tmp_path / "wrong-receipt", receipt_sha256="0" * 64)


def test_seal_rejects_fit_kwargs_not_accepted_by_normal_signature(tmp_path):
    fixture = _receipt_fixture(tmp_path)
    receipt = json.loads(fixture["receipt_path"].read_text(encoding="utf-8"))
    receipt["fitKwargs"]["not_a_fit_option"] = 1
    fixture["receipt_path"].write_text(json.dumps(receipt), encoding="utf-8")
    fixture["receipt_sha256"] = _sha(fixture["receipt_path"])

    with pytest.raises(replay.ReplayError, match="unsupported keyword arguments: not_a_fit_option"):
        _seal(fixture, tmp_path / "unsupported-fit-kwargs")


def test_tampered_dependency_prevents_any_fitter_call(tmp_path, monkeypatch):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / "sealed")
    fixture["source_pose"].write_bytes(b'{"frames": ["tampered"]}')

    from exercise_motion_pkg import controlled_motion as motion

    calls = []

    def forbidden_fit(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("fitter must not be called")

    monkeypatch.setattr(motion, "fit_controlled_motion", forbidden_fit)
    with pytest.raises(replay.ReplayError, match="dependency hash mismatch"):
        replay.run_bundle(
            bundle_path=sealed["bundlePath"],
            bundle_sha256=sealed["bundleSha256"],
            output_dir=tmp_path / "run",
        )
    assert calls == []
    assert not (tmp_path / "run" / "run-result.json").exists()


def test_tampered_fit_receipt_prevents_any_fitter_call(tmp_path, monkeypatch):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / "sealed")
    fixture["receipt_path"].write_text("tampered receipt", encoding="utf-8")

    from exercise_motion_pkg import controlled_motion as motion

    calls = []

    def forbidden_fit(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("fitter must not be called")

    monkeypatch.setattr(motion, "fit_controlled_motion", forbidden_fit)
    with pytest.raises(replay.ReplayError, match="fit input receipt hash mismatch"):
        replay.run_bundle(
            bundle_path=sealed["bundlePath"],
            bundle_sha256=sealed["bundleSha256"],
            output_dir=tmp_path / "run-tampered-receipt",
        )
    assert calls == []
    assert not (tmp_path / "run-tampered-receipt" / "run-result.json").exists()


def test_rehashed_bundle_payload_tampering_still_fails_sealed_payload_digest(tmp_path):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / "sealed")
    bundle_path = Path(sealed["bundlePath"])
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["content"]["fit"]["payload"]["frames"][0]["joints"]["pelvis"][0] = 8.0
    bundle["contentDigest"] = replay.canonical_digest(bundle["content"])
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    with pytest.raises(replay.ReplayError, match="sealed fit payload digest mismatch"):
        replay._load_and_validate_bundle(
            bundle_path=bundle_path, bundle_sha256=_sha(bundle_path)
        )


@pytest.mark.parametrize(
    ("digest_kind", "changed_module", "should_pass"),
    [
        ("pose", "exercise_motion_pkg/support_geometry.py", False),
        ("source", "exercise_motion_pkg/support_geometry.py", False),
        ("pose", "exercise_motion_pkg/sequence_stabilization.py", True),
        ("source", "exercise_motion_pkg/controlled_motion.py", True),
    ],
)
def test_digest_mismatch_requires_its_owning_code_to_change(
    tmp_path, monkeypatch, digest_kind, changed_module, should_pass
):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / f"sealed-{digest_kind}-{should_pass}")
    compare = replay._compare_code_identity

    def compare_with_drift(modules):
        current, result = compare(modules)
        result["changedModules"] = [changed_module]
        result["concurrentOrIntentionalCodeChangeDetected"] = True
        return current, result

    monkeypatch.setattr(replay, "_compare_code_identity", compare_with_drift)
    monkeypatch.setattr(
        replay,
        "current_pose_digest" if digest_kind == "pose" else "current_source_evidence_digest",
        lambda _payload: "0" * 64,
    )

    if should_pass:
        result = replay._load_and_validate_bundle(
            bundle_path=sealed["bundlePath"], bundle_sha256=sealed["bundleSha256"]
        )
        assert result["poseDigestMatches"] is (digest_kind != "pose")
        assert result["sourceEvidenceMatches"] is (digest_kind != "source")
    else:
        message = (
            "sealed solver input pose digest mismatch"
            if digest_kind == "pose"
            else "sealed source evidence digest mismatch"
        )
        with pytest.raises(replay.ReplayError, match=message):
            replay._load_and_validate_bundle(
                bundle_path=sealed["bundlePath"], bundle_sha256=sealed["bundleSha256"]
            )


def test_digest_calculation_error_fails_closed(tmp_path, monkeypatch):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / "sealed-digest-error")

    def broken_pose_digest(_payload):
        raise RuntimeError("synthetic digest implementation failure")

    monkeypatch.setattr(replay, "current_pose_digest", broken_pose_digest)
    with pytest.raises(replay.ReplayError, match="cannot verify sealed pose/source evidence digests"):
        replay._load_and_validate_bundle(
            bundle_path=sealed["bundlePath"], bundle_sha256=sealed["bundleSha256"]
        )


def test_rejected_best_is_persisted_when_payload_is_unchanged(tmp_path, monkeypatch):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / "sealed")
    from exercise_motion_pkg import controlled_motion as motion

    def fake_fit(payload, **kwargs):
        candidate = copy.deepcopy(payload)
        candidate["frames"][0]["joints"]["pelvis"][0] = 9.0
        candidate["fixedRig"] = {"version": 1, "coordinates": [[9.0, 1.0, 0.0]]}
        report = {"applied": False, "reason": "synthetic_rejection", "checks": {"support": False}}
        motion.retain_rejected_fit_candidate(candidate, report, payload)
        return payload, report

    monkeypatch.setattr(motion, "fit_controlled_motion", fake_fit)
    result = replay.run_bundle(
        bundle_path=sealed["bundlePath"],
        bundle_sha256=sealed["bundleSha256"],
        output_dir=tmp_path / "run-unchanged",
    )
    assert result["status"] == "ok"
    assert result["fitAppliedAsReturned"] is False
    assert result["returnedPayloadSameAsInput"] is True
    assert len(result["rejectedCandidates"]) == 1
    candidate_path = Path(result["rejectedCandidates"][0]["path"])
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert candidate["kind"] == replay.CANDIDATE_KIND
    assert candidate["candidatePayload"]["frames"][0]["joints"]["pelvis"][0] == 9.0
    assert candidate["inputPayloadDigest"] == result["inputIdentities"]["payloadDigest"]
    assert result["gateVector"] == {"support": False}
    assert result["acceptance"]["movementAccepted"] is False


def test_rejected_best_is_persisted_when_fit_raises(tmp_path, monkeypatch):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / "sealed")
    from exercise_motion_pkg import controlled_motion as motion

    def raising_fit(payload, **kwargs):
        candidate = copy.deepcopy(payload)
        candidate["frames"][0]["joints"]["pelvis"][0] = 4.0
        motion.retain_rejected_fit_candidate(
            candidate, {"applied": False, "reason": "before_exception"}, payload
        )
        raise RuntimeError("synthetic fit explosion")

    monkeypatch.setattr(motion, "fit_controlled_motion", raising_fit)
    with pytest.raises(replay.ReplayError, match="synthetic fit explosion"):
        replay.run_bundle(
            bundle_path=sealed["bundlePath"],
            bundle_sha256=sealed["bundleSha256"],
            output_dir=tmp_path / "run-exception",
        )
    result_path = tmp_path / "run-exception" / "run-result.json"
    assert result_path.exists()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "error"
    assert result["exception"]["type"] == "RuntimeError"
    assert len(result["rejectedCandidates"]) == 1
    assert Path(result["rejectedCandidates"][0]["path"]).exists()


def test_valid_roundtrip_without_heavy_fit(tmp_path, monkeypatch):
    fixture = _receipt_fixture(tmp_path)
    sealed = _seal(fixture, tmp_path / "sealed")
    from exercise_motion_pkg import controlled_motion as motion

    def fake_fit(payload, **kwargs):
        result = copy.deepcopy(payload)
        result["frames"][0]["joints"]["pelvis"][0] = 0.25
        report = {
            "applied": True,
            "checks": {"support": True, "phase": True},
            "nfev": 7,
            "cost": 0.125,
        }
        return result, report

    monkeypatch.setattr(motion, "fit_controlled_motion", fake_fit)
    result = replay.run_bundle(
        bundle_path=sealed["bundlePath"],
        bundle_sha256=sealed["bundleSha256"],
        output_dir=tmp_path / "run-ok",
        timeout_seconds=2.0,
        max_evaluations=3,
    )
    assert result["status"] == "ok"
    assert result["fitAppliedAsReturned"] is True
    assert result["requestedFitKwargs"] == {"timeout_seconds": 2.0, "max_evaluations": 3}
    assert result["gateVector"] == {"support": True, "phase": True}
    assert result["availableSolverStats"]["nfev"] == 7
    assert result["availableSolverStats"]["cost"] == 0.125
    assert result["returnedPayloadSameAsInput"] is False
    assert (tmp_path / "run-ok" / "fit-returned-payload.json").exists()
    assert (tmp_path / "run-ok" / "run-manifest.json").exists()
    assert result["acceptance"]["movementAccepted"] is False

    preflight = replay.preflight_bundle(
        bundle_path=sealed["bundlePath"],
        bundle_sha256=sealed["bundleSha256"],
        output=tmp_path / "preflight-result.json",
    )
    assert preflight["status"] == "ok"
    assert preflight["fitterCalled"] is False
    assert (tmp_path / "preflight-result.json").exists()
