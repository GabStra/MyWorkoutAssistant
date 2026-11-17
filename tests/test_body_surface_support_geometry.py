import hashlib
import json
import sys
from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from test_body_surface_geometry import _poses

from exercise_motion_pkg.support_geometry import (
    evidence_is_complete, geometry_dependencies, geometry_errors,
    support_contact_readiness, support_evidence,
    validate_support_geometry,
)


def _payload(tmp_path, mode='stationary', *, bound=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    names, points = _poses()
    video_sha, pose_sha, clock_sha = ('a' * 64, 'b' * 64, 'c' * 64)
    observations = [{
        'sampleId': f'sample-{index}', 'sourceTimeSec': float(index),
        'sourcePoseFrameIndex': index, 'sourceFrameIndex': index,
        'sourceFps': 1., 'contactState': 'direct_contact', 'visible': True,
        'surfaceId': 'bench-top',
    } for index in range(len(points))]
    source = {
        'sourceVideoSha256': video_sha,
        'sourcePosePayloadSha256': pose_sha,
        'sourceFrameClockReceiptSha256': clock_sha,
        'observations': observations,
    }
    reviewed = {
        'schemaVersion': 1, 'contactId': 'shoulder-bench',
        'bodyRegion': {'name': 'shoulder', 'side': 'left'},
        'contactMode': mode, 'sourceEvidence': source,
        'patchBinding': None, 'surfaceEstimate': None, 'geometryProvenance': None,
    }
    binding = {'primitiveId': 'wearSphere:left_shoulder',
               'points': [{'triangleIndex': 0, 'barycentric': [1., 0., 0.]}]}
    # The first native shoulder-cap vertex lies on the selected source surface.
    from exercise_motion_pkg.body_surface_geometry import body_surface_primitive_meshes, evaluate_contact_patch
    meshes = body_surface_primitive_meshes(points[:1], names)
    source_point = evaluate_contact_patch(meshes, binding)[0, 0]
    record = {**deepcopy(reviewed),
              'patchBinding': binding if bound else None,
              'surfaceEstimate': {'normal': [0., 1., 0.], 'offsetMeters': float(source_point[1])} if bound else None,
              'geometryProvenance': {'kind': 'calibrated'} if bound else None}
    samples = [{key: row[key] for key in (
        'sampleId', 'sourceTimeSec', 'sourcePoseFrameIndex', 'sourceFrameIndex',
        'sourceFps', 'surfaceId')} | {'imageSha256': 'd' * 64}
        for row in observations]
    request = {
        'policyVersion': 'fixture', 'reviewIdentity': {'model': 'fixture'},
        'contactId': reviewed['contactId'], 'bodyRegion': reviewed['bodyRegion'],
        'contactMode': mode, 'surfaceId': 'bench-top',
        'sourceVideoSha256': video_sha, 'sourcePosePayloadSha256': pose_sha,
        'sourceFrameClockReceiptSha256': clock_sha, 'samples': samples,
    }
    receipt = {
        'schemaVersion': 1, 'requestBinding': request,
        'requestSha256': hashlib.sha256(json.dumps(
            request, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        ).encode()).hexdigest(),
        'reviewIdentity': {'model': 'fixture'}, 'promptPolicyVersion': 'fixture',
        'rawResponses': {row['sampleId']: json.dumps({'choice': 'direct_contact'})
                         for row in observations},
    }
    receipt_path = tmp_path / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
    receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    source_evidence = {
        'bodySupport': {'bodySurfaceContacts': [record]},
        'bodySurfaceContactEvidence': {
            'status': 'observed', 'sourceVideoSha256': video_sha,
            'reviews': [{
                'contactId': reviewed['contactId'], 'status': 'observed',
                'requirement': {'disposition': 'required', 'region': 'shoulder',
                                'side': 'left', 'surface': 'bench-top',
                                'contactMode': mode},
                'record': deepcopy(reviewed), 'receiptPath': str(receipt_path),
                'receiptSha256': receipt_sha,
                'coverage': {'allCanonicalPoseFramesObserved': True,
                             'canonicalPoseFrameCount': len(points)},
            }],
        },
    }
    payload = {
        'jointNames': names,
        'frames': [{'sourceTimeSec': float(i), 'joints': dict(zip(names, row.tolist()))}
                   for i, row in enumerate(points)],
        'sourceFootSupportEvidence': source_evidence,
        'sourcePoseCameraReference': {
            'sourcePose': {'sourceVideoSha256': video_sha},
            'sourceTimelineMapping': {
                'selectedSegmentSha256': video_sha,
                'sourcePosePayloadSha256': pose_sha,
                'selectedFrameClockReceiptSha256': clock_sha,
            },
            'camera': {'bilateralAssignment': 'identity'},
        },
    }
    return payload, points, names


def test_bound_stationary_patch_uses_native_mesh_and_sliding_leaves_tangent_free(tmp_path):
    payload, points, names = _payload(tmp_path, 'stationary')
    evidence = support_evidence(payload)
    assert len(evidence['bodySurfaceContacts']) == 1
    assert evidence['status'] == 'confirmed'
    assert evidence_is_complete(evidence, names)
    stationary = geometry_errors(points, names, evidence)
    rig = SimpleNamespace(names=names, width=6,
                          dependencies=np.ones((len(names) * 3, 6)))
    stationary_dependencies = geometry_dependencies(rig, evidence)
    assert stationary.shape == (len(points), stationary_dependencies.shape[0])
    assert np.linalg.norm(stationary[1, 1:]) > .1
    assert stationary_dependencies.shape[1] == rig.width
    report = validate_support_geometry(payload, points, names)
    assert not report['passed']
    assert 'body_surface_contact_geometry_mismatch' in report['rejectionReasons']
    selected = {**evidence, '_fitFrameStateIndices': [1]}
    selected_residual = geometry_errors(points[1:2], names, selected)
    assert selected_residual.shape == (1, stationary_dependencies.shape[0])
    np.testing.assert_allclose(selected_residual, 0., atol=1e-12)

    sliding_payload, sliding_points, sliding_names = _payload(tmp_path / 'slide', 'sliding')
    sliding_evidence = support_evidence(sliding_payload)
    sliding = geometry_errors(sliding_points, sliding_names, sliding_evidence)
    sliding_rig = SimpleNamespace(names=sliding_names, width=6,
                                  dependencies=np.ones((len(sliding_names) * 3, 6)))
    sliding_dependencies = geometry_dependencies(sliding_rig, sliding_evidence)
    assert sliding.shape == (len(sliding_points), sliding_dependencies.shape[0])
    assert sliding_dependencies.shape[1] == sliding_rig.width
    np.testing.assert_allclose(sliding, 0., atol=1e-12)


def test_body_surface_mesh_binding_forwards_valid_native_foot_geometry(tmp_path, monkeypatch):
    from exercise_motion_pkg import body_surface_geometry, native_foot_geometry

    payload, points, names = _payload(tmp_path)
    native = json.loads((Path(__file__).parent / 'fixtures' /
                         'native_foot_geometry_v1.json').read_text(encoding='utf-8'))['reference']
    payload['nativeFootGeometry'] = native
    evidence = support_evidence(payload)
    expected = native_foot_geometry.validated_native_foot_geometry(native)
    assert evidence['nativeFootGeometry'] == expected

    original = body_surface_geometry.body_surface_primitive_meshes
    seen = {}

    def capture_binding(*args, **kwargs):
        seen.update(kwargs.get('binding') or {})
        return original(*args, **kwargs)

    monkeypatch.setattr(body_surface_geometry, 'body_surface_primitive_meshes', capture_binding)
    from exercise_motion_pkg.support_geometry import _body_surface_contact_residuals
    _body_surface_contact_residuals(points, names, evidence)
    assert seen['nativeFootGeometry'] == expected

    payload['nativeFootGeometry'] = {'version': 999}
    invalid = support_evidence(payload)
    assert 'native_foot_geometry_invalid' in invalid['_bodySurfaceContactErrors']
    invalid_report = validate_support_geometry(payload, points, names)
    assert not invalid_report['passed']
    assert 'body_surface_contact_evidence_unresolved' in invalid_report['rejectionReasons']


def test_unbound_or_rolling_surface_record_fails_closed(tmp_path, monkeypatch):
    payload, points, names = _payload(tmp_path, 'stationary', bound=False)
    report = validate_support_geometry(payload, points, names)
    assert not report['passed']
    assert 'body_surface_contact_evidence_unresolved' in report['rejectionReasons']

    missing_payload, missing_points, missing_names = _payload(tmp_path / 'missing')
    missing_payload['sourceFootSupportEvidence']['bodySupport'].pop('bodySurfaceContacts')
    missing_evidence = support_evidence(missing_payload)
    assert missing_evidence['required'] is True
    assert missing_evidence['status'] == 'confirmed'
    assert missing_evidence['_bodySurfaceGeometryPending'] is True
    assert not support_contact_readiness(missing_payload)['passed']
    from exercise_motion_pkg import body_surface_evidence
    monkeypatch.setattr(body_surface_evidence, 'verify_body_surface_contact_evidence',
                        lambda *args, **kwargs: {
                            'coverage': {'allCanonicalPoseFramesObserved': True,
                                         'canonicalPoseFrameCount': 2},
                            'samples': [{}, {}],
                        })
    deferred = support_contact_readiness(
        missing_payload, require_geometry=False,
        source_pose={'sourceVideoSha256': 'a' * 64},
        source_video_path=tmp_path / 'source.mp4')
    assert deferred['passed']
    missing_report = validate_support_geometry(missing_payload, missing_points, missing_names)
    assert not missing_report['passed']
    assert any('required_contact_binding_missing' in error
               for error in missing_report['evidenceErrors'])

    rolling_payload, rolling_points, rolling_names = _payload(tmp_path / 'rolling', 'rolling')
    rolling_report = validate_support_geometry(rolling_payload, rolling_points, rolling_names)
    assert rolling_report['passed']
    rolling_evidence = support_evidence(rolling_payload)
    rolling_residual = geometry_errors(rolling_points, rolling_names, rolling_evidence)
    assert rolling_residual.shape == (2, 1)
    np.testing.assert_allclose(rolling_residual, 0., atol=1e-12)
    lifted = rolling_points.copy()
    lifted[1, rolling_names.index('left_shoulder'), 1] += .01
    lifted_report = validate_support_geometry(rolling_payload, lifted, rolling_names)
    assert not lifted_report['passed']
    assert 'body_surface_contact_geometry_mismatch' in lifted_report['rejectionReasons']

    # A finite surface polygon is part of the calibrated geometry. Plane
    # proximity cannot pass when the bound body patch lies beyond its edge.
    polygon_payload, polygon_points, polygon_names = _payload(tmp_path / 'polygon')
    polygon_record = polygon_payload['sourceFootSupportEvidence']['bodySupport'][
        'bodySurfaceContacts'][0]
    from exercise_motion_pkg.body_surface_geometry import body_surface_primitive_meshes, evaluate_contact_patch
    mesh = body_surface_primitive_meshes(polygon_points[:1], polygon_names)
    center = evaluate_contact_patch(mesh, polygon_record['patchBinding'])[0, 0]
    polygon_record['surfaceEstimate']['polygonWorld'] = [
        [center[0] - .02, center[1], center[2] - .02],
        [center[0] + .02, center[1], center[2] - .02],
        [center[0] + .02, center[1], center[2] + .02],
        [center[0] - .02, center[1], center[2] + .02],
    ]
    polygon_evidence = support_evidence(polygon_payload)
    polygon_residual = geometry_errors(polygon_points, polygon_names, polygon_evidence)
    polygon_rig = SimpleNamespace(names=polygon_names, width=6,
                                  dependencies=np.ones((len(polygon_names) * 3, 6)))
    polygon_dependencies = geometry_dependencies(polygon_rig, polygon_evidence)
    assert polygon_residual.shape == (len(polygon_points), polygon_dependencies.shape[0])
    assert polygon_dependencies.shape[1] == polygon_rig.width
    assert polygon_residual[0, 3] == 0.
    assert polygon_residual[1, 3] > 0.

    rolling_polygon, rolling_polygon_points, rolling_polygon_names = _payload(
        tmp_path / 'rolling-polygon', 'rolling')
    rolling_polygon_record = rolling_polygon['sourceFootSupportEvidence']['bodySupport'][
        'bodySurfaceContacts'][0]
    rolling_polygon_record['surfaceEstimate']['polygonWorld'] = polygon_record[
        'surfaceEstimate']['polygonWorld']
    finite_rolling_report = validate_support_geometry(
        rolling_polygon, rolling_polygon_points, rolling_polygon_names)
    assert not finite_rolling_report['passed']
    assert any('finite_polygon_rolling_unsupported' in error
               for error in finite_rolling_report['evidenceErrors'])

    mismatched_payload, mismatched_points, mismatched_names = _payload(tmp_path / 'mismatch')
    mismatched_payload['sourcePoseCameraReference']['sourceTimelineMapping'][
        'selectedFrameClockReceiptSha256'] = 'e' * 64
    mismatch_report = validate_support_geometry(
        mismatched_payload, mismatched_points, mismatched_names)
    assert not mismatch_report['passed']
    assert 'body_surface_contact_source_video_mapping_mismatch' not in mismatch_report['evidenceErrors']
    assert any('source_mapping_mismatch' in error for error in mismatch_report['evidenceErrors'])

    altered_payload, altered_points, altered_names = _payload(tmp_path / 'altered')
    altered_payload['sourceFootSupportEvidence']['bodySupport'][
        'bodySurfaceContacts'][0]['sourceEvidence']['observations'][0]['contactState'] = 'no_contact'
    altered_report = validate_support_geometry(altered_payload, altered_points, altered_names)
    assert not altered_report['passed']
    assert any('does_not_match_review' in error for error in altered_report['evidenceErrors'])
