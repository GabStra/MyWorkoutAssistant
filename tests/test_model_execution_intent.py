import json

import pytest

from exercise_motion_pkg import bake_and_rank as bake


@pytest.mark.parametrize('untrusted', [
    {},
    {'bilateralExecutionAuthority': 'structured_definition'},
    {'bilateralExecution': {'legs': 'mirrored'}},
    {'modelExecution': {'legs': 'mirrored'}, 'modelExecutionAuthority': 'llm'},
    {'actionDefinitionAuthority': 'unresolved'},
])
def test_missing_structured_model_intent_cannot_silently_skip_fit_checks(untrusted):
    payload = {'frames': []}
    result, report = bake.constrain_baked_payload_to_source_articulation(
        payload, exercise_motion_contract={
            'actionDefinitionAuthority': 'structured_definition', **untrusted})
    assert result is not payload
    assert payload == {'frames': []}
    assert report == {'applied': False, 'reason': 'model_execution_intent_unresolved'}
    assert result['controlledMotionFit'] == report
    from exercise_motion_pkg.rig_playback import canonical_execution_policy_evidence
    assert canonical_execution_policy_evidence(result) == {
        'required': True, 'passed': False, 'reason': 'model_execution_intent_unresolved'}


def test_explicit_unconstrained_definition_is_distinct_from_missing_intent():
    contract = {'actionDefinitionAuthority': 'structured_definition',
                'bilateralExecutionAuthority': 'structured_definition',
                'bilateralExecution': {}}
    _, report = bake.constrain_baked_payload_to_source_articulation(
        {'frames': []}, exercise_motion_contract=contract)
    assert report['reason'] == 'frames_unavailable'
    assert bake.controlled_motion_execution_policy({}, contract) == {}


def test_diagnostic_without_contract_preserves_existing_model_target():
    payload = {'frames': [], 'canonicalExecution': {'legs': 'mirrored'}}
    result, _ = bake.constrain_baked_payload_to_source_articulation(payload)
    assert result['canonicalExecution'] == {'legs': 'mirrored'}


def test_invalid_reviewed_intent_is_a_hard_rejection_not_a_fit_exception():
    result, report = bake.constrain_baked_payload_to_source_articulation(
        {'frames': []}, exercise_motion_contract={
            'bilateralExecutionAuthority': 'structured_definition',
            'bilateralExecution': {'legs': 'unknown'}})
    from exercise_motion_pkg.rig_playback import canonical_execution_policy_evidence
    assert report['reason'] == 'model_execution_intent_invalid'
    assert canonical_execution_policy_evidence(result)['passed'] is False


def test_contract_cache_rejects_missing_intent_but_keeps_explicit_opt_out(tmp_path):
    from exercise_motion_pkg import youtube
    target = youtube.ExerciseEntry(exercise_id='target', name='Target', slug='target', motion_context={
        'exerciseDefinition': {'definingAction': 'Flex and return.',
                               'completionMode': 'return_to_start', 'bilateralExecution': {}}})
    contract = youtube.normalize_definition_exercise_motion_contract_response({
        'movementType': 'repetition', 'completionMode': 'return_to_start',
        'bodySupportRequirements': {}, 'primaryMovingRegions': ['torso'],
        'referenceRegions': ['hips'], 'primaryAxis': 'vertical',
        'motionPattern': 'joint_flex_extend'}, exercise=target, source='llm')
    settings = youtube.YouTubeRankingSettings(exercise_motion_contract_cache_dir=tmp_path / 'cache')
    assert youtube.cache_exercise_motion_contract(target, settings, contract) is not None
    missing = dict(contract)
    missing.pop('bilateralExecution')
    missing.pop('bilateralExecutionAuthority')
    assert youtube.exercise_motion_contract_is_usable(missing, exercise=target) is False
    assert youtube.cache_exercise_motion_contract(target, settings, missing) is None
    for intent in ({'legs': 'unknown'}, {'modelExecution': {'legs': 'mirrored'}}):
        invalid = {**contract, 'bilateralExecution': intent}
        assert youtube.exercise_motion_contract_is_usable(invalid, exercise=target) is False
        assert youtube.cache_exercise_motion_contract(target, settings, invalid) is None


@pytest.mark.parametrize('intent', [None, {}, {'legs': 'mirrored'}])
def test_missing_model_intent_is_reported_before_expensive_generation(tmp_path, intent):
    from exercise_motion_pkg.definition_ingestion import prepare_workout_plan_definition_readiness

    definition = {'definingAction': 'Flex and return.', 'completionMode': 'return_to_start'}
    if intent is not None:
        definition['bilateralExecution'] = intent
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'exerciseDefinitions': [
        {'id': 'target', 'name': 'Target', 'motionContext': {'exerciseDefinition': definition}}
    ]}), encoding='utf-8')
    original = plan.read_bytes()
    _, _, report = prepare_workout_plan_definition_readiness(plan_path=plan)
    assert report['readyCount'] == (0 if intent is None else 1)
    if intent is None:
        assert report['unresolvedReviewQueue'][0]['reason'] == 'model_execution_intent_unresolved'
    assert plan.read_bytes() == original


def test_exact_reviewed_registry_can_resolve_legacy_inline_intent(tmp_path):
    from exercise_motion_pkg.definition_ingestion import prepare_workout_plan_definition_readiness
    from exercise_motion_pkg.definition_review import approve_definition_review, export_definition_review

    support = {'required': [{'region': 'upper_back', 'side': 'center', 'surface': 'bench'}],
               'prohibited': []}
    definition = {'definingAction': 'Flex and return.', 'completionMode': 'return_to_start',
                  'bodySupportRequirements': support}
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'exerciseDefinitions': [
        {'id': 'target', 'name': 'Target', 'motionContext': {'exerciseDefinition': definition}}
    ]}), encoding='utf-8')
    original = plan.read_bytes()
    review_path = tmp_path / 'review.json'
    review = export_definition_review(plan_path=plan, exercise_id='target', review_path=review_path)
    assert review['definition']['bodySupportRequirements'] == support
    review['definition'] = {**definition, 'bilateralExecution': {}}
    review_path.write_text(json.dumps(review), encoding='utf-8')
    registry = tmp_path / 'approved.json'
    approve_definition_review(plan_path=plan, exercise_id='target', review_path=review_path,
                              output_path=registry)
    _, entries, report = prepare_workout_plan_definition_readiness(
        plan_path=plan, approved_registry_path=registry)
    assert report['readyCount'] == 1
    assert entries[0].motion_context['exerciseDefinition']['bilateralExecution'] == {}
    assert entries[0].motion_context['exerciseDefinition']['bodySupportRequirements'] == support
    assert plan.read_bytes() == original
    review_path.write_text('{}', encoding='utf-8')
    _, _, invalid = prepare_workout_plan_definition_readiness(plan_path=plan,
                                                            approved_registry_path=registry)
    assert invalid['readyCount'] == 0  # The exact review receipt still owns this amendment.
