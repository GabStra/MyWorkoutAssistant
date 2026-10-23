import hashlib
import json
from types import SimpleNamespace

import pytest

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.source_evidence import evidence_inventory, temporal_observation_bins


def _parent(tmp_path):
    sheet = tmp_path / 'sheet.jpg'
    sheet.write_bytes(b'reviewed source sheet')
    (tmp_path / 'contact_sheet_evidence.json').write_text(json.dumps({'sheets': {
        sheet.name: {'sha256': hashlib.sha256(sheet.read_bytes()).hexdigest(),
                     'frames': [{'number': i + 1, 'timestampSeconds': i / 5} for i in range(8)]},
    }}))
    timing = temporal_observation_bins(
        [{'phaseId': 'p1', 'visible': True, 'evidenceFrameIds': ['A:3', 'A:4']},
         {'phaseId': 'p2', 'visible': True, 'evidenceFrameIds': ['A:5', 'A:6']}],
        ['p1', 'p2'], evidence_inventory({'A': [sheet]}), id_field='phaseId',
        source_time_offset_seconds=10., require_visible=True,
    )
    timing.update(candidateId='A', candidateWindowSourceSeconds={'start': 10., 'end': 11.4})
    scorecard = {'id': 'A', 'passed': True, 'requiredEquipment': 'none',
                 'movementTopologyEvidence': {'phaseTimingEvidence': timing}}
    ranking = bake.LoopRanking(score=.95, reasons=[], payload={
        'selectedCandidateId': 'A', 'selectedScorecard': scorecard,
        'sourceCutScorecardCandidates': [scorecard],
        'sourceCutCandidates': [{'candidateId': 'A', 'startSeconds': 0., 'endSeconds': 1.4,
                                 'framePaths': [str(sheet)]}],
    })
    child = {'candidateId': 'A-CYCLE-1', 'startSeconds': .2, 'endSeconds': 1.3,
             'exactCycleRefinementParentId': 'A'}
    return ranking, child, sheet


@pytest.mark.parametrize('lineage', ['exactCycleRefinementParentId', 'exactContractTrimParentId',
                                   'exactBoundaryExpansionParentId'])
def test_source_child_preserves_explicit_parent_bins_on_absolute_source_clock(tmp_path, lineage):
    ranking, child, _ = _parent(tmp_path)
    child[lineage] = child.pop('exactCycleRefinementParentId')
    assert bake.source_cut_child_timing_coverage(ranking, child)['eligible']
    clipped = {**child, 'startSeconds': .55}
    assert not bake.source_cut_child_timing_coverage(ranking, clipped)['eligible']
    unrelated = {**child, lineage: 'OTHER'}
    assert not bake.source_cut_child_timing_coverage(ranking, unrelated)['eligible']
    assert not bake.source_cut_child_timing_coverage(ranking, {**child, 'endSeconds': 2.})['eligible']


def test_changed_parent_sheet_and_legacy_timing_cannot_authorize_child(tmp_path):
    ranking, child, sheet = _parent(tmp_path)
    sheet.write_bytes(b'changed sheet')
    assert not bake.source_cut_child_timing_coverage(ranking, child)['eligible']
    ranking.payload['sourceCutScorecardCandidates'][0]['movementTopologyEvidence'] = {}
    assert not bake.source_cut_child_timing_coverage(ranking, child)['eligible']


def test_source_child_timing_is_checked_before_materialization_or_gpu_work(tmp_path, monkeypatch):
    ranking, child, sheet = _parent(tmp_path)
    child['startSeconds'] = .55
    monkeypatch.setattr(bake, 'source_cut_deterministic_confirmation_candidates', lambda _ranking: [child])
    monkeypatch.setattr(bake, 'read_basic_video_metadata', lambda _path: SimpleNamespace(duration_seconds=2.))

    def unexpected_work(**_kwargs):
        pytest.fail('unresolved child must not be materialized or sent to a model')

    monkeypatch.setattr(bake, 'materialize_source_cut_candidate_for_exact_validation', unexpected_work)
    result, _ = bake.select_exact_pose_confirmed_source_cut(
        ranking, detection_source_video_path=sheet, exercise_name='fixture',
        exercise_motion_contract={}, caption_images=unexpected_work, output_dir=tmp_path,
    )
    assert result.score == 0.
    assert 'source_cut_review_required' in result.reasons
    assert result.payload['sourceCutDeterministicConfirmationAttempts'] == []
    assert result.payload['sourceCutChildTimingCoverageSkips'][0]['parentCandidateId'] == 'A'


def test_single_sheet_overview_has_the_same_frame_provenance_as_paginated_sheets(tmp_path):
    import cv2
    import numpy as np
    from exercise_motion_pkg.segment_detection import build_frame_contact_sheet, build_frame_contact_sheets
    frames = []
    for index in range(3):
        path = tmp_path / f'frame{index}.jpg'
        assert cv2.imwrite(str(path), np.full((32, 32, 3), index * 60, dtype=np.uint8))
        frames.append(path)
    times = [0., .2, .4]
    sheets = build_frame_contact_sheets(
        frame_paths=frames, timestamps=times, output_dir=tmp_path, columns=2,
        tile_width=160, frames_per_sheet=2, jpeg_quality=85, sequence_labels=True,
    )
    overview = build_frame_contact_sheet(
        frame_paths=frames, timestamps=times, output_path=tmp_path / 'overview.jpg',
        columns=3, tile_width=160, jpeg_quality=85, sequence_labels=True,
    )
    assert overview is not None
    inventory = evidence_inventory({'overview': [overview], 'pages': sheets})
    assert [item['timestampSeconds'] for item in inventory if item['sampling'] == 'overview'] == times
    assert len(inventory) == 6
