from copy import deepcopy
import json

from exercise_motion_pkg.body_support_observation import (
    CONTACT_TIMELINE_POLICY_VERSION, POLICY_VERSION,
    _contact_timeline_candidates, _validated_contact_timeline_response,
    observed_body_support_contacts, validated_body_support_contact_timeline,
)
from exercise_motion_pkg.bake_and_rank import body_support_contract_evidence_status


def test_moving_region_review_does_not_authorize_stationary_joint_anchors():
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'sourceTimeSec': i / 10., 'joints': {
            'left_shoulder': [.3 + i * .04, .3],
            'right_shoulder': [.5 + i * .04, .3], 'nose': [.5, .1],
            'left_hip': [.4, .6], 'left_ankle': [.4, .9]},
         'jointConfidence': {'left_shoulder': .95, 'right_shoulder': .95, 'left_hip': .95}}
        for i in range(6)]}
    observation = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
                   'sourceVideoSha256': 'a' * 64, 'policyVersion': POLICY_VERSION,
                   'sourceClock': 'video_frame_zero_seconds',
                   'observation': {'upperBack': 'stationary_support',
                                   'upperBackContactSurface': 'bench'}}
    evidence = {'bodySupportObservation': observation, 'sourceVideoSha256': 'a' * 64}
    original = deepcopy(evidence)
    candidates = _contact_timeline_candidates(pose, evidence)
    assert len(candidates) == 7
    assert sum(row.get('landmark') == 'region' for row in candidates) == 3
    assert all(row['sourceTrackStationary'] is False for row in candidates)
    assert all([.4, .6] in row['regionPoints'] for row in candidates)
    assert evidence == original
    for row in candidates:
        row.update(sourceFrameIndex=round(row['sourceTimeSec'] * 10), sourceFps=10.)
    rows = _validated_contact_timeline_response(json.dumps({'samples': [
        {'sampleId': row['sampleId'], 'contactState': 'direct_contact',
         'surface': 'bench', 'visible': True} for row in candidates]}), candidates)
    assert all(row['sourceTrackStationary'] is False for row in rows)
    observation['contactTimeline'] = {
        'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
        'source': 'exact_source_visual_contact_timeline', 'sourceVideoSha256': 'a' * 64,
        'sourceClock': 'video_frame_zero_seconds', 'status': 'observed', 'samples': rows}
    assert validated_body_support_contact_timeline(observation) == rows
    assert observed_body_support_contacts(observation) == set()
    contract = {'bodySupportRequirements': {'required': [
        {'region': 'upper_back', 'side': 'center', 'surface': 'bench'}]}}
    pose_reference = {'sourceVideoSha256': 'a' * 64, 'pose': pose}
    assert body_support_contract_evidence_status(
        contract, evidence, source_pose=pose_reference)['status'] == 'passed'
    rows[0]['surface'] = 'floor'
    assert body_support_contract_evidence_status(
        contract, evidence, source_pose=pose_reference)['status'] == 'insufficient_evidence'
    rows[0]['surface'] = 'bench'
    observation['contactTimeline']['sourceVideoSha256'] = 'b' * 64
    assert body_support_contract_evidence_status(
        contract, evidence, source_pose=pose_reference)['status'] == 'insufficient_evidence'


def test_required_region_unknown_can_only_defer_reconstruction(monkeypatch, tmp_path):
    from exercise_motion_pkg import body_surface_evidence

    video = tmp_path / 'selected.mp4'
    video.write_bytes(b'exact source')
    digest = 'a' * 64
    source_pose = {'sourceVideoSha256': digest, 'pose': {'frames': [
        {'sourceTimeSec': 0.0}, {'sourceTimeSec': 0.1}, {'sourceTimeSec': 0.2}]}}
    requirement = {
        'disposition': 'required', 'region': 'upper_back', 'side': 'center',
        'declaredSide': 'center', 'surface': 'bench', 'contactMode': 'stationary',
    }
    review = {
        'contactId': 'upper-back-center', 'requirement': requirement,
        'record': {
            'contactId': 'upper-back-center',
            'bodyRegion': {'name': 'upper_back', 'side': 'center'},
            'contactMode': 'stationary',
            'sourceEvidence': {'observations': [{'surfaceId': 'bench'}]},
        },
        'receiptPath': 'verified-review.json', 'receiptSha256': 'b' * 64,
    }
    evidence = {
        'sourceVideoSha256': digest,
        'bodySurfaceContactEvidence': {
            'sourceVideoSha256': digest, 'status': 'insufficient_evidence',
            'reviews': [review],
        },
    }
    states = ['direct_contact', 'unknown', 'direct_contact']

    def verify(*_args, **_kwargs):
        return {
            'coverage': {
                'allCanonicalPoseFramesObserved': True,
                'canonicalPoseFrameCount': 3,
            },
            'samples': [{'contactState': state} for state in states],
        }

    monkeypatch.setattr(body_surface_evidence, 'verify_body_surface_contact_evidence', verify)
    contract = {'bodySupportRequirements': {'required': [
        {'region': 'upper_back', 'side': 'center', 'surface': 'bench',
         'contactMode': 'stationary'}], 'prohibited': []}}
    pending = body_support_contract_evidence_status(
        contract, evidence, source_pose=source_pose, selected_video_path=video)
    assert pending['status'] == 'insufficient_evidence'
    assert len(pending['pendingInferenceRequirements']) == 1
    assert pending['pendingInferenceRequirements'][0]['sourceApproval'] is False
    assert pending['pendingInferenceRequirements'][0]['geometryApproval'] is False

    states[:] = ['direct_contact', 'no_contact', 'unknown']
    rejected = body_support_contract_evidence_status(
        contract, evidence, source_pose=source_pose, selected_video_path=video)
    assert rejected['status'] == 'contradicted'
    assert 'pendingInferenceRequirements' not in rejected

    unapproved = body_support_contract_evidence_status(
        {'bodySupportDiscoveryHints': {'required': [
            {'region': 'upper_back', 'side': 'center', 'surface': 'bench'}]}},
        evidence, source_pose=source_pose, selected_video_path=video)
    assert unapproved == {'status': 'not_required', 'failures': []}


def test_pending_regional_support_stops_after_raw_reconstruction(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from exercise_motion_pkg import bake_and_rank as bake

    candidate = bake.RankedCandidate(
        exercise_index=0, candidate_rank=0, exercise_id='hip',
        exercise_name='Barbell Hip Thrust', exercise_slug='hip-thrust',
        candidate={'videoId': 'retained-source'},
    )
    request = bake.BakeAndRankRequest(
        candidates_json=tmp_path / 'candidates.json',
        workspace=tmp_path / 'workspace', body_model_root=None,
    )
    pending_requirement = {
        'requirement': {'region': 'upper_back', 'side': 'center', 'surface': 'bench'},
        'sourceVideoSha256': 'a' * 64, 'sourcePoseReferenceSha256': 'b' * 64,
        'reviewContactIds': ['upper-back-center'], 'observedStates': ['direct_contact', 'unknown'],
        'sourceApproval': False, 'geometryApproval': False,
    }
    preflight_evidence = {'sourceVideoSha256': 'a' * 64}
    monkeypatch.setattr(bake, 'evaluate_source_candidate_gate', lambda *_a, **_k: {'passed': True})
    monkeypatch.setattr(bake, 'preflight_candidate_body_support', lambda *_a, **_k: (
        preflight_evidence, {'status': 'pending_inference', 'failures': [
            'required_upper_back_center_support_unobserved'],
            'pendingInferenceRequirements': [pending_requirement],
            'sourceApproval': False, 'geometryApproval': False},
    ))
    monkeypatch.setattr(bake, 'generate_candidate_motion', lambda *_a, **_k: SimpleNamespace(
        raw_motion_json_path=tmp_path / 'raw.json',
        cleaned_motion_json_path=tmp_path / 'cleaned.json',
        preview_html_path=tmp_path / 'preview.html', timings=None,
    ))
    monkeypatch.setattr(bake, 'generation_to_manifest', lambda _result: {'generated': True})
    monkeypatch.setattr(bake, 'evaluate_generated_motion_recovery_gate', lambda **_k: {'passed': True})
    preview_calls = []

    result = bake.process_ranked_candidate(
        candidate, request=request, preview_baker=lambda *_a, **_k: preview_calls.append(True),
        review_items=[], review_item_entries=[], support_dominance_classifier=None,
    )
    assert result['status'] == 'pending_support_inference'
    assert result['pendingSupportInference']['fitStarted'] is False
    assert result['pendingSupportInference']['previewRendered'] is False
    assert result['pendingSupportInference']['publicationEligible'] is False
    assert result['sourceSupportContractEvidence']['status'] == 'pending_inference'
    assert preview_calls == []


def test_nonstationary_foot_timeline_cannot_authorize_contact():
    timeline = {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline', 'sourceVideoSha256': 'a' * 64,
                'sourceClock': 'video_frame_zero_seconds', 'status': 'observed', 'samples': [{
                    'sampleId': 'foot', 'sourceTimeSec': 0., 'sourceFrameIndex': 0,
                    'sourcePoseFrameIndex': 0, 'sourceFps': 10., 'side': 'left',
                    'landmark': 'foot', 'contactState': 'full_sole', 'surface': 'ground',
                    'visible': True, 'sourceTrackStationary': False}]}
    assert validated_body_support_contact_timeline(timeline) is None
    timeline['samples'][0]['contactRegion'] = 'upper_back'
    assert validated_body_support_contact_timeline(timeline) is None
    row = timeline['samples'][0]
    row.update(landmark='joint', jointName='left_shoulder', sourceTrackStationary=True)
    assert validated_body_support_contact_timeline(timeline) is None


def test_review_only_foot_fact_can_inform_image_classification_without_pinning():
    from exercise_motion_pkg.body_support_observation import materialize_timed_visual_contact_points
    from exercise_motion_pkg.foot_contact_observation import _reviewed_sole_mode_masks

    timeline = {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline', 'sourceVideoSha256': 'a' * 64,
                'sourceClock': 'video_frame_zero_seconds', 'status': 'observed', 'samples': [{
                    'sampleId': 'foot-review', 'sourceTimeSec': 0., 'sourceFrameIndex': 0,
                    'sourcePoseFrameIndex': 0, 'sourceFps': 10., 'side': 'left',
                    'landmark': 'foot', 'contactState': 'full_sole', 'surface': 'ground',
                    'visible': True, 'sourceTrackStationary': False, 'reviewOnly': True}]}
    assert validated_body_support_contact_timeline(timeline)
    evidence = {'sourceVideoSha256': 'a' * 64, 'bodySupportObservation': timeline}
    neutral, contact, forefoot, heel, stationary, exact_fullsole = _reviewed_sole_mode_masks(evidence, {
        'sourceVideoSha256': 'a' * 64, 'frames': [{'timeSeconds': 0.}]}, 'left')
    assert neutral.tolist() == contact.tolist() == exact_fullsole.tolist() == [True]
    assert forefoot.tolist() == heel.tolist() == stationary.tolist() == [False]
    materialize_timed_visual_contact_points(evidence, [{'sourceTimeSec': 0.}],
                                          ['left_ankle', 'left_foot'], ground_contact_mode='continuous')
    assert evidence['supportContacts'] == []
    timeline['samples'][0]['sourceTrackStationary'] = True
    assert validated_body_support_contact_timeline(timeline) is None


def test_unknown_patch_gaps_are_reviewed_outside_stationary_intervals():
    times = [i / 10. for i in range(6)]
    pose = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'sourceTimeSec': time, 'joints': {'left_ankle': [.4, .8],
                                         'left_heel': [.38, .82], 'left_toe': [.46, .82]},
         'jointConfidence': {'left_ankle': .95, 'left_heel': .95, 'left_toe': .95}}
        for time in times]}
    evidence = {'footPatchEvidence': {'sourceTimesSec': times, 'feet': {'left': {
        'states': ['full_sole', 'full_sole', 'unknown', 'full_sole', 'unknown', 'full_sole']}}}}
    original = deepcopy(evidence)
    rows = _contact_timeline_candidates(pose, evidence)
    assert [row['poseFrameIndex'] for row in rows] == [2, 4]
    assert all(row['reviewOnly'] and row['sourceTrackStationary'] is False for row in rows)
    assert evidence == original


def test_support_preflight_routes_required_upper_back_through_regional_owner(monkeypatch, tmp_path):
    from exercise_motion_pkg import bake_and_rank as bake

    source = tmp_path / 'input' / 'selected_segment.mp4'
    source.parent.mkdir()
    source.write_bytes(b'exact source fixture')
    calls = []
    staged_evidence = {'sourceVideoSha256': 'a' * 64}
    staged_status = {'status': 'pending_inference', 'pendingInferenceRequirements': [
        {'requirement': {'region': 'upper_back', 'side': 'center', 'surface': 'bench'}}]}

    def observe_stage(workspace, contract, video, caption):
        calls.append((workspace, contract, video, caption))
        return staged_evidence, staged_status

    monkeypatch.setattr(bake, '_preflight_source_support_stage', observe_stage)
    contract = {'bodySupportRequirements': {'required': [
        {'region': 'upper_back', 'side': 'center', 'surface': 'bench'}]}}
    caption = lambda: None
    evidence, status = bake.preflight_candidate_body_support(tmp_path, contract, caption)
    assert status['status'] == 'pending_inference'
    assert evidence is staged_evidence
    assert calls == [(tmp_path, contract, source, caption)]


def test_required_ground_foot_unknown_material_is_pending_only_with_exact_bindings(
    monkeypatch, tmp_path,
):
    import hashlib
    from exercise_motion_pkg import body_support_observation as bso
    from exercise_motion_pkg import bake_and_rank as bake
    from exercise_motion_pkg import pose_fidelity, source_frame_clock
    from exercise_motion_pkg import source_support_stage as stage
    from exercise_motion_pkg.foot_contact_observation import POLICY_VERSION
    from exercise_motion_pkg.source_support_tracking import FOOT_MATERIAL_POLICY_VERSION

    video = tmp_path / "selected.mp4"
    video.write_bytes(b"exact selected cut")
    video_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    pose = {
        "sourceVideoSha256": video_sha,
        "coordinateSpace": "normalized_image_xy",
        "sourceTimeOriginSec": 0.0,
        "sourcePoseSampleBoundaryToleranceSeconds": 1.0 / 30.0,
        "frames": [{"sourceTimeSec": index / 15.0} for index in range(3)],
    }
    pose_reference = {"sourceVideoSha256": video_sha, "pose": pose}
    reference_path = tmp_path / "pose-reference.json"
    reference_path.write_text("pose reference", encoding="utf-8")
    reference_sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    clock_path = tmp_path / "clock.json"
    clock_path.write_text("clock receipt", encoding="utf-8")
    fps, count = 30.0, 5
    clock = {"outputFps": fps, "outputFrameCount": count,
             "frames": [{"outputFrameIndex": index, "sourceFrameIndex": 60 + index,
                         "sourceTimeSec": 2.0 + index / fps}
                        for index in range(count)]}
    monkeypatch.setattr(stage, "_pose_reference_receipt_from_workspace",
                        lambda _workspace: (reference_path, reference_sha))
    monkeypatch.setattr(source_frame_clock, "source_frame_clock_path_for_video",
                        lambda _video: clock_path)
    monkeypatch.setattr(source_frame_clock, "load_verified_source_frame_clock",
                        lambda *_a, **_k: clock)
    monkeypatch.setattr(pose_fidelity, "_canonical_source_pose_sha256",
                        lambda _pose: "pose-payload-sha")
    monkeypatch.setattr(bake, "source_pose_support_contract_fingerprint",
                        lambda _contract: "contract-fingerprint")
    monkeypatch.setattr(bso, "validated_body_support_answer", lambda _observation: {
        "leftFoot": "stationary_full_sole", "leftFootSurface": "ground",
        "rightFoot": "stationary_full_sole", "rightFootSurface": "ground",
    })
    monkeypatch.setattr(bso, "validated_body_support_contact_timeline", lambda *_a, **_k: [])

    contract = {"bodySupportRequirements": {"required": [
        {"region": "foot", "side": "both", "surface": "ground"},
    ]}}
    states = {
        "left": ["unknown"] * count,
        "right": ["unknown", "toe_only", "unknown", "toe_only", "unknown"],
    }
    evidence = {
        "sourceVideoSha256": video_sha,
        "sourcePoseSupportEvidencePolicyVersion": 3,
        "sourcePoseSupportContractFingerprint": "contract-fingerprint",
        "bodySupportObservation": {"sourceVideoSha256": video_sha},
        "footPatchEvidence": {
            "available": True, "policyVersion": POLICY_VERSION,
            "materialStationarityPolicyVersion": FOOT_MATERIAL_POLICY_VERSION,
            "sourceVideoSha256": video_sha, "sourcePoseVideoSha256": video_sha,
            "sourcePosePayloadSha256": "pose-payload-sha", "sourcePoseFrameCount": 3,
            "sourceFrameCount": count, "sourceFps": fps,
            "sourceTimeBasis": "absolute_source_video", "sourceTimeOriginSec": 0.0,
            "sourceTimesSec": [index / fps for index in range(count)],
            "feet": {side: {"states": values} for side, values in states.items()},
        },
    }
    readiness = {"passed": False,
                 "rejectionReasons": ["source_support_contact_evidence_incomplete"],
                 "unresolvedSides": ["left", "right"]}
    pending = stage._pending_required_foot_ground_material_inference(
        tmp_path, contract, evidence, readiness, video, pose, pose_reference,
    )
    assert [item["requirement"]["side"] for item in pending] == ["left", "right"]
    assert pending[0]["unknownFrameIndexes"] == list(range(count))
    assert pending[1]["observedPatchStates"] == ["toe_only", "unknown"]
    assert all(item["sourceApproval"] is False and item["geometryApproval"] is False
               for item in pending)

    readiness["rejectionReasons"] = ["body_surface_contact_source_evidence_unavailable"]
    pending = stage._pending_required_foot_ground_material_inference(
        tmp_path, contract, evidence, readiness, video, pose, pose_reference,
    )
    assert len(pending) == 2
    assert all(item["accountsForReadinessReasons"] == [] for item in pending)
    readiness["rejectionReasons"] = ["source_support_contact_evidence_incomplete"]

    # A qualified absence or broken frame-time binding cannot enter pending inference.
    evidence["footPatchEvidence"]["feet"]["right"]["states"][2] = "airborne"
    assert stage._pending_required_foot_ground_material_inference(
        tmp_path, contract, evidence, readiness, video, pose, pose_reference,
    ) == []
    evidence["footPatchEvidence"]["feet"]["right"]["states"][2] = "unknown"
    evidence["footPatchEvidence"]["sourceTimesSec"][2] += .1
    assert stage._pending_required_foot_ground_material_inference(
        tmp_path, contract, evidence, readiness, video, pose, pose_reference,
    ) == []
