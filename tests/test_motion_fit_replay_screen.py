from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "replay_exercise_motion_fit_screen",
    ROOT / "scripts" / "replay_exercise_motion_fit.py",
)
replay = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(replay)

_DEFAULT = object()


def _candidate(*, frame_count: int = 10) -> dict:
    fps = 30.0
    names = ["pelvis", "left_ankle"]
    frames = []
    for index in range(frame_count):
        frames.append(
            {
                "timeSec": index / fps,
                "joints": {
                    "pelvis": [0.0, 1.0 + 0.001 * index, 0.0],
                    "left_ankle": [0.0, 0.1, 0.02 * index],
                },
            }
        )
    return {
        "fps": fps,
        "frameCount": frame_count,
        "jointNames": names,
        "rootJoint": "pelvis",
        "loop": {"enabled": False},
        "frames": frames,
        "fixedRig": {"version": 1, "offsets": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]},
    }


def _reference(candidate: dict) -> list[list[list[float]]]:
    return [
        [
            [0.0, 1.0, 0.0],
            [0.0, 0.1, 0.0],
        ]
        for _ in candidate["frames"]
    ]


def _actual_targets(candidate: dict) -> list[list[list[float]]]:
    return [
        [list(frame["joints"][name]) for name in candidate["jointNames"]]
        for frame in candidate["frames"]
    ]


def _context(
    candidate: dict,
    *,
    jerk_limit: float = 1e-6,
    contact_limit: float = 0.0005,
    fit_pinned: list[list[bool]] | None = None,
    fit_targets: list[list[list[float]]] | None = None,
    joint_pinned: list[list[bool]] | None | object = _DEFAULT,
    joint_targets: list[list[list[float]]] | None | object = _DEFAULT,
    height_pinned: list[list[bool]] | None = None,
    height_targets: list[list[float]] | None = None,
    height_limit: float | None = None,
    reference: list[list[list[float]]] | None = None,
) -> dict:
    count = len(candidate["frames"])
    joint_count = len(candidate["jointNames"])
    actual = _actual_targets(candidate)
    if fit_pinned is None:
        fit_pinned = [[True, False] for _ in range(count)]
    if fit_targets is None:
        fit_targets = actual
    if joint_pinned is _DEFAULT:
        joint_pinned = [[True, False] for _ in range(count)]
    if joint_targets is _DEFAULT:
        joint_targets = actual
    if reference is None:
        reference = _reference(candidate)
    from exercise_motion_pkg.fit_context import build_fit_context

    context = build_fit_context(
        candidate,
        fit_contact_pinned=fit_pinned,
        fit_contact_targets=fit_targets,
        joint_contact_pinned=joint_pinned,
        joint_contact_targets=joint_targets,
        height_contact_pinned=height_pinned,
        height_contact_targets=height_targets,
        height_contact_limit=height_limit,
        temporal_reference=reference,
        jerk_limit=jerk_limit,
        contact_limit=contact_limit,
    )
    return context


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _forbid_full_validation(monkeypatch):
    from exercise_motion_pkg import controlled_motion as motion

    calls: list[tuple] = []

    def forbidden_validation(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("full validation must not run from screening")

    monkeypatch.setattr(
        motion, "validate_controlled_motion_candidate", forbidden_validation
    )
    monkeypatch.setattr(motion, "fit_controlled_motion", forbidden_validation)
    return calls


def _screen(
    tmp_path: Path,
    candidate: dict,
    context: dict,
    monkeypatch,
) -> dict:
    candidate_path = _write_json(tmp_path / "candidate.json", candidate)
    context_path = _write_json(tmp_path / "context.json", context)
    return replay.screen_candidate_file(
        candidate_path=candidate_path,
        context_path=context_path,
        output=tmp_path / "screen.json",
    )


def test_known_jerk_failure_never_calls_full_validation(tmp_path, monkeypatch):
    calls = _forbid_full_validation(monkeypatch)
    candidate = _candidate()
    candidate["frames"][4]["joints"]["pelvis"][1] += 0.25
    context = _context(candidate)

    report = _screen(tmp_path, candidate, context, monkeypatch)

    assert report["status"] == replay.SCREEN_STATUS_KNOWN_FAILED
    assert "jerk_rms_exceeds_limit" in report["failures"]
    assert report["checks"]["jerk"]["candidateRms"] > context["jerkLimit"]
    assert report["fullValidationPerformed"] is False
    assert report["eligibility"]["eligibleForFullValidation"] is False
    assert replay.screen_skips_full_validation(report) is True
    assert replay.screen_requires_full_validation(report) is False
    assert calls == []


def test_known_contact_failure_never_calls_full_validation(tmp_path, monkeypatch):
    calls = _forbid_full_validation(monkeypatch)
    candidate = _candidate()
    joint_targets = []
    for frame in candidate["frames"]:
        row = []
        for name in candidate["jointNames"]:
            value = list(frame["joints"][name])
            if name == "pelvis":
                value[1] += 1.0
            row.append(value)
        joint_targets.append(row)
    context = _context(candidate, joint_targets=joint_targets)

    report = _screen(tmp_path, candidate, context, monkeypatch)

    assert report["status"] == replay.SCREEN_STATUS_KNOWN_FAILED
    assert "contact_error_exceeds_limit" in report["failures"]
    assert report["checks"]["contact"]["components"]["keyframe"]["passed"] is False
    assert report["checks"]["contact"]["components"]["keyframe"]["basis"] == (
        "keyframe_contact_error"
    )
    assert report["fullValidationPerformed"] is False
    assert replay.screen_skips_full_validation(report) is True
    assert replay.screen_requires_full_validation(report) is False
    assert calls == []


def test_height_only_gate_rejects_vertical_violation_but_not_horizontal_motion(
    tmp_path, monkeypatch
):
    from exercise_motion_pkg import controlled_motion as motion
    from exercise_motion_pkg import fit_context

    calls = _forbid_full_validation(monkeypatch)
    candidate = _candidate()
    names = candidate["jointNames"]
    count = len(candidate["frames"])
    foot = names.index("left_ankle")
    limit = motion.PLAYBACK_FLOOR_LIMIT_METERS
    mask = [[False] * len(names) for _ in range(count)]
    for row in mask:
        row[foot] = True
    targets = [
        [frame["joints"][name][1] for name in names] for frame in candidate["frames"]
    ]
    no_xyz_pins = [[False] * len(names) for _ in range(count)]

    context = _context(
        candidate,
        joint_pinned=no_xyz_pins,
        height_pinned=mask,
        height_targets=targets,
        height_limit=limit,
    )
    # The height-only class must remain its own copied gate inputs.
    assert context["heightContactPinned"] == mask
    assert context["heightContactTargets"] == targets
    assert replay._numpy().asarray(context["heightContactTargets"]).shape == (
        count,
        len(names),
    )
    assert context["heightContactLimitMeters"] == limit
    assert context["heightContactLimitMeters"] != context["contactLimitMeters"]
    assert context["heightContactPinned"] != context["jointContactPinned"]
    assert fit_context.validate_fit_context(candidate, context)["passed"]

    # The candidate foot translates horizontally every frame while its height
    # matches the gate, so the height-only screen must not reject it.
    horizontal = _screen(tmp_path / "horizontal", candidate, context, monkeypatch)
    height_check = horizontal["checks"]["contact"]["components"]["heightOnly"]
    assert height_check["available"] is True
    assert height_check["passed"] is True
    assert height_check["pinnedCount"] == count
    assert horizontal["status"] == replay.SCREEN_STATUS_ELIGIBLE

    vertical_targets = copy.deepcopy(targets)
    for row in vertical_targets:
        row[foot] += 0.01
    violating = _context(
        candidate,
        joint_pinned=no_xyz_pins,
        height_pinned=mask,
        height_targets=vertical_targets,
        height_limit=limit,
    )
    rejected = _screen(tmp_path / "vertical", candidate, violating, monkeypatch)
    assert rejected["status"] == replay.SCREEN_STATUS_KNOWN_FAILED
    assert "height_only_contact_error_exceeds_limit" in rejected["failures"]
    height_check = rejected["checks"]["contact"]["components"]["heightOnly"]
    assert height_check["passed"] is False
    assert height_check["maximumErrorMeters"] == pytest.approx(0.01)
    assert height_check["limitMeters"] == limit
    assert replay.screen_skips_full_validation(rejected) is True
    assert calls == []

    # Contexts without the actual height-only fields stay compatible and
    # report that gate as unavailable instead of inventing a pass.
    legacy_context = _context(candidate)
    for key in (
        "heightContactPinned",
        "heightContactTargets",
        "heightContactLimitMeters",
    ):
        legacy_context.pop(key, None)
    legacy_context["contextDigest"] = replay.canonical_digest(
        {key: value for key, value in legacy_context.items() if key != "contextDigest"}
    )
    legacy = _screen(tmp_path / "legacy", candidate, legacy_context, monkeypatch)
    legacy_height = legacy["checks"]["contact"]["components"]["heightOnly"]
    assert legacy_height["available"] is False
    assert legacy_height["status"] == "unavailable"
    assert legacy["status"] == replay.SCREEN_STATUS_ELIGIBLE


def test_stale_or_tampered_context_fails_closed(tmp_path, monkeypatch):
    original = _candidate()
    context = _context(original)
    current = copy.deepcopy(original)
    current["frames"][0]["joints"]["pelvis"][0] = 0.5

    stale = _screen(tmp_path / "stale", current, context, monkeypatch)
    assert stale["status"] == replay.SCREEN_STATUS_CONTEXT_UNAVAILABLE
    assert "candidate_pose_digest_mismatch" in stale["failures"]
    assert stale["eligibility"]["eligibleForFullValidation"] is False
    assert stale["eligibility"]["contextAvailable"] is False
    assert replay.screen_skips_full_validation(stale) is True

    tampered_context = copy.deepcopy(context)
    tampered_context["jerkLimit"] *= 2.0
    tampered = _screen(tmp_path / "tampered", original, tampered_context, monkeypatch)
    assert tampered["status"] == replay.SCREEN_STATUS_CONTEXT_UNAVAILABLE
    assert "context_digest_mismatch" in tampered["failures"]
    assert tampered["eligibility"]["eligibleForFullValidation"] is False

    incomplete_context = copy.deepcopy(context)
    incomplete_context["complete"] = False
    incomplete_context["contextDigest"] = replay.canonical_digest(
        {
            key: value
            for key, value in incomplete_context.items()
            if key != "contextDigest"
        }
    )
    incomplete = _screen(
        tmp_path / "incomplete", original, incomplete_context, monkeypatch
    )
    assert incomplete["status"] == replay.SCREEN_STATUS_CONTEXT_UNAVAILABLE
    assert "context_incomplete" in incomplete["failures"]
    assert incomplete["eligibility"]["eligibleForFullValidation"] is False


def test_eligible_screen_still_requires_full_validation(tmp_path, monkeypatch):
    calls = _forbid_full_validation(monkeypatch)
    candidate = _candidate()
    context = _context(candidate, reference=_reference(candidate))

    report = _screen(tmp_path, candidate, context, monkeypatch)

    assert report["status"] == replay.SCREEN_STATUS_ELIGIBLE
    assert report["failures"] == []
    assert report["eligibility"]["eligibleForFullValidation"] is True
    assert report["eligibility"]["fullValidationRequiredBeforeAcceptance"] is True
    assert report["eligibility"]["fullValidationRecommended"] is True
    assert report["eligibility"]["canAcceptOrPublish"] is False
    assert report["fullValidationPerformed"] is False
    assert report["acceptance"]["movementAccepted"] is False
    assert replay.screen_skips_full_validation(report) is False
    assert replay.screen_requires_full_validation(report) is True
    assert calls == []


def test_native_only_contact_is_unavailable_not_passed(tmp_path, monkeypatch):
    candidate = _candidate()
    context = _context(
        candidate,
        joint_pinned=[[False, False] for _ in candidate["frames"]],
        reference=_reference(candidate),
    )
    context["nativeFootMaterialTracks"] = {
        "version": 2,
        "left": {"active": [True] * len(candidate["frames"])},
        "right": {"active": [False] * len(candidate["frames"])},
    }
    context["contextDigest"] = replay.canonical_digest(
        {key: value for key, value in context.items() if key != "contextDigest"}
    )

    report = _screen(tmp_path, candidate, context, monkeypatch)

    assert report["status"] == replay.SCREEN_STATUS_ELIGIBLE
    assert report["checks"]["contact"]["status"] == "unavailable"
    assert report["checks"]["contact"]["passed"] is None
    native = report["checks"]["contact"]["components"]["nativeMaterial"]
    assert native["available"] is False
    assert native["status"] == "unavailable"
    assert native["reason"] == "native_material_subframe_samples_unavailable"
    assert "contact" in report["unavailableChecks"]
    assert report["fullValidationPerformed"] is False
    assert replay.screen_requires_full_validation(report) is True


def test_moving_native_only_keyframes_are_not_falsely_tested(tmp_path, monkeypatch):
    candidate = _candidate()
    for index, frame in enumerate(candidate["frames"]):
        frame["joints"]["left_ankle"][2] = 0.25 * index
        frame["joints"]["pelvis"][1] += 0.1 * index
    context = _context(
        candidate,
        joint_pinned=[[False, False] for _ in candidate["frames"]],
        reference=_reference(candidate),
    )
    context["nativeFootMaterialTracks"] = {
        "version": 2,
        "left": {"active": [True] * len(candidate["frames"])},
    }
    context["contextDigest"] = replay.canonical_digest(
        {key: value for key, value in context.items() if key != "contextDigest"}
    )

    report = _screen(tmp_path, candidate, context, monkeypatch)

    # No shifted-keyframe native residual was run, so no fabricated failure.
    assert report["status"] == replay.SCREEN_STATUS_ELIGIBLE
    assert report["failures"] == []
    assert report["checks"]["contact"]["components"]["nativeMaterial"][
        "passed"
    ] is None
    assert report["checks"]["contact"]["status"] == "unavailable"


def test_derived_fit_target_miss_without_hard_pin_is_not_rejected(
    tmp_path, monkeypatch
):
    candidate = _candidate()
    fit_targets = _actual_targets(candidate)
    for row in fit_targets:
        row[candidate["jointNames"].index("pelvis")][1] += 1.0

    missing_hard = _context(candidate, fit_targets=fit_targets, joint_pinned=None,
                            joint_targets=None)
    report = _screen(tmp_path / "missing_hard", candidate, missing_hard, monkeypatch)
    assert report["status"] == replay.SCREEN_STATUS_ELIGIBLE
    assert report["failures"] == []
    assert report["checks"]["contact"]["components"]["keyframe"]["reason"] == (
        "hard_joint_contact_mask_unavailable"
    )
    assert report["checks"]["contact"]["status"] == "unavailable"

    distinct_hard = _context(
        candidate,
        fit_targets=fit_targets,
        joint_pinned=[[True, False] for _ in candidate["frames"]],
    )
    report = _screen(tmp_path / "distinct_hard", candidate, distinct_hard, monkeypatch)
    assert report["status"] == replay.SCREEN_STATUS_ELIGIBLE
    assert report["checks"]["contact"]["components"]["keyframe"]["passed"] is True


def test_real_fit_context_helper_accepts_hard_joint_schema(tmp_path, monkeypatch):
    candidate = _candidate()
    context = _context(candidate)

    report = _screen(
        tmp_path, candidate, context, monkeypatch
    )

    assert report["status"] == replay.SCREEN_STATUS_ELIGIBLE
    assert report["context"]["validator"] == "fit_context.validate_fit_context"
    assert report["checks"]["contact"]["components"]["keyframe"]["passed"] is True


def test_missing_context_and_inherited_report_context_are_rejected(
    tmp_path, monkeypatch
):
    candidate = _candidate()
    context = _context(candidate)
    missing_path = _write_json(
        tmp_path / "missing.json",
        {"candidatePayload": candidate},
    )
    with pytest.raises(replay.ReplayError, match="no captured fitContext"):
        replay.screen_candidate_file(candidate_path=missing_path)

    inherited_path = _write_json(
        tmp_path / "inherited.json",
        {
            "candidatePayload": candidate,
            "controlledMotionFit": {"fitContext": context},
        },
    )
    with pytest.raises(replay.ReplayError, match="no captured fitContext"):
        replay.screen_candidate_file(candidate_path=inherited_path)


def test_diagnostic_report_fit_context_is_read(tmp_path, monkeypatch):
    candidate = _candidate()
    context = _context(candidate, reference=_reference(candidate))
    diagnostic = {
        "schemaVersion": 1,
        "kind": "rejected_controlled_motion_fit_diagnostic",
        "candidatePayloadDigest": replay.canonical_digest(candidate),
        "candidatePoseDigest": replay.current_pose_digest(candidate),
        "candidatePayload": candidate,
        "report": {"fitContext": context},
    }
    path = _write_json(tmp_path / "diagnostic.json", diagnostic)

    report = replay.screen_candidate_file(candidate_path=path)

    assert report["status"] == replay.SCREEN_STATUS_ELIGIBLE
    assert report["context"]["source"] == "diagnostic_report_fitContext"


def test_parser_preserves_seal_preflight_run_and_adds_exact_screen():
    parser = replay._build_parser()
    seal = parser.parse_args(
        [
            "seal",
            "--receipt",
            "r.json",
            "--receipt-sha256",
            "0" * 64,
            "--variant",
            "v",
            "--payload-digest",
            "1" * 64,
            "--proof",
            "p.json",
            "--output",
            "out",
        ]
    )
    assert (seal.command, seal.receipt, seal.variant) == ("seal", "r.json", "v")
    preflight = parser.parse_args(
        ["preflight", "--bundle", "b.json", "--bundle-sha256", "2" * 64]
    )
    assert preflight.command == "preflight" and preflight.bundle == "b.json"
    run = parser.parse_args(
        [
            "run",
            "--bundle",
            "b.json",
            "--bundle-sha256",
            "2" * 64,
            "--output-dir",
            "out",
        ]
    )
    assert (run.command, run.output_dir) == ("run", "out")
    screen = parser.parse_args(
        ["screen", "--candidate", "candidate.json", "--output", "screen.json"]
    )
    assert (screen.command, screen.candidate, screen.context) == (
        "screen",
        "candidate.json",
        None,
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["screen"])


def test_screen_main_writes_report(tmp_path, monkeypatch):
    candidate = _candidate()
    context = _context(candidate, reference=_reference(candidate))
    candidate_path = _write_json(tmp_path / "candidate.json", candidate)
    context_path = _write_json(tmp_path / "context.json", context)
    output_path = tmp_path / "screen.json"

    exit_code = replay.main(
        [
            "screen",
            "--candidate",
            str(candidate_path),
            "--context",
            str(context_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["kind"] == replay.SCREEN_KIND
    assert written["status"] == replay.SCREEN_STATUS_ELIGIBLE
    assert written["candidate"]["candidatePoseDigest"] == replay.current_pose_digest(
        candidate
    )


def test_missing_shared_context_validator_fails_closed(tmp_path, monkeypatch):
    candidate = _candidate()
    context = _context(candidate)
    monkeypatch.setattr(replay, "_fit_context_helper", lambda: (None, None))
    report = _screen(tmp_path, candidate, context, monkeypatch)
    assert report["status"] == replay.SCREEN_STATUS_CONTEXT_UNAVAILABLE
    assert "fit_context_helper_unavailable" in report["failures"]
    assert report["eligibility"]["eligibleForFullValidation"] is False
