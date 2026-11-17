import hashlib
from copy import deepcopy

from exercise_motion_pkg import foot_contact_observation
from exercise_motion_pkg import source_support_tracking
from exercise_motion_pkg.body_support_observation import (
    POLICY_VERSION,
    _CONTACT_TIMELINE_FOOT_BATCH_SIZE,
)
from exercise_motion_pkg.support_geometry import pre_reconstruction_source_support_readiness
from exercise_motion_pkg.wave_pipeline import (
    _refresh_source_foot_contacts_from_dense_sole_review,
)


def _source_evidence(tmp_path):
    source_video = tmp_path / "source.mp4"
    source_video.write_bytes(b"exact source video")
    digest = hashlib.sha256(source_video.read_bytes()).hexdigest()
    frame_count = 12
    states = ["full_sole"] * frame_count
    chunk_count = (frame_count + _CONTACT_TIMELINE_FOOT_BATCH_SIZE - 1) // _CONTACT_TIMELINE_FOOT_BATCH_SIZE
    observation = {
        "status": "observed",
        "source": "exact_source_visual_support_observation",
        "sourceVideoSha256": digest,
        "policyVersion": POLICY_VERSION,
        "observation": {
            "leftFoot": "stationary_full_sole",
            "leftFootSurface": "ground",
            "rightFoot": "stationary_full_sole",
            "rightFootSurface": "ground",
        },
    }
    patch = {
        "available": True,
        "sourceVideoSha256": digest,
        "sourceFrameCount": frame_count,
        "sourceFps": 25.0,
        "sourceTimeBasis": "absolute_source_video",
        "sourceTimeOriginSec": 0.0,
        "sourceTimesSec": [index / 25.0 for index in range(frame_count)],
        "feet": {
            side: {"states": list(states)}
            for side in ("left", "right")
        },
        "contacts": [],
        "materialStationarityEvidence": {
            "available": False,
            "policyVersion": source_support_tracking.FOOT_MATERIAL_POLICY_VERSION,
            "episodes": [],
            "reason": "no_proposed_full_sole_episodes",
        },
    }
    review = {
        "sourceVideoSha256": digest,
        "sourceFrameCount": frame_count,
        "framesPerChunk": _CONTACT_TIMELINE_FOOT_BATCH_SIZE,
        "feet": {
            side: {
                "reviewedFrameCount": frame_count,
                "confirmed": True,
                "decisions": ["stationary_full_sole_ground"] * chunk_count,
            }
            for side in ("left", "right")
        },
    }
    evidence = {
        "sourceVideoSha256": digest,
        "bodySupportObservation": observation,
        "footPatchEvidence": patch,
        "stationarySoleIntervalReview": review,
        "contacts": [],
    }
    return source_video, digest, evidence, states


def _observations(digest, frame_count):
    joints = {
        "left_heel": {"image": [0.40, 0.80], "confidence": 0.95},
        "left_toe": {"image": [0.46, 0.80], "confidence": 0.95},
        "right_heel": {"image": [0.54, 0.80], "confidence": 0.95},
        "right_toe": {"image": [0.60, 0.80], "confidence": 0.95},
    }
    return {
        "available": True,
        "sourceVideoSha256": digest,
        "imageWidth": 640,
        "imageHeight": 360,
        "frames": [
            {"timeSeconds": index / 25.0, "joints": deepcopy(joints)}
            for index in range(frame_count)
        ],
    }


def test_dense_sole_review_derivation_closes_before_readiness(tmp_path, monkeypatch):
    source_video, digest, evidence, states = _source_evidence(tmp_path)
    frame_count = len(states)
    observations = _observations(digest, frame_count)
    material_calls = []

    def classify_foot_contacts(_observations, _evidence, _source_pose, *_args, **_kwargs):
        patch = deepcopy(evidence["footPatchEvidence"])
        patch["contacts"] = [{
            "jointName": f"{side}_foot",
            "supportKind": "observed_foot_patch",
            "contactState": "full_sole",
            "contactMotion": "unknown",
            "startFrame": 0,
            "endFrame": frame_count - 1,
            "startRatio": 0.0,
            "endRatio": 1.0,
            "confidence": 0.8,
            "source": "observed_heel_and_forefoot",
        } for side in ("left", "right")]
        return patch

    def track_material(_video_path, _observations, _patch, episodes, *, cache_dir):
        material_calls.append(list(episodes))
        results = []
        for episode in episodes:
            if episode["side"] == "right":
                results.append({
                    **episode,
                    "sourceVideoSha256": digest,
                    "status": "failed",
                    "passed": False,
                    "reason": "material_motion_exceeds_stationary_tolerance",
                    "heel": {"reference": "registered_scene"},
                    "toe": {"reference": "registered_scene"},
                })
            else:
                results.append({
                    **episode,
                    "sourceVideoSha256": digest,
                    "status": "unresolved",
                    "passed": None,
                    "reason": "foot_material_identity_or_visibility_incomplete",
                })
        return {
            "available": True,
            "policyVersion": source_support_tracking.FOOT_MATERIAL_POLICY_VERSION,
            "sourceVideoSha256": digest,
            "episodes": results,
        }

    monkeypatch.setattr(foot_contact_observation, "classify_foot_contacts", classify_foot_contacts)
    monkeypatch.setattr(foot_contact_observation, "observe_foot_landmarks", lambda *_args, **_kwargs: observations)
    monkeypatch.setattr(source_support_tracking, "observe_foot_material_episodes", track_material)

    # The persisted dense review alone is admitted because its derived material
    # evidence is still the stale "no proposed episodes" record.
    stale_readiness = pre_reconstruction_source_support_readiness(deepcopy(evidence))
    assert stale_readiness["passed"] is True
    assert evidence["footPatchEvidence"]["materialStationarityEvidence"]["reason"] == (
        "no_proposed_full_sole_episodes"
    )

    refreshed = _refresh_source_foot_contacts_from_dense_sole_review(
        deepcopy(evidence), source_video, {"frames": []},
    )

    assert refreshed is not None
    assert material_calls, "dense review must drive the shared material derivation"
    right_episode = next(
        row for row in refreshed["footPatchEvidence"]["materialStationarityEvidence"]["episodes"]
        if row["side"] == "right"
    )
    assert right_episode["passed"] is False
    # Derived contacts are not fabricated into stationary source facts.
    assert refreshed["footPatchEvidence"]["feet"]["right"]["states"] == states
    assert all(
        contact.get("contactMotion") != "stationary"
        for contact in refreshed["contacts"]
        if str(contact.get("jointName") or "").endswith("_foot")
    )
    assert refreshed["stationarySoleIntervalReview"] == evidence["stationarySoleIntervalReview"]
    assert refreshed["bodySupportObservation"] == evidence["bodySupportObservation"]
    assert refreshed["sourceVideoSha256"] == digest

    readiness = pre_reconstruction_source_support_readiness(refreshed)
    assert readiness["passed"] is False
    assert readiness["unresolvedSides"] == ["right"]
    assert "source_support_contact_evidence_incomplete" in readiness["rejectionReasons"]
