import copy

import pytest
from jsonschema import Draft7Validator

from workout_generator_pkg import session_drafting as drafting
from workout_generator_pkg.planning_tools import library_fingerprint, requirement_sources, source_message_context
from test_workout_generator_context_decisions import programming_choice_case
from test_workout_generator_planning_decisions import store
from test_workout_generator_weekly_shortlist import shortlist_case


def test_optional_menu_has_same_choice_domain_and_independent_preparation(monkeypatch):
    equipment, messages, arguments = shortlist_case()
    alternative = copy.deepcopy(equipment['exerciseDefinitions'][0])
    alternative['id'] += '-alternative'
    equipment['exerciseDefinitions'].append(alternative)
    tool = drafting.prepare_workout_sessions_tool(messages, equipment,
        selection_options={'admissibleDefinitionIds': ['LIBRARY_0', 'LIBRARY_1']})
    validator = Draft7Validator(tool['function']['parameters'])
    choices = {'selectionMode': 'selected_menu', 'definition_ids': ['LIBRARY_0'],
        'alternative_definition_ids': ['LIBRARY_1']}
    validator.validate(choices)
    assert not validator.is_valid({**choices, 'alternative_definition_ids': ['invented']})
    assert not validator.is_valid({**choices, 'alternative_definition_ids': ['LIBRARY_1', 'LIBRARY_1']})
    assert not validator.is_valid({**choices, 'alternative_definition_ids': [['LIBRARY_1']]})
    seen = []
    def prepare(arguments, *args, **kwargs):
        seen.append(copy.deepcopy(arguments))
        return {**arguments, 'preparationId': str(len(seen))}
    monkeypatch.setattr(drafting, '_prepare_week', prepare)
    prepared = drafting.prepare_workout_sessions(choices, messages, equipment)
    assert len(seen) == 2
    assert seen[0]['semanticSelection']['definitionIds'] != seen[1]['semanticSelection']['definitionIds']
    assert prepared['semanticSelection'] == seen[0]['semanticSelection']
    assert prepared['alternativePreparation']['semanticSelection'] == seen[1]['semanticSelection']
    assert prepared['preparationArguments']['alternative_definition_ids'] == ['LIBRARY_1']
    with pytest.raises(drafting.PlanningInputError, match='alternative must change'):
        drafting.prepare_workout_sessions({**choices, 'alternative_definition_ids': ['LIBRARY_0']}, messages, equipment)


@pytest.mark.parametrize('selection', ['baseline', 'candidate'])
def test_public_drafting_reuses_branch_work_then_selects_exact_membership(monkeypatch, selection):
    from workout_generator_pkg import allocation, joint_planning
    equipment, record, candidate, comparison, messages, _ = programming_choice_case()
    other = copy.deepcopy(equipment['exerciseDefinitions'][0])
    other['id'] += '-other'
    equipment['exerciseDefinitions'].append(other)
    fingerprint = library_fingerprint(equipment)
    source_messages = source_message_context(requirement_sources(messages))
    identity = {'preparationId': 'menus', 'requirementsId': record['requirementsId'],
        'baseDraftId': None, 'libraryFingerprint': fingerprint, 'historyFingerprint': None,
        'draftingVersion': drafting.DRAFTING_VERSION, 'sourceMessages': source_messages,
        'candidates': {}, 'sessions': [], 'recipeSessions': [], 'definition_ids': [],
        'setAllocation': {'feasible': True}, 'sourceWorkingSetBudget': {'source': 'unbounded_by_user',
            'variableWeeklyWorkingSets': None}}
    primary = {**identity, 'semanticSelection': {'mode': 'selected_menu',
        'definitionIds': [equipment['exerciseDefinitions'][0]['id']]}}
    alternate = {**identity, 'preparationId': 'alternate', 'semanticSelection': {'mode': 'selected_menu',
        'definitionIds': [other['id']]}}
    prepared = {**primary, 'alternativePreparation': alternate}
    store(messages, 'prepare_workout_sessions', {}, prepared, 'menus')
    store(messages, 'draft_workout_sessions', {}, {'preparationId': 'prior-menu',
        'prescriptionResults': {'retained-recipe-hash': {'reps': 10}},
        'menuResults': {'baseline': {'submittedDraft': candidate['submittedDraft'],
            'jointPlanning': {'feasible': True}}}}, 'prior-work')
    monkeypatch.setattr(drafting, 'require_approved_requirements', lambda *args: None)
    monkeypatch.setattr(drafting, 'latest_draft_submission', lambda *args: (None, None))
    calls = []
    fail_alternate = [True]
    def run(client, arguments, messages, equipment, state, **kwargs):
        menu = kwargs['prepared_override']
        name = 'baseline' if menu['preparationId'] == 'menus' else 'candidate'
        calls.append(name)
        assert kwargs['compare_counts'] is False
        if name == 'baseline':
            assert kwargs['previous_override']['prescriptionResults']['retained-recipe-hash'] == {'reps': 10}
        if name == 'candidate':
            assert kwargs['previous_override']['prescriptionResults']['same-recipe-hash'] == {'reps': 8}
            assert kwargs['previous_override']['recipeQualification']['contracts'] == []
            if fail_alternate[0]:
                return {**identity, 'passed': False, 'errors': [{'code': 'temporary_failure'}]}
        draft = copy.deepcopy(candidate['submittedDraft'])
        draft['workouts'][0]['name'] = name
        draft['workouts'][0]['exercises'][0]['definition_id'] = 'LIBRARY_0' if name == 'baseline' else 'LIBRARY_1'
        return {**identity, 'proposedSubmission': draft, 'jointPlanning': {'feasible': True, 'proofOwner': name},
            'prescriptionResults': {'same-recipe-hash': {'reps': 8}},
            'recipeQualification': {'contracts': [], 'inputHashes': {}}}
    def audit(result, menu, *args):
        return {**result, 'submittedDraft': result['proposedSubmission'], 'audit': {'issues': [], 'errors': []},
            'semanticSelection': {**menu['semanticSelection'], 'fixedWorkouts': []}}
    monkeypatch.setattr(drafting, '_draft_workout_sessions', run)
    monkeypatch.setattr(drafting, '_audit_fresh_menu', audit)
    monkeypatch.setattr(allocation, '_joint_candidate_comparison_context', lambda *args, **kwargs: {})
    monkeypatch.setattr(joint_planning, 'compare_audited_joint_candidates', lambda *args, **kwargs: copy.deepcopy(comparison))
    first = drafting.draft_workout_sessions(None, {'preparationId': 'menus'}, messages, equipment, {})
    assert calls == ['baseline', 'candidate']
    assert first['submittedDraft']['workouts'][0]['name'] == 'baseline'
    store(messages, 'draft_workout_sessions', {}, first, 'partial')
    assert drafting.accepted_fresh_programming_artifact(first, equipment, messages)['jointPlanning']['proofOwner'] == 'baseline'
    fail_alternate[0] = False
    pending = drafting.draft_workout_sessions(None, {'preparationId': 'menus'}, messages, equipment, {})
    assert calls == ['baseline', 'candidate', 'candidate']
    assert len(pending['programmingDecisionChoices']) == 2
    store(messages, 'draft_workout_sessions', {}, pending, 'comparison')
    assert drafting.selected_fresh_programming_artifact(messages, equipment) is None
    from workout_generator_pkg import interactive_shell
    from workout_generator_pkg.planner_context import request_planning_state
    snapshot = copy.deepcopy(pending['jointCandidateComparison']['programmingArtifacts'])
    state = request_planning_state(interactive_shell._messages_for_api(messages, True, provided_equipment=equipment))
    menus = state['programmingChoice']['menus']
    assert menus['baseline']['workouts'][0]['exercises'][0]['definition_id'] == 'LIBRARY_0'
    assert menus['candidate']['workouts'][0]['exercises'][0]['definition_id'] == 'LIBRARY_1'
    assert set(state['exerciseCandidates']) >= {'LIBRARY_0', 'LIBRARY_1'}
    assert 'parallelSubmission' not in state
    assert pending['jointCandidateComparison']['programmingArtifacts'] == snapshot
    store(messages, 'audit_workout_plan', {}, {**identity, 'semanticSelection': {
        **prepared['semanticSelection'], 'fixedWorkouts': []}}, 'older-baseline-audit')
    identifier, choice = next((key, value) for key, value in pending['programmingDecisionChoices'].items()
        if value['selection'] == selection)
    store(messages, 'record_planning_decisions', {}, {'passed': True, 'decisionReview': {'passed': True},
        'decisions': {'DECISION_0': {'topic': 'Menu choice', 'choice': choice['label'],
            'sourceReferences': ['SOURCE_0'], 'acceptedConcernGroupId': identifier,
            'acceptedCandidateScope': choice['acceptedCandidateScope']}}}, 'selection')
    chosen = drafting.draft_workout_sessions(None, {'preparationId': 'menus'}, messages, equipment, {})
    assert calls == ['baseline', 'candidate', 'candidate']
    assert chosen['submittedDraft']['workouts'][0]['name'] == selection
    assert chosen['jointPlanning']['proofOwner'] == selection
    expected = prepared if selection == 'baseline' else alternate
    assert chosen['semanticSelection'] == {**expected['semanticSelection'], 'fixedWorkouts': []}
    assert drafting.current_semantic_selection(messages, equipment) == chosen['semanticSelection']
    replacement = alternate if selection == 'baseline' else primary
    admitted = {**replacement['semanticSelection'], 'fixedWorkouts': []}
    store(messages, 'audit_workout_plan', {}, {**identity, 'semanticSelection': admitted}, 'admitted-repair')
    assert drafting.current_semantic_selection(messages, equipment) == admitted


def test_menu_qualification_union_deduplicates_and_retains_conflicting_evidence():
    first = {'inputHashes': {'LIBRARY_0': 'same'}, 'contracts': [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['push']}]}
    second = {'inputHashes': {'LIBRARY_0': 'same', 'LIBRARY_1': 'other'}, 'contracts': [
        {'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['push']},
        {'definition_id': 'LIBRARY_1', 'satisfiesCoverage': ['pull']}]}
    merged = drafting._merge_menu_qualifications(first, second)
    assert merged['inputHashes'] == second['inputHashes']
    assert merged['contracts'] == second['contracts']
    assert 'qualificationConflicts' not in merged
    changed = copy.deepcopy(second)
    changed['inputHashes']['LIBRARY_0'] = 'conflicting-context'
    conflict = drafting._merge_menu_qualifications(first, changed)
    assert conflict['qualificationConflicts'] == [{'definition_id': 'LIBRARY_0',
        'retainedInputHash': 'same', 'conflictingInputHash': 'conflicting-context'}]


@pytest.mark.parametrize('retained_full_week', [False, True])
def test_omission_feedback_uses_saved_semantic_artifact_choice(monkeypatch, retained_full_week):
    from workout_generator_pkg import allocation, joint_planning
    from test_workout_generator_session_repetition import repetition_case
    from test_workout_generator_planning_tools import requirement_messages

    equipment, record, draft, context = repetition_case(monkeypatch)
    record['requirements']['executionRules'][0]['maximumSets'] = 6
    for item in draft['workouts'][0]['exercises']:
        item['allocationBounds']['maximum'] = 6
    if retained_full_week:
        record['requirements']['sessionsPerWeek'] = 3
        draft['workouts'] = [copy.deepcopy(draft['workouts'][0]) for _ in range(3)]
        for index, day in enumerate(draft['workouts']):
            day.update(name=f'Day {index}', trainingDays=[2 * index])
        monkeypatch.setattr(drafting, 'latest_draft_submission', lambda *_: (draft, 'RETAINED_WEEK'))
    selection = {'mode': 'selected_menu',
        'definitionIds': [item['id'] for item in equipment['exerciseDefinitions']], 'fixedWorkouts': []}
    prepared = {'semanticSelection': selection, 'sourceWorkingSetBudget': None}
    candidate = copy.deepcopy(draft['workouts'])
    for day in candidate:
        day['exercises'] = day['exercises'][:1]
        day['exercises'][0]['numWorkSets'] = 5
    revised = {'mode': 'selected_menu', 'definitionIds': [equipment['exerciseDefinitions'][0]['id']],
        'fixedWorkouts': []}
    joint = {'feasible': True, 'status': 'feasible', 'completeCandidateRefinement': {
        'semanticMenuAlternative': {'sessions': candidate, 'semanticSelection': revised,
            'jointPlanning': {'feasible': True, 'status': 'feasible'}}}}
    messages = requirement_messages(record)
    before = copy.deepcopy((draft, joint, prepared))

    result = drafting._fresh_semantic_menu_tradeoff(draft, joint, prepared, record,
        equipment, messages, None, {}, True)

    assert result['passed'] is False
    assert len(result['programmingDecisionChoices']) == 2
    comparison = result['jointCandidateComparison']
    assert comparison['decision'] == 'requires_programming_decision'
    assert comparison['baselineAuditErrors'] == comparison['candidateAuditErrors'] == []
    artifacts = comparison['programmingArtifacts']
    assert artifacts['baseline']['semanticSelection']['definitionIds'] == selection['definitionIds']
    assert artifacts['candidate']['semanticSelection'] == revised
    assert artifacts['baseline']['submittedDraft'] == draft
    assert artifacts['candidate']['submittedDraft']['workouts'] == candidate
    assert (draft, joint, prepared) == before


def test_count_consolidation_cannot_bypass_committed_semantic_menu(monkeypatch):
    from test_workout_generator_session_repetition import repetition_case
    from test_workout_generator_planning_tools import requirement_messages

    equipment, record, draft, _ = repetition_case(monkeypatch)
    record['requirements']['executionRules'][0]['maximumSets'] = 6
    for item in draft['workouts'][0]['exercises']:
        item['allocationBounds']['maximum'] = 6
    selection = {'mode': 'selected_menu',
        'definitionIds': [item['id'] for item in equipment['exerciseDefinitions']], 'fixedWorkouts': []}
    monkeypatch.setattr(drafting, 'current_semantic_selection', lambda *args, **kwargs: selection)
    before = copy.deepcopy(draft)

    result = drafting._fresh_development_tradeoff(draft, record, equipment,
        requirement_messages(record), None, None, {})

    assert result['jointCandidateSearchDiagnostic']['status'] == 'no_audited_count_tradeoff'
    assert 'proposedSubmission' not in result
    assert 'programmingDecisionChoices' not in result
    assert draft == before


@pytest.mark.parametrize('infeasible_reference', ['LIBRARY_0', 'LIBRARY_1'])
def test_proven_preparation_conflict_preserves_the_other_menu(monkeypatch, infeasible_reference):
    equipment, messages, _ = shortlist_case()
    alternative = copy.deepcopy(equipment['exerciseDefinitions'][0])
    alternative['id'] += '-alternative'
    equipment['exerciseDefinitions'].append(alternative)
    def prepare(arguments, *args, **kwargs):
        references = {item['definition_id'] for day in arguments['sessions'] for item in day['exercises']}
        if references == {infeasible_reference}:
            raise drafting.PlanningInputError('infeasible_set_allocation', 'Proven fixture menu conflict.',
                '/sessions', 'Select another menu.', errors=[{'code': 'infeasible_set_allocation'}])
        return {**arguments, 'preparationId': 'feasible'}
    monkeypatch.setattr(drafting, '_prepare_week', prepare)
    result = drafting.prepare_workout_sessions({'selectionMode': 'selected_menu',
        'definition_ids': ['LIBRARY_0'], 'alternative_definition_ids': ['LIBRARY_1']}, messages, equipment)
    assert 'alternativePreparation' not in result
    assert 'menuPreparationErrors' in result
    assert {item['definition_id'] for day in result['sessions'] for item in day['exercises']} == (
        {'LIBRARY_1'} if infeasible_reference == 'LIBRARY_0' else {'LIBRARY_0'})
