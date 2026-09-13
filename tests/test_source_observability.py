from exercise_motion_pkg.source_observability import reconstruction_observability
from exercise_motion_pkg.youtube import YouTubeCandidate, YouTubeRankingSettings, reviewed_candidate_sort_key


def test_required_region_evidence_allows_side_view_but_rejects_cropped_predictions():
    from exercise_motion_pkg.source_observability import required_region_observation_metrics
    from exercise_motion_pkg.bake_and_rank import exact_source_validation_effectively_passed

    contract = {'mustBeVisibleRegions': ['feet']}
    source = {'coordinateSpace': 'normalized_image_xy', 'frames': [
        {'joints': {'left_ankle': [.4, 1.1], 'right_ankle': [.6, 1.1]},
         'jointConfidence': {'left_ankle': .99, 'right_ankle': .99}}]}
    result = required_region_observation_metrics(source, contract)
    assert result['missingRegions'] == ['feet']
    assert not exact_source_validation_effectively_passed({
        'passed': True, 'poseFailureOverriddenByVlm': True, 'requiredRegionObservations': result})
    source['frames'][0]['joints']['left_ankle'] = [.4, .9]
    assert required_region_observation_metrics(source, contract)['passed']
    source['frames'][0]['jointConfidence']['left_ankle'] = .1
    assert not required_region_observation_metrics(source, contract)['passed']
    assert required_region_observation_metrics({'frames': [
        {'joints': {'left_ear': [.5, .2]}}]}, {'mustBeVisibleRegions': ['head']})['passed']


def observations(missing=()):
    return [{'joints': {name: [0., .5] for name in ('left_wrist', 'right_wrist')
                        if not (name == 'right_wrist' and index in missing)}} for index in range(36)]


def test_temporary_occlusion_ranks_above_persistent_missing_evidence_without_rejection():
    contract = {'mustBeVisibleRegions': ['hands']}
    complete = reconstruction_observability(observations(), contract)
    brief = reconstruction_observability(observations(range(15, 18)), contract)
    persistent = reconstruction_observability(observations(range(5, 36)), contract)
    assert complete['score'] > brief['score'] > persistent['score']
    assert brief['advisoryOnly'] and persistent['advisoryOnly']
    assert not brief['persistentMissingJoints']
    assert persistent['persistentMissingJoints'] == ['right_wrist']


def test_explicit_unilateral_motion_does_not_require_hidden_inactive_arm():
    result = reconstruction_observability(observations(range(36)), {
        'mustBeVisibleRegions': ['hands'], 'activeSide': 'left'})
    assert result['score'] == 1.
    inferred_side = reconstruction_observability(observations(range(36)), {
        'mustBeVisibleRegions': ['hands'], 'handRelationship': 'single'})
    assert inferred_side['score'] == 1.


def test_source_evidence_changes_ranking_without_changing_acceptance_score():
    def candidate(score):
        return YouTubeCandidate(url='url', video_id='video', title='exercise', channel=None,
            duration_seconds=10, view_count=None, upload_date=None, description_snippet=None,
            thumbnail=None, vision_score=.9, final_score=.9, vision_payload={
                'posePrefilter': {'passed': True, 'score': .9,
                    'reconstructionObservability': {'available': True, 'score': score}}})
    good, poor = candidate(1.), candidate(.3)
    settings = YouTubeRankingSettings(rank_with_vision=True)
    assert reviewed_candidate_sort_key(good, settings) > reviewed_candidate_sort_key(poor, settings)
    assert good.final_score == poor.final_score == .9


def test_reconstruction_queue_preserves_observability_ranking():
    from dataclasses import replace
    from test_exercise_motion_pkg import _first_attempt_readiness_candidate
    from exercise_motion_pkg.bake_and_rank import (
        first_attempt_readiness_assessment,
        prioritize_ranked_candidates_for_reconstruction,
    )

    def candidate(video_id, score):
        result = _first_attempt_readiness_candidate(completion_mode='return_to_start')
        result.candidate['videoId'] = video_id
        result.candidate['visionPayload']['posePrefilter']['reconstructionObservability'] = {
            'available': True, 'score': score, 'advisoryOnly': True}
        return result

    poor, good = candidate('persistent-occlusion', .3), candidate('clear-evidence', 1.)
    assert first_attempt_readiness_assessment(poor)['eligible']
    ranked = prioritize_ranked_candidates_for_reconstruction([poor, good])
    assert [item.candidate['videoId'] for item in ranked] == ['clear-evidence', 'persistent-occlusion']
    renamed = [replace(item, exercise_name='Different movement name') for item in (poor, good)]
    assert [item.candidate['videoId'] for item in prioritize_ranked_candidates_for_reconstruction(renamed)] == [
        'clear-evidence', 'persistent-occlusion']


def test_view_diversity_does_not_promote_an_ineligible_source():
    from test_exercise_motion_pkg import _first_attempt_readiness_candidate
    from exercise_motion_pkg.bake_and_rank import (
        first_attempt_readiness_assessment, prioritize_orientation_diverse_fallback,
    )
    candidates = [_first_attempt_readiness_candidate(completion_mode='return_to_start') for _ in range(3)]
    for index, (candidate, view) in enumerate(zip(candidates, (0., .2, 1.))):
        candidate.candidate['videoId'] = str(index)
        candidate.candidate['visionPayload']['posePrefilter']['frontalOrBackViewEvidence'] = view
    invalid = candidates[-1].candidate['visionPayload']
    invalid['bestChunkScore'] = .1
    invalid['validChunkCount'] = 0
    invalid['validChunkRatio'] = 0.
    assert not first_attempt_readiness_assessment(candidates[-1])['eligible']
    assert [item.candidate['videoId'] for item in prioritize_orientation_diverse_fallback(candidates)] == ['0', '1', '2']


def test_missing_bilateral_chain_is_unknown_not_perfect():
    from exercise_motion_pkg.pose_prefilter import bilateral_active_chain_balance
    result = bilateral_active_chain_balance(motion_by_joint={'left_wrist': .5},
        visibility_by_joint={'left_wrist': 1.}, active_threshold=.1)
    assert result is None


def test_lying_source_angle_cannot_override_observed_motion():
    from test_exercise_motion_pkg import _first_attempt_readiness_candidate
    from exercise_motion_pkg.bake_and_rank import first_attempt_readiness_assessment
    candidate = _first_attempt_readiness_candidate(completion_mode='return_to_start')
    candidate.candidate['exerciseMotionContract']['startPoseConstraints'] = {'supportMode': 'lying'}
    candidate.candidate['visionPayload']['posePrefilter']['reconstructionViewQuality'] = .01
    assert first_attempt_readiness_assessment(candidate)['eligible']
