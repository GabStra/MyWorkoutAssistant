import copy

import pytest

from exercise_motion_pkg import bake_and_rank as b


def test_baked_contacts_are_rebased_to_selected_frames_without_changing_source():
    evidence = {"contacts": [{"jointName": "left_foot", "startRatio": 0., "endRatio": .5},
                              {"jointName": "right_foot", "startRatio": .8, "endRatio": 1.}],
                "footContactCandidates": [{"jointName": "left_ankle", "startRatio": .2, "endRatio": .6}],
                "footPatchEvidence": {"feet": {"left": {"states": list(range(101))}}}}
    original = copy.deepcopy(evidence)
    payload = {"source": {"frameCount": 101}, "frames": [{"sourceFrameIndex": 25}, {"sourceFrameIndex": 75}],
               "selectedPreviewSettings": {"sourceFootSupportEvidence": evidence}}
    result = b.baked_source_support_evidence(payload)
    assert result["contacts"] == [{
        "jointName": "left_foot", "startRatio": 0., "endRatio": .5,
        "startFrame": 0, "endFrame": 25,
    }]
    assert result["contacts"][0]["startFrame"] == 0
    assert result["contacts"][0]["endFrame"] == 25
    assert result["footContactCandidates"] == [{
        "jointName": "left_ankle", "startRatio": 0., "endRatio": .7,
        "startFrame": 0, "endFrame": 35,
    }]
    assert result["footPatchEvidence"]["feet"]["left"]["states"] == list(range(101))
    assert evidence == original
    payload["sourceFootSupportEvidence"] = result
    assert b.baked_source_support_evidence(payload) is result  # Do not slice twice.


def test_confirmed_stationary_feet_expand_sparse_contacts_to_full_clip_intervals():
    evidence = {
        "contacts": [
            {"jointName": "left_ankle", "startFrame": 6, "endFrame": 22, "contactMotion": "stationary"},
            {"jointName": "right_ankle", "startFrame": 24, "endFrame": 37, "contactMotion": "stationary"},
        ],
        "sharedSupportPlaneY": 0.0,
        "bodySupport": {
            "required": True,
            "status": "confirmed",
            "stationaryJoints": ["left_ankle", "right_ankle"],
        },
    }

    intervals = b.source_contact_intervals_from_evidence(evidence, frame_count=95)

    by_joint = {interval["jointName"]: interval for interval in intervals}
    assert set(by_joint) == {"left_ankle", "right_ankle"}
    for interval in by_joint.values():
        assert interval["startFrame"] == 0
        assert interval["endFrame"] == 94
        assert interval["supportKind"] == "observed_foot_patch"
        assert interval["contactMotion"] == "stationary"


def test_source_intervals_keep_expanded_fit_frame_runs():
    evidence = {
        "contacts": [{
            "jointName": "left_foot",
            "startRatio": 0.2,
            "endRatio": 0.8,
            "contactMotion": "stationary",
            "_fitFrameRuns": [[3, 5], [10, 12]],
            "_fitFrameCount": 20,
        }]
    }

    intervals = b.source_contact_intervals_from_evidence(evidence, frame_count=20)

    assert [(item["startFrame"], item["endFrame"]) for item in intervals] == [
        (3, 5),
        (10, 12),
    ]

    stale_fit_clock = {
        "contacts": [{
            **evidence["contacts"][0],
            "_fitFrameCount": 19,
        }]
    }
    assert b.source_contact_intervals_from_evidence(stale_fit_clock, frame_count=20) == []


def test_mapped_patch_unknown_endpoint_is_not_expanded_by_legacy_support_summary():
    evidence = {
        "footPatchEvidence": {"available": True, "feet": {
            side: {"states": ["full_sole"] * 82 + ["unknown"]}
            for side in ("left", "right")
        }},
        "contacts": [
            {"jointName": f"{side}_foot", "supportKind": "observed_foot_patch",
             "contactState": "full_sole", "contactMotion": "stationary",
             "anchorGroupId": f"{side}:foot:0",
             "_fitFrameRuns": [[0, 81]], "_fitFrameCount": 83}
            for side in ("left", "right")
        ],
        "feet": {side: {"jointName": f"{side}_ankle", "continuousSupport": True}
                 for side in ("left", "right")},
        "sharedSupportPlaneY": 0.,
        "bodySupport": {"required": True, "status": "confirmed",
                         "stationaryJoints": ["left_foot", "right_foot"]},
    }

    intervals = b.source_contact_intervals_from_evidence(evidence, frame_count=83)

    assert [(row["jointName"], row["startFrame"], row["endFrame"])
            for row in intervals if row["supportKind"] == "observed_foot_patch"] == [
                ("left_foot", 0, 81), ("right_foot", 0, 81),
            ]
    assert not any(row["endFrame"] == 82 for row in intervals)


def test_baked_source_support_override_rebases_the_original_interval_once():
    original = {"contacts": [{"jointName": "left_foot", "startRatio": .2, "endRatio": .6}]}
    payload = {
        "source": {"frameCount": 101},
        "frames": [{"sourceFrameIndex": 40}, {"sourceFrameIndex": 60}],
        "sourceFootSupportEvidence": {"contacts": []},
    }
    result = b.baked_source_support_evidence(payload, evidence_override=original)
    assert result["contacts"] == [{
        "jointName": "left_foot", "startRatio": 0., "endRatio": 1.,
        "startFrame": 0, "endFrame": 20,
    }]


def test_baked_contacts_use_verified_cut_clock_for_native_frame_indices():
    selected_sha = "a" * 64
    parent_sha = "b" * 64
    evidence = {
        "sourceVideoSha256": selected_sha,
        "contacts": [{
            "jointName": "left_foot",
            "startRatio": .6 / 3.1,
            "endRatio": 1.2 / 3.1,
        }],
        "footPatchEvidence": {
            "sourceVideoSha256": selected_sha,
            "sourceFps": 30.0,
            "sourceTimesSec": [index / 30. for index in range(94)],
            "feet": {"left": {"states": ["unknown"] * 94}},
        },
    }
    payload = {
        # The selected clip has 93 frames, while frame IDs and timestamps below
        # remain in the parent video's native clock (frames 62 through 150).
        "source": {"frameCount": 93},
        "frames": [
            {"sourceFrameIndex": source_frame, "sourceTimeSec": source_frame / 30.}
            for source_frame in range(62, 151)
        ],
        "sourcePoseCameraReference": {"sourceTimelineMapping": {
            "schemaVersion": 1,
            "verified": True,
            "mappingKind": "selected_segment_to_parent_source",
            "selectedSegmentSha256": selected_sha,
            "parentSourceSha256": parent_sha,
            "selectedStartSeconds": 2.,
            "selectedEndSeconds": 5.1,
            "selectedFrameClockReceiptSha256": "c" * 64,
            "selectedOutputFps": 30.0,
            "parentSourceFps": 30.0,
            "selectedFrameCount": 94,
            "selectedFrameLineage": [
                {"selectedFrameIndex": index, "selectedFrameTimeSec": index / 30.,
                 "parentSourceFrameIndex": 62 + index,
                 "parentSourceTimeSec": (62 + index) / 30.}
                for index in range(94)
            ],
        }},
        "selectedPreviewSettings": {"sourceFootSupportEvidence": evidence},
    }

    result = b.baked_source_support_evidence(payload)

    contact = result["contacts"][0]
    # The requested 2.0s crop begins before its first decoded exposure at
    # 62/30s; use the receipt lineage, not selectedStartSeconds arithmetic.
    assert contact["startFrame"] == 18
    assert contact["endFrame"] == 36
    assert contact["startRatio"] == pytest.approx(18 / 88)
    assert contact["endRatio"] == pytest.approx(36 / 88)
    assert contact["sourceStartTimeSec"] == pytest.approx((62 + 18) / 30.)
    assert result["footPatchEvidence"] == evidence["footPatchEvidence"]
    assert result["previewCrop"]["sourceTimelineMapping"] == "verified_selected_cut_to_parent"

    mismatched_payload = copy.deepcopy(payload)
    mismatched_payload["selectedPreviewSettings"]["sourceFootSupportEvidence"]["sourceVideoSha256"] = "c" * 64
    unresolved = b.baked_source_support_evidence(mismatched_payload)
    assert unresolved["contacts"] == []
    assert unresolved["previewCrop"]["sourceTimelineMapping"] == "unresolved"


def test_bake_without_contact_evidence_does_not_invent_ground_support():
    assert b.baked_source_support_evidence({"frames": []}) is None


def test_post_bake_solver_receives_retained_evidence_and_exports_its_floor(monkeypatch):
    joints = {"pelvis": [0., 1., 0.], "neck": [0., 1.7, 0.]}
    for side, x in (("left", -.2), ("right", .2)):
        joints.update({f"{side}_hip": [x, 1., 0.], f"{side}_knee": [x, .5, .2],
                       f"{side}_ankle": [x, 0., 0.], f"{side}_foot": [x, 0., .15]})
    evidence = {"contacts": [{"jointName": "left_foot", "contactState": "full_sole"}]}
    payload = {"fps": 30, "jointNames": list(joints), "frames": [
        {"timeSec": i / 30., "joints": copy.deepcopy(joints), "sourceJoints": copy.deepcopy(joints)} for i in range(8)],
        "selectedPreviewSettings": {"sourceFootSupportEvidence": evidence}}
    monkeypatch.setattr(b, "constrain_to_source_articulation_envelope", lambda source, proposed, **kw: (proposed, {"applied": False}))
    monkeypatch.setattr(b, "suppress_post_ik_anatomical_spikes", lambda clip: (clip, {"applied": False}))
    monkeypatch.setattr(b, "stabilize_distal_foot_heading", lambda clip: (clip, {"applied": False}))
    def contact_solver(clip, observed):
        assert observed == evidence
        return clip, {"applied": True, "supportPlaneY": -.02}
    monkeypatch.setattr(b, "stabilize_forefoot_ground_contacts", contact_solver)
    result, _ = b.constrain_baked_payload_to_source_articulation(payload, use_controlled_motion_fit=False)
    assert result["sourceFootSupportEvidence"] == evidence
    assert result["renderFloorY"] == pytest.approx(-.02)


def test_verified_pose_reaches_fit_entry_without_camera_registration(monkeypatch):
    from exercise_motion_pkg import body_support_observation as body_support
    from exercise_motion_pkg import controlled_motion as controlled
    from exercise_motion_pkg import foot_contact_observation as foot_contact
    from exercise_motion_pkg import support_geometry

    video_sha = "a" * 64
    source_pose = {
        "frames": [{"sourceTimeSec": 0., "joints": {
            "left_ankle": [0., 0.], "right_ankle": [1., 0.],
        }}],
        "sourcePoseSampleBoundaryToleranceSeconds": .04,
        "sourceTimeOriginSec": 0.,
        "sourceVideoSha256": video_sha,
        "imageWidth": 640,
        "imageHeight": 480,
    }
    patch = {
        "available": True,
        "source": "mediapipe_full_heel_forefoot",
        "policyVersion": foot_contact.POLICY_VERSION,
        "sourcePosePayloadSha256": foot_contact._source_pose_digest(source_pose),
        "sourcePoseFrameCount": 1,
        "sourcePoseSampleBoundaryToleranceSeconds": .04,
        "sourceVideoSha256": video_sha,
        "sourcePoseVideoSha256": video_sha,
        "sourceTimeBasis": "absolute_source_video",
        "sourceTimeOriginSec": 0.,
        "sourceTimesSec": [0.],
        "sourceFrameCount": 1,
        "imageWidth": 640,
        "imageHeight": 480,
        "feet": {side: {"states": ["unknown"], "rayObservations": []}
                 for side in ("left", "right")},
    }
    evidence = {"footPatchEvidence": patch, "contacts": []}
    joints = {"pelvis": [0., 1., 0.]}
    payload = {"fps": 30., "jointNames": ["pelvis"], "frames": [
        {"timeSec": 0., "joints": copy.deepcopy(joints),
         "sourceJoints": copy.deepcopy(joints)}],
        "sourceFootSupportEvidence": evidence}

    monkeypatch.setattr(b, "constrain_to_source_articulation_envelope",
                        lambda source, proposed, **kwargs: (proposed, {"applied": False}))
    monkeypatch.setattr(support_geometry, "declare_support_requirements", lambda *args: None)
    for name in ("materialize_body_support", "materialize_hand_support",
                 "materialize_knee_support", "materialize_observed_ground_contacts",
                 "materialize_ankle_support"):
        monkeypatch.setattr(body_support, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(body_support, "calibrate_material_sole_floor", lambda value: value)
    monkeypatch.setattr(controlled, "can_reuse_controlled_motion", lambda value: False)

    class FitReached(Exception):
        pass

    def stop_at_fit_entry(fit_payload, **kwargs):
        assert "sourcePoseCameraReference" not in fit_payload
        assert fit_payload["sourcePoseReference"] == source_pose
        assert controlled.source_foot_patch_pose_binding_failure(fit_payload) is None
        raise FitReached

    monkeypatch.setattr(controlled, "fit_controlled_motion", stop_at_fit_entry)
    with pytest.raises(FitReached):
        b.constrain_baked_payload_to_source_articulation(
            payload,
            source_foot_support_evidence=evidence,
            source_pose_reference=source_pose,
        )
