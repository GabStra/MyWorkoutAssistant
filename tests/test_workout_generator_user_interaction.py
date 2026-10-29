import json

import pytest
from jsonschema import ValidationError

from test_workout_generator_conversation_sessions import FakeFunction, FakeToolCall, make_shell_deps, run_shell
from workout_generator_pkg import interactive_shell as shell
from workout_generator_pkg.conversation_store import load_active_conversation_record
from workout_generator_pkg.user_interaction import (answer_question, clarification_question, pending_question,
    preference_comparison_concerns, PROPOSE_WORKOUT_ALTERNATIVES_TOOL)
from workout_generator_pkg.logging_ui import format_question
from workout_generator_pkg.constants import EXACT_GENERATION_CONFIRMATION


@pytest.mark.parametrize('options, answer, expected', [
    (['Stationary work only', 'Walking is fine'], '1', 'Stationary work only'),
    ([], '3', '3'),
    (['CONFIRM GENERATE'], '1', 'CONFIRM GENERATE'),
    (['Stationary work only', 'Walking is fine'], 'Neither; ask me about the available space first.',
     'Neither; ask me about the available space first.'),
])
def test_question_tool_waits_records_answer_and_never_grants_approval(monkeypatch, tmp_path, capsys, options, answer, expected):
    question = {'question': 'Which setup can you use?', 'options': options}
    ask = FakeToolCall('question', 'function', FakeFunction('ask_user', json.dumps(question)))
    dependent = FakeToolCall('export', 'function', FakeFunction('generate_workout', '{}'))
    generated, requests = [], []
    deps = make_shell_deps(tmp_path, chat_results=[(None, [ask, dependent]), ('Answer recorded.', None)],
                           generation_results=[], generation_calls=generated)
    original = deps.chat_call_with_loading

    def capture(client, messages, tools, logger, **options):
        requests.append((messages, tools))
        return original(client, messages, tools, logger, **options)

    deps.chat_call_with_loading = capture
    run_shell(monkeypatch, deps, ['Plan a workout', answer, '/exit'])
    messages = load_active_conversation_record(str(tmp_path))['messages']
    assert not generated and len(requests) == 2
    assert all(any(t.get('function', {}).get('name') == 'ask_user' for t in tools) for _, tools in requests)
    response = next(m for m in messages if m.get('userInteraction'))
    assert response['content'] == 'My answer: ' + expected
    assert response['userInteraction']['input'] == answer
    assert any(m.get('role') == 'assistant' and question['question'] in m.get('content', '')
               and not m.get('tool_calls') for m in messages)
    assert all('userInteraction' not in m for m in shell._messages_for_api(messages))
    skipped = json.loads(next(m['content'] for m in messages if m.get('tool_call_id') == 'export'))
    assert skipped['skipped']
    output = capsys.readouterr().out
    assert 'Question> Which setup can you use?' in output
    assert 'type your own response' in output.casefold()
    assert pending_question(messages) is None


def test_unanswered_question_survives_saved_history_and_commands(monkeypatch, tmp_path):
    question = {'question': 'How many sessions?', 'options': []}
    ask = FakeToolCall('question', 'function', FakeFunction('ask_user', json.dumps(question)))
    deps = make_shell_deps(tmp_path, chat_results=[(None, [ask])], generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, ['Plan a workout', '', '/view', '/exit'])
    messages = load_active_conversation_record(str(tmp_path))['messages']
    pending = pending_question(messages)
    assert pending['question'] == question['question']
    assert answer_question(pending, '/exit') == '/exit'
    assert answer_question(pending, '3') == 'My answer: 3'
    assert not any(m.get('userInteraction') for m in messages)


def test_recommendation_is_rendered_saved_and_never_selects_an_answer(monkeypatch, tmp_path, capsys):
    question = {'question': 'Which scheduling option do you prefer?',
                'options': ['Keep the current days', 'Move the demanding session'],
                'recommendation': {'option': 2, 'reason': 'More recovery before your priority session; it changes your training days.'}}
    ask = FakeToolCall('question', 'function', FakeFunction('ask_user', json.dumps(question)))
    deps = make_shell_deps(tmp_path, chat_results=[(None, [ask])], generation_results=[], generation_calls=[])
    run_shell(monkeypatch, deps, ['Plan a workout', '', '/exit'])
    messages = load_active_conversation_record(str(tmp_path))['messages']
    pending = pending_question(json.loads(json.dumps(messages)))
    assert pending['recommendation'] == question['recommendation']
    assert '2. Move the demanding session (Recommended)' in capsys.readouterr().out
    assert 'Why: ' + question['recommendation']['reason'] in format_question(pending)
    assert 'type your own response' in format_question(pending)
    assert not any(m.get('userInteraction') for m in messages)
    assert answer_question(pending, '') == 'My answer: '
    assert answer_question(pending, '1') == 'My answer: Keep the current days'
    assert answer_question(pending, 'Neither; keep Monday free.') == 'My answer: Neither; keep Monday free.'


@pytest.mark.parametrize('options, recommendation', [
    ([], {'option': 1, 'reason': 'Preferred.'}),
    (['A'], {'option': 2, 'reason': 'Preferred.'}),
    (['A'], {'option': 0, 'reason': 'Preferred.'}),
    (['A'], {'option': True, 'reason': 'Preferred.'}),
    (['A'], {'option': 1, 'reason': '   '}),
])
def test_recommendations_require_a_real_option_and_reason(options, recommendation):
    with pytest.raises((ValueError, ValidationError)):
        clarification_question({'question': 'Choose?', 'options': options, 'recommendation': recommendation})


@pytest.mark.parametrize('kind', ['requirements', 'generation'])
def test_approval_requires_explicit_valid_choice_and_supports_revisions(kind):
    question = {'kind': kind, 'question': 'Approve?', 'options': ['Approve', 'Revise']}
    assert answer_question(question, '') == ''
    assert answer_question(question, 'yes') == 'yes'
    assert answer_question(question, 'Change the schedule to Tuesday and Friday.') == 'Change the schedule to Tuesday and Friday.'
    assert answer_question(question, '1') == ('CONFIRM REQUIREMENTS' if kind == 'requirements' else 'CONFIRM GENERATE')
    assert 'Ask what I want changed' in answer_question(question, '2')
    with pytest.raises(ValueError, match='listed number'):
        answer_question(question, '3')


def test_question_validation_rejects_blank_prompts_and_model_approval_actions():
    with pytest.raises(ValueError):
        clarification_question({'question': '   '})
    with pytest.raises(ValidationError):
        clarification_question({'question': 'Approve?', 'action': 'generate_workout'})


def test_preference_comparison_selector_uses_reviewed_source_accounting_and_excludes_accepted_or_hard_findings():
    findings = [
        {'concernGroupId': 'CONCERN_PREF', 'basis': 'soft_tradeoff', 'action': 'advisory',
         'decisionId': None, 'message': 'The approved preference remains incomplete.',
         'evidencePaths': ['/sourceMessages/SOURCE_0', '/draft/exercises/0']},
        {'concernGroupId': 'CONCERN_ACCEPTED', 'basis': 'soft_tradeoff', 'action': 'advisory',
         'decisionId': None, 'message': 'An already accepted tradeoff.',
         'evidencePaths': ['/sourceMessages/SOURCE_1', '/draft/exercises/1']},
        {'concernGroupId': 'CONCERN_HARD', 'basis': 'established_violation', 'action': 'repair',
         'decisionId': None, 'message': 'A hard requirement violation.',
         'evidencePaths': ['/sourceMessages/SOURCE_2', '/draft/exercises/2']},
    ]
    audit = {'review': {'findings': findings, 'requirementAssessments': {
        'SOURCE_0': {'findingIndexes': [0]}, 'SOURCE_1': {'findingIndexes': [1]},
        'SOURCE_2': {'findingIndexes': [2]}},
        'assessment': {'groups': [
            {'findingIndexes': [0], 'disposition': 'advisory', 'reason': 'Preference evidence.'},
            {'findingIndexes': [1], 'disposition': 'advisory', 'reason': 'Already adjudicated.'},
            {'findingIndexes': [2], 'disposition': 'repair', 'reason': 'Hard requirement.'}]}}}
    requirements = {'requirementAccounting': [
        {'sourceReferences': ['SOURCE_0'], 'priority': 'preference', 'instruction': 'Favor similar durations.'},
        {'sourceReferences': ['SOURCE_1'], 'priority': 'preference', 'instruction': 'Favor extra variety.'},
        {'sourceReferences': ['SOURCE_2'], 'priority': 'mandatory', 'instruction': 'Keep the schedule.'}]}
    checklist = {'acceptedSoftTradeoffs': {'CONCERN_ACCEPTED': {'finding': findings[1]}}}

    eligible = preference_comparison_concerns(audit, requirements, review_checklist=checklist)
    assert [item['concernGroupId'] for item in eligible] == ['CONCERN_PREF']
    assert eligible[0]['preferenceRequirements'][0]['instruction'] == 'Favor similar durations.'
    assert preference_comparison_concerns(audit, requirements, ['CONCERN_PREF'],
        review_checklist=checklist) == eligible
    with pytest.raises(ValueError, match='not an unresolved, source-backed preference'):
        preference_comparison_concerns(audit, requirements, ['CONCERN_HARD'], review_checklist=checklist)


def test_preference_comparison_tool_selector_is_optional_and_explicit():
    parameters = PROPOSE_WORKOUT_ALTERNATIVES_TOOL['function']['parameters']
    assert 'comparisonConcernIds' not in parameters.get('required', [])
    assert parameters['properties']['comparisonConcernIds']['uniqueItems'] is True


def test_alternative_question_gate_only_exposes_the_latest_validated_proposal():
    from test_workout_generator_conflict_resolution import _alternative_case
    from workout_generator_pkg.conflict_resolution import render_alternative_preview

    _, _, result = _alternative_case()
    proposal = result['proposals'][0]
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'proposal', 'function': {
            'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'proposal', 'content': json.dumps(result)},
        {'role': 'assistant', 'content': render_alternative_preview(proposal),
         'canonicalAlternativePreview': proposal['proposalId']},
    ]

    question = pending_question(messages)
    assert question['kind'] == 'alternative'
    assert answer_question(question, '1') == 'APPROVE ALTERNATIVE ' + proposal['proposalId']

    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'new-diagnosis', 'function': {
            'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'new-diagnosis', 'content': json.dumps({
            'outcome': 'unresolved', 'proposals': []})},
    ])
    assert pending_question(messages) is None


@pytest.mark.parametrize('kind', ['requirements', 'generation'])
@pytest.mark.parametrize('reply', ['1', '2', 'no', 'cancel'])
def test_approval_survives_explanations_but_not_approval_or_decline(kind, reply):
    from test_workout_generator_planning_tools import planning_case, requirement_messages, approved_messages
    from workout_generator_pkg.planning_tools import audit_workout_plan
    equipment, _, stored, draft = planning_case()
    if kind == 'generation':
        result = audit_workout_plan(draft, equipment, requirement_messages(stored))
        messages = approved_messages(stored, result)[:-1]
    else:
        messages = requirement_messages(stored)[:-1]
    question = pending_question(messages)
    messages.extend([{'role': 'user', 'content': 'What does RIR mean?'},
                     {'role': 'assistant', 'content': 'RIR means reps in reserve.'}])
    assert pending_question(messages) == question
    messages.extend([{'role': 'user', 'content': answer_question(question, reply),
        'userInteraction': {'question': question, 'input': reply}},
        {'role': 'assistant', 'content': 'Understood.'}])
    assert pending_question(json.loads(json.dumps(messages))) is None


def test_generation_confirmation_names_unproven_distribution_without_other_limitations():
    from test_workout_generator_planning_tools import planning_case, requirement_messages, approved_messages
    from workout_generator_pkg.generation_audit import render_optimization_disclosure
    from workout_generator_pkg.planning_tools import audit_workout_plan

    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    execution = {'approvedPriorities': [
        {'priority': 'distribution', 'owner': 'joint_solver', 'status': 'unproven'},
    ]}
    result['automaticAllocation'] = {'priorityExecution': execution}
    result['preview'] += '\n\n' + render_optimization_disclosure(execution)
    question = pending_question(approved_messages(stored, result)[:-1])

    assert 'bounded search did not establish this priority' in question['question']
    assert 'not proof that improvement is impossible' in question['question']
    assert 'A better menu or placement has not been ruled out' in question['question']
    assert question['options'][0] == 'Accept the disclosed priority limitations and generate'

    placement_disclosure = render_optimization_disclosure({**execution, 'structuralConcentration': {
        'rolePlacement': {'status': 'feasible', 'profiles': [
            {'roles': ['abs', 'core'], 'peakSurplusPerOccurrence': 2},
        ]},
        'verifiedDemandUnion': {'optimizationStatus': 'unavailable_evidence'},
    }})
    assert 'preserves weekly exercise-recipe doses and exact target counts' in placement_disclosure
    assert 'does not add volume to make inclusion-only roles appear balanced' in placement_disclosure
    assert '2 working sets above its frequency-weighted per-occasion average' in placement_disclosure
    assert 'Verified-demand co-location: not optimized because verified exercise evidence is unavailable' in placement_disclosure


@pytest.mark.parametrize('status', ['optimal', 'feasible'])
def test_development_disclosure_reports_both_allocation_objectives(status):
    from workout_generator_pkg.generation_audit import (
        _development_summary_interpretation, render_optimization_disclosure)

    development = {'roleKeys': ['lateral_delt', 'vertical_pull'], 'status': status,
        'minimumWeeklyWorkingSets': 4,
        'combinedExposure': {'status': status, 'weeklyWorkingSets': 12}}
    disclosure = render_optimization_disclosure({'developmentEmphasis': development})

    assert 'then maximize combined exposure without reducing that minimum' in disclosure
    assert 'combined development-role exposure 12 role-set credits/week' in disclosure
    assert 'not a count of distinct physical sets' in disclosure
    assert 'does not establish adequate stimulus or personal suitability' in disclosure
    assert ('best minimum and combined exposure proven' in disclosure) == (status == 'optimal')
    assert 'compared combined development-role exposure' in _development_summary_interpretation(development)


def test_generation_confirmation_names_unoptimized_joint_priorities():
    from test_workout_generator_planning_tools import planning_case, requirement_messages, approved_messages
    from workout_generator_pkg.generation_audit import render_optimization_disclosure
    from workout_generator_pkg.planning_tools import audit_workout_plan

    equipment, _, stored, draft = planning_case()
    result = audit_workout_plan(draft, equipment, requirement_messages(stored))
    priority_execution = {'approvedPriorities': [
        {'priority': 'demand_distribution', 'owner': 'joint_solver', 'status': 'unavailable_evidence'},
        {'priority': 'duration_balance', 'owner': 'joint_solver', 'status': 'feasible'},
        {'priority': 'progression', 'owner': 'movement_selection_and_review', 'status': 'outside_joint_solver'},
    ], 'developmentEmphasis': {
        'owner': 'joint_solver', 'status': 'feasible',
        'roleKeys': ['lateral_delt', 'vertical_pull'],
        'comparison': 'maximize the minimum weekly raw working-set exposure across development roles',
        'unit': 'weekly_raw_working_sets', 'minimumWeeklyWorkingSets': 3,
        'sourceBudget': {'source': 'code_preparation_hard_feasible_set_allocation_plus_existing_source_sessions',
            'variableSourceWorkingSets': 22, 'fixedExistingWorkingSets': 4,
            'sourceBudgetWeeklyWorkingSets': 26, 'variableMenuCapWorkingSets': 22},
        'scope': 'Qualified executable recipes in the submitted finite menu and approved hard constraints.',
    }}
    result['automaticAllocation'] = {'priorityExecution': priority_execution}
    result['preview'] += '\n\n' + render_optimization_disclosure(
        priority_execution)
    messages = approved_messages(stored, result)[:-1]

    question = pending_question(messages)

    assert 'demand distribution: not optimized because verified exercise evidence is unavailable.' in question['question']
    assert 'duration balance: valid candidate found; the approved balance hierarchy is not proven optimal.' in question['question']
    assert 'Development allocation across lateral delt, vertical pull: maximize the minimum weekly raw working-set exposure.' in question['question']
    assert 'Source budget (code-prepared workout allocation plus existing sessions): 22 weekly variable-session sets, plus 4 fixed-session sets; 26 total source weekly sets.' in question['question']
    assert 'variable-menu cap is 22 weekly sets; fixed-session sets remain constant' in question['question']
    assert 'attained minimum 3 raw working sets/week' in question['question']
    assert 'does not establish adequate stimulus or personal suitability' in question['question']
    assert question['options'][0] == 'Accept the disclosed priority limitations and generate'
    assert answer_question(question, '1') == EXACT_GENERATION_CONFIRMATION

    budget_conflict = dict(priority_execution['developmentEmphasis'],
        status='source_budget_conflict_requires_review', minimumWeeklyWorkingSets=None)
    conflict_disclosure = render_optimization_disclosure({'developmentEmphasis': budget_conflict})
    assert 'uncapped diagnostic found hard feasibility' in conflict_disclosure
    assert 'not proof that hard requirements are infeasible' in conflict_disclosure
    assert 'no export candidate is available' in conflict_disclosure

    duration_disclosure = render_optimization_disclosure({'approvedPriorities': [
        {'priority': 'duration_balance', 'owner': 'joint_solver', 'status': 'optimal',
            'solverStage': {'goal': 'duration_balance', 'status': 'optimal', 'value': 42}},
    ]})
    assert 'Duration balance retains 42 seconds of excess beyond the approved duration-similarity band' in duration_disclosure
    assert 'the preferred tolerance remains unmet' in duration_disclosure


@pytest.mark.parametrize('omitted', [[], [0, 1]])
def test_shell_advertises_draft_lookup_only_for_omitted_sessions(monkeypatch, tmp_path, omitted):
    from test_workout_generator_planning_tools import planning_case
    equipment, _, _, _ = planning_case()
    path = tmp_path / 'library.json'
    path.write_text(json.dumps(equipment), encoding='utf-8')
    state = {'currentDraft': {'workouts': [{'detailsOmitted': index in omitted} for index in range(3)]}}
    monkeypatch.setattr(shell, '_messages_for_api', lambda *args: [
        {'role': 'system', 'content': 'Current planning state\n' + json.dumps(state)}])
    deps = make_shell_deps(tmp_path, chat_results=[('Ready.', None)], generation_results=[], generation_calls=[])
    capture = deps.chat_call_with_loading
    def chat(client, messages, tools, logger, **options):
        lookup = [tool for tool in tools if tool.get('function', {}).get('name') == 'get_workout_draft']
        assert bool(lookup) == bool(omitted)
        if lookup:
            assert lookup[0]['function']['parameters']['properties']['workoutReferences']['items']['enum'] == [
                f'WORKOUT_{index}' for index in omitted]
        return capture(client, messages, tools, logger, **options)
    deps.chat_call_with_loading = chat
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--exercise-library-file', str(path)])
    run_shell(monkeypatch, deps, ['Plan a workout', '/exit'])
    assert 'enum' not in shell.GET_WORKOUT_DRAFT_TOOL['function']['parameters']['properties']['workoutReferences']['items']
