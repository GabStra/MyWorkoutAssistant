from exercise_motion_pkg import youtube as y


def test_semantic_review_receives_requested_phases_without_mutating_exercise():
    exercise = y.ExerciseEntry(exercise_id='movement', name='Compound Movement', slug='movement',
                               motion_context={'equipment': 'barbell'})
    candidate = y.YouTubeCandidate(url='https://example.test/demo', video_id='demo',
        title='Compound Movement Technique', channel=None, duration_seconds=20,
        view_count=None, upload_date=None, description_snippet=None, thumbnail=None)
    contract = {'requiredPhases': ['lift', 'catch in a squat', 'stand', 'press'],
                'validStartState': 'implement on floor', 'validEndState': 'overhead'}
    captured = []

    def semantic_gate(target, item, settings):
        captured.append(y.build_candidate_semantic_gate_prompt(target, item))
        assert target.motion_context['requestedMovement']['requiredPhases'] == contract['requiredPhases']
        return 1., [], {'wrongExercise': False, 'wrongEquipment': False,
                        'matchedExercise': target.name, 'unrequestedVariantTerms': []}

    result = y.run_youtube_candidate_review_pass(exercise=exercise, ranked=[candidate],
        settings=y.YouTubeRankingSettings(semantic_gate_enabled=True, pose_prefilter_enabled=False,
                                          rank_with_vision=False), debug_candidates_by_key={},
        semantic_gate=semantic_gate, pose_ranker=None, vision_ranker=None,
        exercise_motion_contract=contract)
    assert captured and 'catch in a squat' in captured[0]
    assert result.ranked[0].vision_payload['semanticGate']['passed']
    assert exercise.motion_context == {'equipment': 'barbell'}
