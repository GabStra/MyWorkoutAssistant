import math

import pytest

from exercise_motion_pkg.bake_and_rank import (
    dominant_observable_motion_phase_track,
    materialized_observable_motion_spec_metrics,
    phase_track_has_return,
    source_foot_orientation_phase_tracks,
)


def _source_fixture(angles, *, confidence=0.9, digest="a" * 64, origin=0.0):
    times = [index / 10 for index in range(len(angles))]
    pose = {
        "sourceTimeOriginSec": origin,
        "frames": [
            {"timeSec": time, "sourceTimeSec": origin + time, "joints": {}}
            for time in times
        ],
    }
    patch = {
        "available": True,
        "sourceVideoSha256": digest,
        "sourceTimeBasis": "absolute_source_video",
        "sourceTimeOriginSec": origin,
        "feet": {"left": {"rayObservations": [
            {"sourceTimeSec": origin + time,
             "ankleToToeImageRay": [math.cos(angle), math.sin(angle)],
             "confidence": confidence}
            for time, angle in zip(times, angles)
        ]}},
    }
    return pose, {"sourceVideoSha256": digest, "footPatchEvidence": patch}


def _angles_with_return():
    return [0.02 * math.sin(2 * math.pi * index / 15) for index in range(16)]


def test_measured_foot_orientation_can_supply_generic_distal_phase_and_amplitude():
    pose, evidence = _source_fixture(_angles_with_return())
    tracks = source_foot_orientation_phase_tracks(pose, evidence)
    assert "left" in tracks
    assert tracks["left"]["unit"] == "aspect_corrected_image_plane_radian"
    assert tracks["left"]["rangeRatio"] > 0.0

    spec = {
        "primaryMovingRegions": ["feet"], "referenceRegions": ["knees"],
        "primaryAxis": "vertical", "motionPattern": "distal_limb_vertical",
    }
    phase = dominant_observable_motion_phase_track(
        pose["frames"], spec=spec, body_span=1.0, foot_orientation_tracks=tracks,
    )
    assert phase["selection"] == "observable_source_foot_orientation"
    assert phase["motionUnit"] == "aspect_corrected_image_plane_radian"
    assert phase_track_has_return(phase["values"])

    metrics = materialized_observable_motion_spec_metrics(
        pose["frames"], spec=spec, body_span=1.0, foot_orientation_tracks=tracks,
    )
    assert metrics["footOrientationRangeRatio"] == pytest.approx(tracks["left"]["rangeRatio"])
    assert metrics["footOrientationRangeUnit"] == "fraction_of_pi_aspect_corrected_image_plane_radian"


@pytest.mark.parametrize("confidence,digest,origin", [
    (0.79, "a" * 64, 0.0), (0.9, "b" * 64, 0.0), (0.9, "a" * 64, 1.0),
])
def test_uncertain_or_unbound_rays_fall_back_without_a_foot_track(confidence, digest, origin):
    pose, evidence = _source_fixture(_angles_with_return(), confidence=confidence)
    evidence["sourceVideoSha256"] = "a" * 64
    evidence["footPatchEvidence"]["sourceVideoSha256"] = digest
    evidence["footPatchEvidence"]["sourceTimeOriginSec"] = origin
    assert source_foot_orientation_phase_tracks(pose, evidence) == {}


def test_one_way_foot_rotation_has_amplitude_but_no_return_phase():
    angles = [index * 0.005 for index in range(16)]
    pose, evidence = _source_fixture(angles)
    tracks = source_foot_orientation_phase_tracks(pose, evidence)
    assert tracks["left"]["rangeRatio"] > 0.0
    spec = {"primaryMovingRegions": ["feet"], "referenceRegions": ["knees"],
            "primaryAxis": "vertical", "motionPattern": "distal_limb_vertical"}
    phase = dominant_observable_motion_phase_track(
        pose["frames"], spec=spec, body_span=1.0, foot_orientation_tracks=tracks,
    )
    assert phase is not None
    assert not phase_track_has_return(phase["values"])


def test_static_rays_do_not_create_observable_amplitude_or_phase_track():
    pose, evidence = _source_fixture([0.1] * 16)
    tracks = source_foot_orientation_phase_tracks(pose, evidence)
    assert tracks["left"]["rangeRatio"] == pytest.approx(0.0)
    spec = {"primaryMovingRegions": ["feet"], "referenceRegions": ["knees"],
            "primaryAxis": "vertical", "motionPattern": "distal_limb_vertical"}
    assert dominant_observable_motion_phase_track(
        pose["frames"], spec=spec, body_span=1.0, foot_orientation_tracks=tracks,
    ) is None
