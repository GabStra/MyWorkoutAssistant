import json

from exercise_motion_pkg.source_outcomes import (
    load_source_outcome_index,
    source_outcome_prior,
    update_source_outcome_index,
)


def test_processing_errors_do_not_penalize_sources_or_hide_resolved_windows(tmp_path):
    path = tmp_path / 'outcomes.json'
    unresolved = [
        {'candidate': {'videoId': 'source', 'channel': 'coach'}, 'status': status}
        for status in ('failed', 'source_processing_failed', 'rejected_vlm_timeout',
                       'needs_motion_processing', 'needs_source_review', 'needs_definition_review', 'blocked_contract',
                       'needs_manual_review', 'skipped_previous_terminal_result')
    ]
    assert update_source_outcome_index(path, unresolved) is None
    assert not path.exists()
    rejected = {'candidate': {'videoId': 'source', 'channel': 'coach'},
                'status': 'source_rejected', 'sourceFailureReason': 'cropped_body'}
    update_source_outcome_index(path, unresolved + [rejected])
    index = load_source_outcome_index(path)
    for stats in (index['sources']['video:source'], index['channels']['coach']):
        assert stats['attempts'] == 1
        assert stats['rejectionCounts'] == {'cropped_body': 1, 'status:source_rejected': 1}
    assert source_outcome_prior(index, video_id='source', channel='coach')['score'] < 0.


def test_mixed_legacy_history_is_preserved_but_new_resolved_outcomes_own_prior(tmp_path):
    path = tmp_path / 'outcomes.json'
    mixed = {'attempts': 10, 'sourcePasses': 2, 'accepts': 0,
             'rejectionCounts': {'status:failed': 8, 'cropped_body': 2}}
    clean = {'attempts': 3, 'sourcePasses': 3, 'accepts': 3}
    index = {'schemaVersion': 1, 'sources': {'video:mixed': dict(mixed), 'video:clean': clean},
             'channels': {'coach': dict(mixed)}}
    path.write_text(json.dumps(index))
    assert source_outcome_prior(index, video_id='mixed', channel='coach')['score'] == 0.
    old_clean_prior = source_outcome_prior(index, video_id='clean')['score']
    assert old_clean_prior > 0.
    assert update_source_outcome_index(path, [{
        'candidate': {'videoId': 'mixed', 'channel': 'coach'},
        'status': 'ready_for_selection', 'finalSelectionStatus': 'review_incomplete',
    }]) is None
    update_source_outcome_index(path, [{
        'candidate': {'videoId': 'mixed', 'channel': 'coach'},
        'status': 'ready_for_selection', 'finalSelectionStatus': 'selected',
    }])
    revised = load_source_outcome_index(path)
    for stats in (revised['sources']['video:mixed'], revised['channels']['coach']):
        assert stats['attempts'] == 11
        assert stats['rejectionCounts'] == mixed['rejectionCounts']
        assert stats['qualityHistory'] == {'attempts': 1, 'sourcePasses': 1, 'accepts': 1}
    assert source_outcome_prior(revised, video_id='mixed', channel='coach')['score'] > 0.
    assert source_outcome_prior(revised, video_id='clean')['score'] == old_clean_prior


def test_retained_pre_render_support_failure_does_not_penalize_approved_source(tmp_path):
    path = tmp_path / 'outcomes.json'
    downstream_rejection = {
        'candidate': {'videoId': 'approved-source', 'channel': 'coach'},
        'status': 'rejected_baked_motion_validation',
        'failureStage': 'baked_motion_validation',
        'finalSelectionStatus': 'rejected_after_materialized_review',
        'reconstructionAttempted': True,
        'failures': [{
            'reason': 'baked_motion_validation_failed',
            'rejectionReasons': ['source_confirmed_support_unrepaired'],
        }],
        'finalOutputRejectionReasons': ['source_confirmed_support_unrepaired'],
    }

    assert update_source_outcome_index(path, [downstream_rejection]) is None
    assert not path.exists()

    source_rejection = {
        **downstream_rejection,
        'failureOwner': 'source',
        'finalOutputRejectionReasons': ['materialized_source_support_posture_mismatch'],
    }
    update_source_outcome_index(path, [source_rejection])
    index = load_source_outcome_index(path)
    assert index['sources']['video:approved-source']['attempts'] == 1
    assert index['sources']['video:approved-source']['rejectionCounts'] == {
        'baked_motion_validation': 1,
        'materialized_source_support_posture_mismatch': 1,
        'status:rejected_baked_motion_validation': 1,
    }


def test_old_baked_motion_penalties_are_neutralized_without_losing_raw_history(tmp_path):
    path = tmp_path / 'outcomes.json'
    contaminated = {
        'attempts': 10, 'sourcePasses': 10, 'accepts': 0,
        'qualityHistory': {'attempts': 10, 'sourcePasses': 10, 'accepts': 0},
        'rejectionCounts': {'status:rejected_baked_motion_validation': 10},
    }
    index = {'sources': {'video:source': dict(contaminated)},
             'channels': {'coach': dict(contaminated)}}
    path.write_text(json.dumps(index))
    assert source_outcome_prior(index, video_id='source', channel='coach')['score'] == 0.

    for _ in range(2):
        update_source_outcome_index(path, [{
            'candidate': {'videoId': 'source', 'channel': 'coach'},
            'status': 'ready_for_selection', 'finalSelectionStatus': 'selected',
        }])
    revised = load_source_outcome_index(path)
    for stats in (revised['sources']['video:source'], revised['channels']['coach']):
        assert stats['attempts'] == 12
        assert stats['rejectionCounts'] == contaminated['rejectionCounts']
        assert stats['qualityHistory'] == {'attempts': 2, 'sourcePasses': 2, 'accepts': 2}
    assert source_outcome_prior(revised, video_id='source', channel='coach')['score'] > 0.
