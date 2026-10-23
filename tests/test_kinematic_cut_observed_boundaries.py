from __future__ import annotations

from typing import Any

from exercise_motion_pkg import kinematic_cut


def _pose(wrist_y: float, flexion: float = 0.0) -> dict[str, list[float]]:
    left_ankle = (0.46 - 0.13 * flexion, 0.93 - 0.18 * flexion)
    right_ankle = (0.54 + 0.13 * flexion, 0.93 - 0.18 * flexion)
    return {
        "nose": [0.5, 0.30, 0.9],
        "left_shoulder": [0.44, 0.40, 0.9],
        "right_shoulder": [0.56, 0.40, 0.9],
        "left_elbow": [0.42, 0.50, 0.9],
        "right_elbow": [0.58, 0.50, 0.9],
        "left_wrist": [0.43, wrist_y, 0.9],
        "right_wrist": [0.57, wrist_y, 0.9],
        "left_hip": [0.46, 0.65, 0.9],
        "right_hip": [0.54, 0.65, 0.9],
        "left_knee": [0.46, 0.80, 0.9],
        "right_knee": [0.54, 0.80, 0.9],
        "left_ankle": [*left_ankle, 0.9],
        "right_ankle": [*right_ankle, 0.9],
    }


def _samples(
    wrist_at: Any,
    *,
    flexion_at: Any = lambda _: 0.0,
    duration: float = 8.0,
    fps: float = 8.0,
) -> list[dict[str, Any]]:
    result = []
    for index in range(int(duration * fps)):
        time = index / fps
        result.append(
            {
                "timeSeconds": time,
                "confidence": 0.9,
                "keypoints": _pose(float(wrist_at(time)), float(flexion_at(time))),
            }
        )
    return result


def test_observed_return_to_start_proposal_survives_missing_pca(monkeypatch):
    monkeypatch.setattr(kinematic_cut, "dominant_motion_signal", lambda _: None)
    samples = _samples(
        lambda _: 0.55,
        flexion_at=lambda time: 0.0 if time < 1.5 or time >= 6.0 else 1.0,
    )

    proposals = kinematic_cut.propose_source_cut(
        contract={
            "completionMode": "return_to_start",
            "startPoseConstraints": {"kneeState": "extended"},
        },
        dominant_pose_samples=samples,
        max_proposals=1,
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.policy == "observed_boundary_return_to_start"
    assert proposal.start_seconds < 1.5
    assert proposal.end_seconds >= 6.0
    assert proposal.stats["excursionTorsoUnits"] >= kinematic_cut.MIN_AMPLITUDE_TORSO_UNITS
    assert "phaseCoverage" not in proposal.stats


def test_observed_nonloop_proposal_keeps_distinct_end_boundary(monkeypatch):
    monkeypatch.setattr(kinematic_cut, "dominant_motion_signal", lambda _: None)
    samples = _samples(lambda _: 0.55, flexion_at=lambda time: max(0.0, min(1.0, (time - 2.0) / 2.0)))

    proposals = kinematic_cut.propose_source_cut(
        contract={
            "completionMode": "distinct_end_state",
            "startPoseConstraints": {"kneeState": "extended"},
            "endPoseConstraints": {"kneeState": "deep_flexion"},
        },
        dominant_pose_samples=samples,
        max_proposals=1,
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.policy == "observed_boundary_distinct_end_state"
    assert proposal.start_seconds < 3.0 < proposal.end_seconds
    assert proposal.stats["startBoundaryScore"] >= kinematic_cut.POSE_MATCH_THRESHOLD
    assert proposal.stats["endBoundaryScore"] >= kinematic_cut.POSE_MATCH_THRESHOLD


def test_observed_boundary_search_does_not_bridge_a_spread_window_gap(monkeypatch):
    monkeypatch.setattr(kinematic_cut, "dominant_motion_signal", lambda _: None)
    samples = _samples(lambda _: 0.55, flexion_at=lambda time: 0.0 if time < 1.5 else 1.0, duration=8.0)
    samples = [sample for sample in samples if sample["timeSeconds"] < 2.0 or sample["timeSeconds"] >= 5.0]

    proposals = kinematic_cut.propose_source_cut(
        contract={
            "completionMode": "distinct_end_state",
            "startPoseConstraints": {"kneeState": "extended"},
            "endPoseConstraints": {"kneeState": "deep_flexion"},
        },
        dominant_pose_samples=samples,
        max_proposals=1,
    )

    assert proposals == []


def test_pca_cycles_are_detected_within_contiguous_runs_on_both_sides_of_gap():
    samples = []
    for run_start in (0.0, 12.0):
        for frame_index in range(32):
            time = run_start + frame_index / 8.0
            phase = time % 2.0
            flexion = 0.0 if phase < 0.25 or phase >= 1.75 else 1.0
            samples.append(
                {
                    "timeSeconds": time,
                    "confidence": 0.9,
                    "keypoints": _pose(0.55, flexion),
                }
            )

    proposals = kinematic_cut.propose_source_cut(
        contract={
            "completionMode": "return_to_start",
            "startPoseConstraints": {"kneeState": "extended"},
        },
        dominant_pose_samples=samples,
        max_proposals=4,
    )

    assert proposals
    assert any(proposal.start_seconds < 4.0 for proposal in proposals)
    assert any(proposal.start_seconds >= 12.0 for proposal in proposals)
    assert all(
        (proposal.end_seconds <= 4.0) or (proposal.start_seconds >= 12.0)
        for proposal in proposals
    )


def test_existing_pca_proposals_still_need_observed_contract_boundaries(monkeypatch):
    signal = kinematic_cut.SignalResult(
        times=tuple(index / 8.0 for index in range(64)),
        signal=tuple(float(index % 8) for index in range(64)),
        energy=tuple(1.0 for _ in range(64)),
        explained_variance_ratio=0.9,
        body_scale=0.25,
        mean_confidence=0.9,
        joint_coverage=1.0,
    )
    monkeypatch.setattr(kinematic_cut, "dominant_motion_signal", lambda _: signal)
    monkeypatch.setattr(
        kinematic_cut,
        "_distinct_end_state_proposals",
        lambda *args, **kwargs: [
            kinematic_cut.CutProposal(0.5, 3.0, "distinct_end_state", 0.9)
        ],
    )
    monkeypatch.setattr(kinematic_cut, "_distinct_end_state_excursion_proposals", lambda *args, **kwargs: [])
    samples = _samples(lambda _: 0.55)

    proposals = kinematic_cut.propose_source_cut(
        contract={
            "completionMode": "distinct_end_state",
            "startPoseConstraints": {"handHeight": "above_head"},
            "endPoseConstraints": {"handHeight": "shoulder_chest"},
        },
        dominant_pose_samples=samples,
        max_proposals=1,
    )

    assert proposals == []


def test_low_confidence_keypoints_are_not_used_as_boundary_evidence():
    samples = _samples(lambda _: 0.10)
    for sample in samples:
        for name in ("left_wrist", "right_wrist"):
            sample["keypoints"][name][2] = 0.2

    parsed = kinematic_cut.parse_dominant_pose_samples(samples)

    assert parsed
    assert all("left_wrist" not in frame.keypoints and "right_wrist" not in frame.keypoints for frame in parsed)
    assert all(kinematic_cut.pose_state_score(frame, {"handHeight": "above_head"}) == 0.0 for frame in parsed)


def test_loop_proposal_rejects_fast_opposite_boundary_motion():
    samples = _samples(lambda _: 0.55)
    for sample in samples:
        time = sample["timeSeconds"]
        if time in (1.875, 2.125):
            offset = -0.03 if time == 1.875 else 0.03
        elif time in (5.875, 6.125):
            offset = 0.03 if time == 5.875 else -0.03
        else:
            offset = 0.0
        for point in sample["keypoints"].values():
            point[0] += offset
    frames = kinematic_cut.parse_dominant_pose_samples(samples)
    proposal = kinematic_cut.CutProposal(2.0, 6.0, "cycle_return_to_start", 0.8)

    assert kinematic_cut._proposal_observation_stats(
        proposal,
        frames,
        {"completionMode": "return_to_start", "startPoseConstraints": {"kneeState": "extended"}},
    ) is None


def test_loop_proposal_accepts_quiet_true_apex_boundaries():
    frames = kinematic_cut.parse_dominant_pose_samples(
        _samples(
            lambda _: 0.55,
            flexion_at=lambda time: 0.0 if time < 2.0 or time >= 6.0 else 1.0,
        )
    )
    proposal = kinematic_cut.CutProposal(1.5, 6.5, "cycle_return_to_start", 0.8)

    stats = kinematic_cut._proposal_observation_stats(
        proposal,
        frames,
        {"completionMode": "return_to_start", "startPoseConstraints": {"kneeState": "extended"}},
    )

    assert stats is not None
    assert stats["startBoundarySpeedTorsoPerSecond"] <= kinematic_cut.LOOP_BOUNDARY_QUIET_SPEED_TORSO_PER_SECOND
    assert stats["endBoundarySpeedTorsoPerSecond"] <= kinematic_cut.LOOP_BOUNDARY_QUIET_SPEED_TORSO_PER_SECOND
