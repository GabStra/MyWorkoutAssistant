import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from workout_generator_pkg import plan_review
from workout_generator_pkg.interactive_shell import handle_function_call
from workout_generator_pkg.planning_decisions import (
    confirmed_setup_access, execution_decision_definitions, propose_decisions,
    record_planning_decisions_tool,
)
from workout_generator_pkg.planning_tools import PlanningInputError, library_fingerprint
from test_workout_generator_planning_decisions import store


def context_case():
    equipment = {'exerciseDefinitions': [
        {'id': 'raise', 'name': 'Dumbbell lateral raise', 'equipmentId': 'db',
         'requiredAccessoryEquipmentIds': [], 'muscleGroups': ['BACK_DELTOID']},
        {'id': 'press', 'name': 'Barbell press', 'equipmentId': 'bar',
         'requiredAccessoryEquipmentIds': ['bench'], 'muscleGroups': ['FRONT_CHEST']},
        {'id': 'rotation', 'name': 'Woodchopper', 'equipmentId': 'db',
         'requiredAccessoryEquipmentIds': [], 'muscleGroups': ['FRONT_OBLIQUES'],
         'reviewedExecution': {'limbMode': 'bilateral'}}],
        'equipments': [{'id': 'db', 'name': 'Dumbbells'}, {'id': 'bar', 'name': 'Barbell'}],
        'accessoryEquipments': [{'id': 'bench', 'name': 'Bench'}]}
    requirements = {'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 5}}},
        'executionRules': [{'kind': 'supersetNoReconfiguration'}]}
    messages = [{'role': 'user', 'content': 'I can use the clear floor for dumbbell lateral raises while the barbell and bench remain in place. Choose a sensible rep-counting basis for woodchoppers.'}]
    arguments = {'decisions': [
        {'topic': 'Independent clear-space access', 'choice': 'Lateral raises remain accessible.',
         'sourceReferences': ['SOURCE_0'], 'confirmedSetupAccess': {
             'independentExercises': ['Dumbbell lateral raise'], 'retainedResources': ['Barbell', 'Bench']}},
        {'topic': 'Woodchopper counting', 'choice': 'Repeat the prescribed reps on each side.',
         'sourceReferences': ['SOURCE_0'], 'executionPrescription': {
             'exercise': 'Woodchopper', 'setMode': 'paired_sides'}}]}
    return equipment, requirements, messages, arguments


def test_planner_decisions_project_input_choices_without_mutating_backend_identity():
    from workout_generator_pkg.planner_context import _decision_selection_projection
    equipment, _, messages, arguments = context_case()
    backend = propose_decisions(arguments, messages, equipment)
    original = copy.deepcopy(backend)
    projected = _decision_selection_projection(backend, equipment)
    for index, argument in enumerate(arguments['decisions']):
        for field in ('confirmedSetupAccess', 'executionPrescription'):
            if field in argument:
                assert projected['decisions'][f'DECISION_{index}'][field] == argument[field]
    assert backend == original
    unknown = {'executionPrescription': {'definitionId': 'not-current', 'setMode': 'single_sequence'}}
    assert _decision_selection_projection(unknown, equipment) == unknown


def test_live_decision_gate_compiles_reviewed_setup_and_execution_without_mutating_inputs(monkeypatch):
    equipment, requirements, messages, arguments = context_case()
    original_equipment, original_requirements = copy.deepcopy(equipment), copy.deepcopy(requirements)
    contexts = []
    def accept(client, request, **options):
        contexts.append(json.loads(request[-1]['content']))
        assert 'Delegation, equipment possession and acceptance of uncertainty do not establish this fact' in request[0]['content']
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', accept)
    assert not confirmed_setup_access(messages, equipment, requirements)['bindings']
    assert execution_decision_definitions(messages, equipment) == {}
    result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', arguments, equipment)['result'])
    assert result['passed'] and len(contexts) == 1
    assert contexts[0]['decisionSelections']['definitions'][0]['name'] == 'Dumbbell lateral raise'
    assert result['decisions']['DECISION_0']['factualContextLibraryFingerprint'] == library_fingerprint(equipment)
    assert result['decisions']['DECISION_0']['confirmedSetupAccess'] == {
        'independentDefinitionIds': ['raise'], 'retainedResourceIds': ['bar', 'bench']}
    assert result['decisions']['DECISION_1']['executionPrescription'] == {
        'definitionId': 'rotation', 'setMode': 'paired_sides'}
    store(messages, 'record_planning_decisions', arguments, result, 'context')
    bound = confirmed_setup_access(messages, equipment, requirements)
    assert bound['requirements']['executionRules'][0]['confirmedIndependentPairs'] == [['press', 'raise']]
    assert bound['bindings'][0]['sourceReferences'] == ['SOURCE_0']
    definitions = execution_decision_definitions(messages, equipment)
    assert definitions['rotation']['reviewedExecution'] == {'limbMode': 'bilateral', 'setMode': 'paired_sides'}
    assert equipment == original_equipment and requirements == original_requirements
    assert bound['requirements']['auditTargets'] == requirements['auditTargets']
    changed = copy.deepcopy(equipment)
    changed['exerciseDefinitions'][0]['requiredAccessoryEquipmentIds'] = ['bench']
    assert not confirmed_setup_access(messages, changed, requirements)['bindings']
    assert execution_decision_definitions(messages, changed) == {}


def test_typed_decision_fields_use_current_library_choices_and_cannot_forge_provenance():
    equipment, _, messages, arguments = context_case()
    schema = record_planning_decisions_tool(messages, equipment)['function']['parameters']
    assert schema['properties']['decisions']['items']['properties']['executionPrescription']['properties']['exercise']['enum'] == ['Barbell press', 'Dumbbell lateral raise', 'Woodchopper']
    invalid = copy.deepcopy(arguments)
    invalid['decisions'][0]['confirmedSetupAccess']['retainedResources'] = ['unknown']
    with pytest.raises(ValidationError):
        propose_decisions(invalid, messages, equipment)
    invalid = copy.deepcopy(arguments)
    invalid['decisions'][0]['factualContextLibraryFingerprint'] = 'invented'
    with pytest.raises(ValidationError):
        propose_decisions(invalid, messages, equipment)
    invalid = copy.deepcopy(arguments)
    invalid['decisions'][0]['confirmedSetupAccess']['retainedResources'] = ['Dumbbells']
    with pytest.raises(PlanningInputError, match='cannot use the retained'):
        propose_decisions(invalid, messages, equipment)


def test_delegation_alone_does_not_save_physical_access_claim(monkeypatch):
    equipment, requirements, messages, arguments = context_case()
    messages[0]['content'] = 'Choose the workout and suitable supersets for me.'
    def reject(client, request, **options):
        assert 'factual physical-access assertion' in request[0]['content']
        return json.dumps({'findings': [{'severity': 'blocking',
            'path': '/decisions/DECISION_0/confirmedSetupAccess',
            'message': 'Delegation does not establish physical clear-space access.',
            'evidencePaths': ['/sourceMessages/SOURCE_0/content'],
            'repair': 'Ask the user to confirm this physical configuration.'}]}), None, None
    monkeypatch.setattr(plan_review, 'chat_call', reject)
    result = json.loads(handle_function_call(None, messages, 'record_planning_decisions', arguments, equipment)['result'])
    assert not result['passed'] and result['decisions'] == {}
    store(messages, 'record_planning_decisions', arguments, result, 'rejected')
    assert not confirmed_setup_access(messages, equipment, requirements)['bindings']
    assert execution_decision_definitions(messages, equipment) == {}


def test_changed_execution_choice_requires_superseding_identity_even_under_new_topic():
    equipment, _, messages, arguments = context_case()
    proposal = propose_decisions(arguments, messages, equipment)
    store(messages, 'record_planning_decisions', arguments,
        {**proposal, 'passed': True, 'decisionReview': {'passed': True}}, 'first')
    changed = copy.deepcopy(arguments['decisions'][1])
    changed['topic'] = 'Different topic cannot hide the existing choice'
    changed['executionPrescription']['setMode'] = 'single_sequence'
    with pytest.raises(PlanningInputError, match='silently replaced'):
        propose_decisions({'decisions': [changed]}, messages, equipment)

    messages.append({'role': 'user', 'content': 'Use one total rep sequence for woodchoppers instead.'})
    changed.update(sourceReferences=['SOURCE_1'], supersedes='DECISION_1', reason='The user changed the counting choice.')
    replacement = propose_decisions({'decisions': [changed]}, messages, equipment)
    assert replacement['decisions']['DECISION_1']['supersededBy'] == 'DECISION_2'
    assert replacement['decisions']['DECISION_2']['executionPrescription']['setMode'] == 'single_sequence'
    store(messages, 'record_planning_decisions', {'decisions': [changed]},
        {**replacement, 'passed': True, 'decisionReview': {'passed': True}}, 'replacement')
    assert execution_decision_definitions(messages, equipment)['rotation']['reviewedExecution']['setMode'] == 'single_sequence'


def test_original_physical_source_names_resolve_to_current_canonical_definitions():
    bar, bench, rack = ('a247d19d-e625-4c84-af6a-f643bb1d076c',
        'e3f0e0ee-3433-4435-bed9-c926e23a8468', '31159650-e64d-47ba-95b3-a63ce301dbac')
    pair, single = 'fcecd1f6-25e1-4d8b-a3d1-58cdffd6b86c', 'f145a180-eaae-4fe1-b7b4-5527ec8adb04'
    raise_id, crunch_id, woodchopper_id = ('531463a1-bb50-5265-8eda-13fbf9a1b7e2',
        'c3e3e44c-16f0-5006-ac49-a9b844ddca8b', '8e0ccbd0-29c1-58f1-9c0d-06245950ebea')
    equipment = {'exerciseDefinitions': [
        {'id': raise_id, 'name': 'Dumbbell Lateral Raise (Dumbbell Pair)', 'equipmentId': pair},
        {'id': crunch_id, 'name': 'Weighted Dumbbell Crunch', 'equipmentId': single},
        {'id': woodchopper_id, 'name': 'Dumbbell Woodchopper', 'equipmentId': single}],
        'equipments': [{'id': bar, 'name': 'Barbell'}, {'id': pair, 'name': 'Dumbbell Pair'},
                       {'id': single, 'name': 'Dumbbell'}],
        'accessoryEquipments': [{'id': bench, 'name': 'Adjustable Bench'}, {'id': rack, 'name': 'Squat Rack'}]}
    messages = [{'role': 'user', 'content': 'Separate clear floor space is available for dumbbell lateral raises and weighted floor crunches while the rack, barbell and bench remain positioned. Choose the woodchopper counting basis.'}]
    arguments = {'decisions': [{'topic': 'Floor space', 'choice': 'The stated floor configurations remain accessible.',
        'sourceReferences': ['SOURCE_0'], 'confirmedSetupAccess': {
            'independentExercises': ['Dumbbell Lateral Raise (Dumbbell Pair)', 'Weighted Dumbbell Crunch'],
            'retainedResources': ['Squat Rack', 'Barbell', 'Adjustable Bench']}},
        {'topic': 'Woodchopper counting', 'choice': 'Prescribe each direction.', 'sourceReferences': ['SOURCE_0'],
         'executionPrescription': {'exercise': 'Dumbbell Woodchopper', 'setMode': 'paired_sides'}}]}
    original = copy.deepcopy(arguments)
    proposal = propose_decisions(arguments, messages, equipment)
    assert proposal['decisions']['DECISION_0']['confirmedSetupAccess'] == {
        'independentDefinitionIds': sorted([raise_id, crunch_id]), 'retainedResourceIds': sorted([bar, bench, rack])}
    assert proposal['decisions']['DECISION_1']['executionPrescription'] == {
        'definitionId': woodchopper_id, 'setMode': 'paired_sides'}
    assert proposal['sourceMessages']['SOURCE_0']['content'] == messages[0]['content']
    assert arguments == original
    assert 'decisionReview' not in proposal


def test_complete_structured_intake_reviews_and_compiles_physical_context_without_changing_policy(monkeypatch):
    from workout_generator_pkg import planning_tools
    from workout_generator_pkg.joint_planning import _superset_pair_rejection
    from workout_generator_pkg.planner_context import _decision_selection_projection
    from workout_generator_pkg.requirement_accounting import STRUCTURED_REQUIREMENTS_MARKER

    equipment, _, messages, arguments = context_case()
    equipment['equipments'][0]['type'] = 'DUMBBELLS'
    equipment['equipments'][1]['type'] = 'BARBELL'
    equipment['exerciseDefinitions'][0]['muscleGroups'] = ['BACK_DELTOIDS']
    for definition in equipment['exerciseDefinitions']:
        definition.update(exerciseType='WEIGHT', exerciseCategory='ISOLATION', secondaryMuscleGroups=[])
    equipment['exerciseDefinitions'].append({'id': 'station', 'name': 'Bench movement',
        'equipmentId': None, 'requiredAccessoryEquipmentIds': ['bench']})
    requirements = json.loads(Path('docs/workout_generator_initial_requirements.json').read_text(encoding='utf-8'))
    requirements.update(requiredCoverage=[], familySetBounds=[], objectiveOrder=['duration_balance'],
        exerciseRestrictions={'excludeNameTerms': [], 'exceptNameTerms': []},
        auditTargets={'weeklyEffectiveSets': {'chest': {'minimum': 0, 'maximum': None}},
            'perSessionEffectiveSets': {}, 'maximumSessionSeconds': 5400},
        executionRules=[{'kind': 'supersetNoReconfiguration', 'coverageKey': None,
            'confirmedIndependentPairs': []}])
    requirements.pop('objectiveTiers', None)
    messages[0]['content'] += (' Barbell and Bench are one shared physical station.\n'
        + STRUCTURED_REQUIREMENTS_MARKER + '\n' + json.dumps(requirements))
    arguments['decisions'] = [arguments['decisions'][0], {
        'topic': 'Shared station', 'choice': 'Barbell and bench share one station.',
        'sourceReferences': ['SOURCE_0'], 'confirmedSharedStation': ['Barbell', 'Bench']}]
    tool_arguments = {'planningDecisions': arguments}
    schema = planning_tools.workout_requirements_tool(equipment, messages)['function']['parameters']
    validate(tool_arguments, schema)
    with pytest.raises(ValidationError):
        validate({'planningDecisions': {'decisions': [{
            'topic': 'Policy', 'choice': 'Invent another rule.', 'sourceReferences': ['SOURCE_0']}]}}, schema)
    calls = []

    def accept(client, request, **options):
        calls.append(json.loads(request[-1]['content']))
        return '{"findings":[]}', None, None

    monkeypatch.setattr(plan_review, '_review_call', accept)
    result = json.loads(handle_function_call(None, messages, 'set_workout_requirements',
        tool_arguments, equipment)['result'])
    assert result['passed'] and result['jointDecisionReview']['passed'] and len(calls) == 1
    assert result['requirements'] == planning_tools.set_workout_requirements({}, messages, equipment)['requirements']
    original = copy.deepcopy(result['requirements'])
    store(messages, 'set_workout_requirements', tool_arguments, result, 'physical-intake')
    bound = confirmed_setup_access(messages, equipment, original)
    rule = bound['requirements']['executionRules'][0]
    assert rule['sharedResourceGroups'] == [['bar', 'bench']]
    assert rule['confirmedIndependentPairs'] == [['press', 'raise'], ['raise', 'station']]
    assert _decision_selection_projection(result['decisions'], equipment)['DECISION_1']['confirmedSharedStation'] == ['Barbell', 'Bench']
    definitions = {item['id']: item for item in equipment['exerciseDefinitions']}
    rejection = lambda first, second, policy: _superset_pair_rejection(
        {'definition_id': first}, {'definition_id': second}, definitions, policy, equipment)
    assert rejection('press', 'raise', original) == 'simultaneous_access_unconfirmed'
    assert rejection('press', 'raise', bound['requirements']) is None
    assert rejection('press', 'station', bound['requirements']) == 'shared_physical_station'
    assert rejection('press', 'rotation', bound['requirements']) == 'simultaneous_access_unconfirmed'
    assert result['requirements'] == original
    changed = copy.deepcopy(equipment)
    changed['exerciseDefinitions'][0]['requiredAccessoryEquipmentIds'] = ['bench']
    assert confirmed_setup_access(messages, changed, original)['requirements'] == original


@pytest.mark.parametrize('bad_selection', ['Invented Woodchopper', 'rotation', '07fcecde-67c8-549a-9522-3eb46f62cfd8'])
def test_unknown_or_uuid_execution_selections_do_not_reach_authorization(bad_selection):
    equipment, _, messages, arguments = context_case()
    arguments['decisions'][1]['executionPrescription']['exercise'] = bad_selection
    with pytest.raises(ValidationError):
        propose_decisions(arguments, messages, equipment)


def test_ambiguous_labels_are_not_selectable():
    equipment, _, messages, arguments = context_case()
    equipment['exerciseDefinitions'].append({**equipment['exerciseDefinitions'][2], 'id': 'another_rotation'})
    schema = record_planning_decisions_tool(messages, equipment)['function']['parameters']
    choices = schema['properties']['decisions']['items']['properties']['executionPrescription']['properties']['exercise']['enum']
    assert 'Woodchopper' not in choices
    with pytest.raises(ValidationError):
        propose_decisions(arguments, messages, equipment)


def programming_choice_case(receipt_tool='audit_workout_plan', unknown=False):
    from workout_generator_pkg.planning_tools import set_workout_requirements
    from workout_generator_pkg.planning_decisions import candidate_acceptance_scope
    from workout_generator_pkg.repair_execution import apply_repair_promotion_gate
    from test_workout_generator_planning_tools import planning_case, requirement_messages
    equipment, requirements, _, draft = planning_case()
    requirements['preferenceResolution'] = 'explicit_tradeoffs'
    stored = set_workout_requirements(requirements,
        [{'role': 'user', 'content': 'Keep the stated requirements; show explicit choices when feasible candidates exchange preferences.'}], equipment)
    draft['requirementsId'] = stored['requirementsId']
    for workout in draft['workouts']:
        for exercise in workout['exercises']:
            exercise.pop('placementNotes', None)
    candidate = {'passed': True, 'requirementsId': stored['requirementsId'],
        'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
        'audit': {'issues': [], 'errors': []}, 'submittedDraft': draft, 'errors': []}
    baseline = copy.deepcopy(candidate)
    baseline['submittedDraft']['workouts'][0]['name'] = 'Baseline'
    comparison = {'decision': 'incomparable', 'reason': 'soft_preference_tradeoff_requires_decision',
        'baselineAuditErrors': [], 'candidateAuditErrors': [],
        'baselineAcceptanceScope': candidate_acceptance_scope(baseline),
        'programmingTradeoff': {'status': 'requires_programming_decision',
            'improved': [{'objective': 'duration_economy', 'baseline': 100, 'candidate': 70}],
            'worsened': [{'objective': 'setup_economy_resource_switches', 'baseline': 19, 'candidate': 21}],
            'unknownObjectives': [], 'developmentChanges': [], 'hardErrors': {'baseline': [], 'candidate': []}}}
    if unknown:
        comparison['programmingTradeoff']['status'] = 'unknown'
        comparison['programmingTradeoff']['unknownObjectives'] = ['setup_economy_transitions']
    messages = requirement_messages(stored)
    gated = apply_repair_promotion_gate(candidate, comparison, messages=messages)
    store(messages, receipt_tool, {}, gated, 'tradeoff')
    return equipment, stored, candidate, comparison, messages, gated


def test_programming_question_is_displayable_and_numbered_answer_keeps_computed_tradeoff():
    from workout_generator_pkg.logging_ui import format_question
    from workout_generator_pkg.user_interaction import pending_question, answer_question
    _, _, _, _, messages, _ = programming_choice_case()
    question = pending_question(messages)
    assert question is not None
    assert '100 -> 70' in question['question'] and '19 -> 21' in question['question']
    assert all(isinstance(option, str) for option in question['options'])
    assert '1. Retain the baseline' in format_question(question)
    assert answer_question(question, '2') == 'My answer: ' + question['options'][1]


@pytest.mark.parametrize('selection,receipt_tool,unknown', [
    ('candidate', 'audit_workout_plan', False), ('baseline', 'audit_workout_plan', False),
    ('candidate', 'draft_workout_sessions', True)])
def test_code_programming_choice_uses_existing_review_and_stays_bound_after_acceptance(monkeypatch, selection, receipt_tool, unknown):
    from workout_generator_pkg.planning_decisions import resolved_decisions
    from workout_generator_pkg.repair_execution import apply_repair_promotion_gate
    equipment, stored, candidate, comparison, messages, gated = programming_choice_case(receipt_tool, unknown)
    assert not gated['passed'] and len(gated['programmingDecisionChoices']) == 2
    identifier = next(key for key, option in gated['programmingDecisionChoices'].items() if option['selection'] == selection)
    messages.append({'role': 'user', 'content': 'Use the candidate and accept its displayed tradeoff.'
        if selection == 'candidate' else 'Keep the baseline and stop this replacement.'})
    arguments = {'decisions': [{'topic': 'Explicit artifact choice', 'choice': messages[-1]['content'],
        'sourceReferences': ['SOURCE_1'], 'acceptedConcernGroupId': identifier}]}
    seen = []
    def approve(client, request, **options):
        context = json.loads(request[-1]['content'])
        seen.append(context)
        assert context['decisionSelections']['programmingChoices'][identifier]['selection'] == selection
        return '{"findings":[]}', None, None
    monkeypatch.setattr(plan_review, 'chat_call', approve)
    proposal = propose_decisions(arguments, messages, equipment)
    assert not resolved_decisions(messages)
    receipt = json.loads(handle_function_call(None, messages, 'record_planning_decisions', arguments, equipment)['result'])
    assert receipt['passed'] and len(seen) == 1
    store(messages, 'record_planning_decisions', arguments, receipt, 'accept-choice')
    fresh = copy.deepcopy(candidate)
    fresh['resolvedDecisions'] = resolved_decisions(messages)
    rechecked = apply_repair_promotion_gate(fresh, comparison, messages=messages)
    assert rechecked['programmingDecision']['selection'] == selection
    assert rechecked['passed'] is (selection == 'candidate')
    assert 'preview' not in rechecked and 'planIndex' not in rechecked
    assert 'review' not in rechecked  # Acceptance does not create semantic review.
    assert proposal['decisions']['DECISION_0']['acceptedCandidateScope'] == receipt['decisions']['DECISION_0']['acceptedCandidateScope']
    assert rechecked['requirementsId'] == stored['requirementsId']
    assert rechecked['jointCandidateComparison']['programmingTradeoff'] == comparison['programmingTradeoff']
    if selection == 'baseline':
        assert 'userQuestion' not in rechecked and 'Stop this replacement' in rechecked['instruction']
    changed = copy.deepcopy(fresh)
    changed['submittedDraft']['workouts'][0]['exercises'][0]['restBetweenSetsSeconds'] += 15
    assert not apply_repair_promotion_gate(changed, comparison, messages=messages)['passed']
    evidence_changed = copy.deepcopy(comparison)
    evidence_changed['programmingTradeoff']['worsened'][0]['candidate'] += 1
    assert not apply_repair_promotion_gate(fresh, evidence_changed, messages=messages)['passed']
    baseline_changed = copy.deepcopy(comparison)
    baseline_changed['baselineAcceptanceScope']['workoutsFingerprint'] = 'changed-baseline'
    assert not apply_repair_promotion_gate(fresh, baseline_changed, messages=messages)['passed']


@pytest.mark.parametrize('failure', ['candidate_hard_error', 'baseline_hard_error', 'missing_feasibility', 'policy_changed'])
def test_programming_acceptance_never_offers_or_waives_failed_native_or_stale_policy(failure):
    from workout_generator_pkg.repair_execution import apply_repair_promotion_gate, programming_decision_choices
    equipment, stored, candidate, comparison, messages, gated = programming_choice_case()
    if failure == 'candidate_hard_error':
        candidate['audit']['errors'] = [{'code': 'duration_exceeded'}]
        comparison['candidateAuditErrors'] = ['native_audit_has_errors']
    elif failure == 'baseline_hard_error':
        comparison['programmingTradeoff']['hardErrors']['baseline'] = ['invalid_setup']
    elif failure == 'missing_feasibility':
        comparison.pop('candidateAuditErrors')
    else:
        stored['requirements']['preferenceResolution'] = 'strict_lexicographic'
        stored['sourceReview'] = {}
        store(messages, 'set_workout_requirements', {}, stored, 'policy-change')
    checked = apply_repair_promotion_gate(candidate, comparison, messages=messages)
    assert not checked['passed'] and not checked.get('programmingDecisionChoices')
    if failure != 'policy_changed':
        assert programming_decision_choices(candidate, comparison) == {}
    if failure == 'policy_changed':
        assert 'acceptedConcernGroupId' not in record_planning_decisions_tool(messages, equipment)['function']['parameters']['properties']['decisions']['items']['properties']


def test_native_feasible_unknown_preference_choice_retains_unknown_facts():
    from workout_generator_pkg.repair_execution import programming_decision_choices
    _, _, candidate, comparison, _, _ = programming_choice_case()
    comparison['programmingTradeoff']['status'] = 'unknown'
    comparison['programmingTradeoff']['unknownObjectives'] = ['setup_economy_transitions']
    original = copy.deepcopy(comparison)
    choices = programming_decision_choices(candidate, comparison)
    assert len(choices) == 2
    assert choices['CONCERN_programming_use_candidate']['acceptedCandidateScope']['programmingTradeoff']['unknownObjectives'] == ['setup_economy_transitions']
    assert comparison == original


@pytest.mark.parametrize('selection', ['candidate', 'baseline'])
def test_final_review_projects_only_exact_programming_choice_without_semantic_waiver(selection):
    from workout_generator_pkg.planning_decisions import candidate_acceptance_scope, resolved_decisions
    from workout_generator_pkg.planning_tools import audit_workout_plan
    from workout_generator_pkg.repair_execution import programming_decision_choices
    from test_workout_generator_planning_tools import capability_requirement_messages

    equipment, stored, candidate, comparison, _, _ = programming_choice_case(unknown=True)
    messages = capability_requirement_messages(stored, equipment)
    candidate = audit_workout_plan(candidate['submittedDraft'], equipment, messages)
    candidate['historyFingerprint'] = None
    assert candidate['passed'] and not candidate['audit']['errors']
    baseline = copy.deepcopy(candidate)
    baseline['submittedDraft']['workouts'][0]['name'] = 'Baseline'
    comparison['baselineAcceptanceScope'] = candidate_acceptance_scope(baseline)
    identifier = f'CONCERN_programming_{"use_candidate" if selection == "candidate" else "retain_baseline"}'
    choice = programming_decision_choices(candidate, comparison)[identifier]
    messages.append({'role': 'user', 'content': choice['label']})
    decisions = resolved_decisions(messages)
    decisions['DECISION_1'] = {
        'topic': 'Exact displayed programming choice', 'choice': choice['label'],
        'sourceReferences': ['SOURCE_2'], 'acceptedConcernGroupId': identifier,
        'acceptedCandidateScope': choice['acceptedCandidateScope']}
    store(messages, 'record_planning_decisions', {}, {
        'passed': True, 'decisionReview': {'passed': True}, 'decisions': decisions}, 'reviewed-choice')
    selected = copy.deepcopy(candidate if selection == 'candidate' else baseline)
    selected['resolvedDecisions'] = resolved_decisions(messages)
    finding = {'concernGroupId': 'CONCERN_distinct_semantic_issue', 'basis': 'soft_tradeoff',
        'decisionId': 'DECISION_1', 'severity': 'warning', 'message': 'A separately reviewable concern.'}
    selected['reviewChecklist'] = {'findings': {'OBLIGATION_0': {'finding': finding}}}
    original = copy.deepcopy(selected)

    context = plan_review._context(selected, messages, equipment, None, len(messages) - 1)

    assert context['acceptedProgrammingChoices'] == {'DECISION_1': {
        'selection': selection, 'tradeoff': comparison['programmingTradeoff'], 'sourceReferences': ['SOURCE_2'],
        'scope': 'Exact displayed preference choice only; unknown facts remain unknown and new semantic concerns remain reviewable.'}}
    assert context['acceptedProgrammingChoices']['DECISION_1']['tradeoff']['unknownObjectives'] == ['setup_economy_transitions']
    assert context['reviewChecklist'] == selected['reviewChecklist']
    assert not plan_review._soft_tradeoff_terminal_evidence(context, finding,
        ['/resolvedDecisions/DECISION_1', '/finalArtifact'])
    assert selected == original and 'review' not in selected

    for changed in ('candidate', 'requirementsId', 'libraryFingerprint', 'historyFingerprint'):
        stale = copy.deepcopy(selected)
        if changed == 'candidate':
            stale['submittedDraft']['workouts'][0]['name'] += ' changed'
        elif changed == 'requirementsId':
            stale['requirementsId'] = stale['submittedDraft']['requirementsId'] = 'REQUIREMENTS_changed'
        else:
            stale[changed] = 'changed'
        assert plan_review._context(stale, messages, equipment, None,
            len(messages) - 1)['acceptedProgrammingChoices'] == {}
