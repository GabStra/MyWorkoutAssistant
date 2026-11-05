import copy
import json

import pytest

from workout_generator_pkg import repair_execution as acceptance


def test_incumbent_definitions_enter_normal_preparation_only_under_the_same_authority(monkeypatch):
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment = {'exerciseDefinitions': [], 'equipments': [], 'accessoryEquipments': []}
    original = {'requirements': {'objectiveOrder': ['duration_economy']},
        'sourceMessages': [{'role': 'user', 'content': 'Keep my approved workout targets.'}],
        'restrictionPolicy': {}}
    source = {'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': 'history',
        'resolvedDecisions': {}, 'submittedDraft': {'workouts': [{'exercises': [
            {'definition_id': 'LIBRARY_1', 'numWorkSets': 3},
            {'definition_id': 'LIBRARY_0', 'numWorkSets': 2}]}]}}
    current = copy.deepcopy(original)
    messages = [{'role': 'system', 'incumbentPlan': {'pinned': 'receipt'}}]
    monkeypatch.setattr(acceptance, '_incumbent_source', lambda _reference: ([], source, original))
    monkeypatch.setattr('workout_generator_pkg.planning_tools._latest_result', lambda *_args: (0, current))
    assert acceptance.incumbent_candidate_references(messages, equipment, 'history') == ['LIBRARY_0', 'LIBRARY_1']
    for change in ('source', 'requirements', 'restrictions', 'decisions', 'library', 'history'):
        with monkeypatch.context() as scoped:
            changed_current, changed_source = copy.deepcopy(current), copy.deepcopy(source)
            if change == 'source':
                changed_current['sourceMessages'][0]['content'] = 'Use different movement priorities.'
            elif change == 'requirements':
                changed_current['requirements']['objectiveOrder'] = ['setup_economy']
            elif change == 'restrictions':
                changed_current['restrictionPolicy'] = {'excluded': ['exercise']}
            else:
                field = {'decisions': 'resolvedDecisions', 'library': 'libraryFingerprint',
                         'history': 'historyFingerprint'}[change]
                changed_source[field] = {'new': 'choice'} if change == 'decisions' else 'stale'
            scoped.setattr(acceptance, '_incumbent_source', lambda _reference: ([], changed_source, original))
            scoped.setattr('workout_generator_pkg.planning_tools._latest_result', lambda *_args: (0, changed_current))
            assert acceptance.incumbent_candidate_references(messages, equipment, 'history') == []
    assert acceptance.incumbent_candidate_references([], equipment, 'history') == []


@pytest.mark.parametrize('rejection', ['stale_hash', 'feedback', 'conflicting_receipt',
    'final_role_mismatch', 'occurrence_disagreement', 'different_authority'])
def test_incumbent_qualification_rejects_unproven_definition_evidence(monkeypatch, rejection):
    ref = 'LIBRARY_0'
    contract = {'definition_id': ref, 'satisfiesCoverage': ['horizontal_pull']}
    qualification = {'inputHashes': {ref: 'exact'}, 'contracts': [contract]}
    source_messages = [{'role': 'tool', 'content': json.dumps({'recipeQualification': qualification})}]
    source = {'submittedDraft': {'workouts': [{'exercises': [copy.deepcopy(contract), copy.deepcopy(contract)]}]}}
    feedback = {}
    if rejection == 'stale_hash':
        qualification['inputHashes'][ref] = 'old'
        source_messages[0]['content'] = json.dumps({'recipeQualification': qualification})
    elif rejection == 'feedback':
        feedback[ref] = [{'finding': 'Reconsider coverage.'}]
    elif rejection == 'conflicting_receipt':
        different = copy.deepcopy(qualification)
        different['contracts'][0]['satisfiesCoverage'] = []
        source_messages.append({'role': 'tool', 'content': json.dumps({'recipeQualification': different})})
    elif rejection == 'final_role_mismatch':
        for item in source['submittedDraft']['workouts'][0]['exercises']:
            item['satisfiesCoverage'] = []
    elif rejection == 'occurrence_disagreement':
        source['submittedDraft']['workouts'][0]['exercises'][1]['satisfiesCoverage'] = []
    monkeypatch.setattr(acceptance, '_incumbent_under_current_authority',
        lambda *_args: None if rejection == 'different_authority' else (source_messages, source))
    contracts, conflicts = acceptance.incumbent_recipe_contracts([], {}, None,
        {ref: 'exact'}, {'horizontal_pull'}, {ref: {}}, feedback)
    assert contracts == {}
    assert bool(conflicts) == (rejection == 'conflicting_receipt')


def test_incumbent_metadata_survives_switch_and_stays_out_of_model_messages(tmp_path):
    from workout_generator_pkg.conversation_meta import (
        load_conversation_meta, save_conversation_meta, save_incumbent_reference)
    from workout_generator_pkg.interactive_shell import _messages_for_api

    reference = {'messagesPath': 'saved/messages.json', 'draftId': 'DRAFT_A', 'receiptHash': 'hash'}
    save_conversation_meta('A', str(tmp_path))
    save_incumbent_reference(reference, str(tmp_path))
    save_conversation_meta('B', str(tmp_path))
    assert load_conversation_meta(str(tmp_path)) == {
        'active_conversation_id': 'B', 'incumbentPlan': reference}
    messages = [{'role': 'system', 'content': 'Application'}, {'role': 'user', 'content': 'Plan'}]
    acceptance.bind_incumbent_reference(messages, reference)
    assert messages[0]['incumbentPlan'] == reference
    assert all('incumbentPlan' not in message for message in _messages_for_api(messages))


def test_missing_pinned_incumbent_blocks_instead_of_silently_disappearing(tmp_path):
    messages = [{'role': 'system', 'content': '', 'incumbentPlan': {
        'messagesPath': str(tmp_path / 'missing.json'), 'draftId': 'A', 'receiptHash': 'hash'}}]
    result = {'passed': True, 'preview': 'reviewed candidate', 'planIndex': {}, 'errors': []}
    gated = acceptance.apply_incumbent_promotion_gate(result, messages, {})
    assert not gated['passed']
    assert gated['incumbentComparison']['reason'] == 'incumbent_revalidation_failed'
    assert 'preview' not in gated and 'planIndex' not in gated
    assert gated['userQuestion']['options']
    assert result['passed'] and result['preview'] == 'reviewed candidate'


def test_cli_selection_is_carried_into_fresh_conversations(tmp_path, monkeypatch):
    from test_workout_generator_conversation_sessions import make_shell_deps
    from workout_generator_pkg.interactive_shell import main
    from workout_generator_pkg.conversation_store import list_conversations, load_conversation_record

    reference = {'messagesPath': str(tmp_path / 'saved.json'), 'draftId': 'A', 'receiptHash': 'hash'}
    monkeypatch.setattr(acceptance, 'select_incumbent_conversation', lambda _path: reference)
    inputs = iter(['Hello', '/clear', 'Hello again', '/exit'])
    monkeypatch.setattr('builtins.input', lambda _prompt='': next(inputs))
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr('sys.argv', ['workout_generator.py', '--incumbent-conversation', reference['messagesPath']])
    deps = make_shell_deps(tmp_path, chat_results=[('Ready', None), ('Ready', None)],
        generation_results=[], generation_calls=[])
    main(deps=deps)
    conversations = list_conversations(str(tmp_path))
    assert len(conversations) == 2
    for saved in conversations:
        messages = load_conversation_record(saved['conversation_id'], str(tmp_path))['messages']
        assert messages[0]['incumbentPlan'] == reference


def test_successful_export_pins_the_saved_reviewed_receipt(tmp_path, monkeypatch):
    from test_workout_generator_conversation_sessions import make_shell_deps, run_shell
    from test_workout_generator_planning_tools import planning_case
    from workout_generator_pkg.conversation_meta import load_conversation_meta
    from workout_generator_pkg.conversation_store import save_conversation
    from workout_generator_pkg.domain_ops import reviewable_workout_artifact
    from workout_generator_pkg.planning_tools import build_draft_plan

    equipment, requirements, stored, draft = planning_case()
    plan = build_draft_plan(draft, equipment, requirements)
    snapshot = {'passed': True, 'draftId': 'DRAFT_A', 'requirementsId': stored['requirementsId'],
        'errors': [], 'audit': {'errors': []}, 'planIndex': plan, 'submittedDraft': draft,
        'review': {'assessment': {'groups': []},
                   'reviewedArtifact': reviewable_workout_artifact(plan, 'Reviewed guidance')}}
    messages = [{'role': 'system', 'content': 'Application'},
        {'role': 'assistant', 'tool_calls': [
            {'id': 'requirements', 'type': 'function',
             'function': {'name': 'set_workout_requirements', 'arguments': json.dumps(requirements)}},
            {'id': 'audit', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': json.dumps(draft)}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(stored)},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps(snapshot)}]
    save_conversation(messages, conversation_id='reviewed', script_dir=str(tmp_path), migrate=False)
    calls = []
    deps = make_shell_deps(tmp_path, chat_results=[], generation_results=[{
        'success': True, 'filepath': str(tmp_path / 'export.json')}], generation_calls=calls)
    run_shell(monkeypatch, deps, ['/resume-conversation reviewed', '/generate', '/exit'])
    reference = load_conversation_meta(str(tmp_path))['incumbentPlan']
    assert len(calls) == 1
    assert reference['draftId'] == snapshot['draftId']
    assert acceptance._incumbent_source(reference)[1] == snapshot


def test_export_guard_rechecks_comparison_even_if_candidate_is_marked_passing(monkeypatch):
    from workout_generator_pkg import plan_review
    from workout_generator_pkg.planning_tools import PlanningInputError

    monkeypatch.setattr(plan_review, '_require_review_receipt', lambda *_args: None)
    monkeypatch.setattr(acceptance, 'compare_incumbent_candidate', lambda *_args: {
        'decision': 'retain_baseline', 'reason': 'first_differing_approved_objective',
        'firstDifferingObjective': 'source_balance', 'comparisons': []})
    with pytest.raises(PlanningInputError, match='saved incumbent'):
        plan_review.require_current_review({'passed': True, 'errors': []}, [], {})


@pytest.mark.parametrize('decision,reason', [
    ('promote_candidate', 'first_differing_approved_objective'),
    ('retain_baseline', 'same_reviewed_source_artifact'),
    ('inapplicable', 'different_approved_requirements'),
    ('inapplicable', 'different_approved_decisions'),
])
def test_improvements_exact_incumbent_and_new_requirements_keep_existing_review_gates(monkeypatch, decision, reason):
    monkeypatch.setattr(acceptance, 'compare_incumbent_candidate', lambda *_args: {
        'decision': decision, 'reason': reason, 'comparisons': []})
    result = {'passed': True, 'errors': [], 'preview': 'reviewed preview', 'planIndex': {'current': True}}
    accepted = acceptance.apply_incumbent_promotion_gate(result, [], {})
    assert accepted['passed'] and accepted['preview'] == result['preview']
    assert accepted['planIndex'] == result['planIndex']
    assert 'userQuestion' not in accepted
    failed = {**result, 'passed': False, 'errors': [{'code': 'review_execution_failed'}]}
    assert acceptance.apply_incumbent_promotion_gate(failed, [], {}) is failed


def test_comparison_requirements_ignores_presentation_but_preserves_numbers_and_priority():
    from workout_generator_pkg.requirement_accounting import comparison_requirements

    source = {'objectiveOrder': ['duration_balance', 'source_balance'],
        'notes': 'Display notes', 'requiredCoverage': [
            {'key': 'abs', 'description': 'Abs', 'minimumWeeklySets': 9}, {'key': 'calves'}],
        'executionRules': [{'kind': 'workSets', 'maximumSets': 3},
            {'kind': 'supersetNoReconfiguration', 'confirmedIndependentPairs': [['A', 'B']]}]}
    reordered = copy.deepcopy(source)
    reordered['requiredCoverage'].reverse()
    reordered['executionRules'].reverse()
    reordered['notes'] = 'Other wording'
    reordered['executionRules'][0]['confirmedIndependentPairs'][0].reverse()
    assert comparison_requirements(source) == comparison_requirements(reordered)
    reordered['objectiveOrder'].reverse()
    assert comparison_requirements(source) != comparison_requirements(reordered)
    reordered['objectiveOrder'].reverse()
    reordered['requiredCoverage'][1]['minimumWeeklySets'] = 8
    assert comparison_requirements(source) != comparison_requirements(reordered)


def test_pinned_receipt_cannot_be_replaced_by_a_later_audit_or_edited_in_place(tmp_path, monkeypatch):
    from workout_generator_pkg.planning_tools import _fingerprint

    snapshot = {'draftId': 'A', 'requirementsId': 'REQ', 'passed': True}
    calls = [{'id': name, 'function': {'name': tool}} for name, tool in (
        ('requirements', 'set_workout_requirements'), ('audit', 'audit_workout_plan'))]
    messages = [{'role': 'assistant', 'tool_calls': calls},
        {'role': 'tool', 'tool_call_id': 'requirements',
         'content': json.dumps({'requirementsId': 'REQ', 'requirements': {'sessionsPerWeek': 1}})},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps(snapshot)}]
    path = tmp_path / 'messages.json'
    path.write_text(json.dumps(messages))
    reference = {'messagesPath': str(path), 'draftId': 'A', 'receiptHash': _fingerprint(snapshot)}
    monkeypatch.setattr(acceptance, 'reviewed_incumbent_reference', lambda *_args: reference)
    assert acceptance._incumbent_source(reference)[1] == snapshot
    messages.append({'role': 'tool', 'tool_call_id': 'later', 'content': json.dumps({'draftId': 'B'})})
    path.write_text(json.dumps(messages))
    assert acceptance._incumbent_source(reference)[1] == snapshot
    messages[2]['content'] = json.dumps({**snapshot, 'passed': False})
    path.write_text(json.dumps(messages))
    with pytest.raises(ValueError, match='missing or changed'):
        acceptance._incumbent_source(reference)


def test_historical_role_disagreement_cannot_be_used_to_claim_an_improvement(monkeypatch):
    from workout_generator_pkg import allocation, planning_tools, programming_guidelines

    requirements = {'requirements': {}, 'restrictionPolicy': {},
        'sourceMessages': [{'role': 'user', 'content': 'Same goals'}]}
    source = {'libraryFingerprint': 'LIB', 'historyFingerprint': None,
        'allowEducatedLoadGuesses': False, 'submittedDraft': {'workouts': [
            {'exercises': [{'definition_id': 'LIBRARY_0', 'satisfiesCoverage': ['horizontal_pull']}]}]}}
    candidate = copy.deepcopy(source)
    candidate['submittedDraft']['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['rear_delt']
    messages = [{'role': 'system', 'incumbentPlan': {'draftId': 'A'}}]
    monkeypatch.setattr(acceptance, '_incumbent_source', lambda _ref: ([], source, requirements))
    monkeypatch.setattr(planning_tools, '_latest_result', lambda *_args: (0, requirements))
    monkeypatch.setattr(planning_tools, 'library_fingerprint', lambda _equipment: 'LIB')
    monkeypatch.setattr(programming_guidelines, 'canonical_execution_order_draft', lambda draft, *_args: draft)
    monkeypatch.setattr(planning_tools, 'audit_workout_plan', lambda *_args: {
        'passed': True, 'submittedDraft': source['submittedDraft'], 'audit': {}})
    monkeypatch.setattr(allocation, '_joint_candidate_comparison_context', lambda *_args, **_kwargs: {
        'qualifiedRoleEvidence': {}})
    result = acceptance.compare_incumbent_candidate(candidate, messages, {})
    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'reviewed_role_evidence_conflicts'


@pytest.fixture
def decision_scope_case(monkeypatch):
    from workout_generator_pkg import planning_tools

    decision = {'topic': 'Pull selection', 'choice': 'Use the approved loadable pull.',
                'sourceReferences': ['SOURCE_0']}
    decisions = {'DECISION_0': decision}
    receipt = {'passed': True, 'decisionReview': {'passed': True}, 'decisions': decisions}
    messages = [{'role': 'system', 'incumbentPlan': {'draftId': 'A'}},
        {'role': 'assistant', 'tool_calls': [{'id': 'decision',
            'function': {'name': 'record_planning_decisions'}}]},
        {'role': 'tool', 'tool_call_id': 'decision', 'content': json.dumps(receipt)}]
    original = {'requirements': {'objectiveOrder': ['duration_economy']},
        'restrictionPolicy': {}, 'sourceMessages': [{'role': 'user', 'content': 'Approved goals'}]}
    current = copy.deepcopy(original)
    source = {'libraryFingerprint': 'LIB', 'historyFingerprint': None,
        'allowEducatedLoadGuesses': False, 'resolvedDecisions': {},
        'submittedDraft': {'workouts': []}}
    candidate = {**copy.deepcopy(source), 'resolvedDecisions': copy.deepcopy(decisions),
        'passed': True, 'errors': [], 'preview': 'Reviewed preview', 'planIndex': {}, 'audit': {}}
    source_messages = []
    monkeypatch.setattr(acceptance, '_incumbent_source',
        lambda _ref: (source_messages, source, original))
    monkeypatch.setattr(planning_tools, '_latest_result', lambda *_args: (0, current))
    monkeypatch.setattr(planning_tools, 'library_fingerprint', lambda _equipment: 'LIB')
    return messages, receipt, source_messages, source, current, candidate


@pytest.mark.parametrize('receipt_passed,review_passed', [(True, True), (False, True), (True, False)])
def test_only_independently_approved_decisions_start_a_new_comparison_scope(
        decision_scope_case, receipt_passed, review_passed):
    messages, receipt, _, _, _, candidate = decision_scope_case
    receipt.update(passed=receipt_passed, decisionReview={'passed': review_passed})
    receipt['decisions']['DECISION_9'] = {'choice': 'Superseded choice', 'supersededBy': 'DECISION_0'}
    messages[-1]['content'] = json.dumps(receipt)
    result = acceptance.apply_incumbent_promotion_gate(candidate, messages, {})
    approved = receipt_passed and review_passed
    assert result['passed'] is approved
    comparison = result['incumbentComparison']
    assert comparison['decision'] == ('inapplicable' if approved else 'incomparable')
    assert comparison['reason'] == ('different_approved_decisions' if approved else 'candidate_decisions_not_current')
    assert not comparison['comparisons'] and comparison['firstDifferingObjective'] is None
    if approved:
        assert result['preview'] == candidate['preview']
        assert 'userQuestion' not in result


@pytest.mark.parametrize('new_requirements', [False, True])
def test_candidate_matching_old_incumbent_cannot_hide_a_stale_decision_ledger(decision_scope_case, new_requirements):
    messages, _, _, _, current, candidate = decision_scope_case
    candidate['resolvedDecisions'] = {}
    if new_requirements:
        current['requirements']['objectiveOrder'] = ['setup_economy']
    result = acceptance.apply_incumbent_promotion_gate(candidate, messages, {})
    assert not result['passed']
    assert result['incumbentComparison']['reason'] == 'candidate_decisions_not_current'


@pytest.mark.parametrize('mismatch', ['source', 'restrictions', 'library', 'history',
    'calibration', 'current_history', 'source_decisions'])
def test_approved_decision_scope_change_does_not_hide_other_authority_failures(decision_scope_case, mismatch):
    messages, _, _, source, current, candidate = decision_scope_case
    if mismatch == 'source':
        current['sourceMessages'][0]['content'] = 'Other source'
    elif mismatch == 'restrictions':
        current['restrictionPolicy'] = {'excluded': ['LIBRARY_0']}
    elif mismatch == 'source_decisions':
        source['resolvedDecisions'] = {'DECISION_9': {'choice': 'Not independently approved'}}
    elif mismatch == 'current_history':
        source['historyFingerprint'] = candidate['historyFingerprint'] = 'missing-current-history'
    else:
        field = {'library': 'libraryFingerprint', 'history': 'historyFingerprint',
                 'calibration': 'allowEducatedLoadGuesses'}[mismatch]
        candidate[field] = True if mismatch == 'calibration' else 'different'
    result = acceptance.apply_incumbent_promotion_gate(candidate, messages, {})
    assert not result['passed']
    assert result['incumbentComparison']['decision'] == 'incomparable'
    assert result['incumbentComparison']['reason'] == (
        'current_history_required_for_incumbent_revalidation' if mismatch == 'current_history'
        else 'incumbent_decisions_not_current' if mismatch == 'source_decisions'
        else 'incumbent_authority_differs')


@pytest.mark.parametrize('ledger_change', ['none', 'candidate_acceptance', 'bookkeeping', 'null_supersedes'])
def test_same_approved_decision_scope_still_compares_and_blocks_regression(
        decision_scope_case, monkeypatch, ledger_change):
    from workout_generator_pkg import allocation, joint_planning, planning_tools, programming_guidelines

    messages, receipt, source_messages, source, _, candidate = decision_scope_case
    source['resolvedDecisions'] = copy.deepcopy(candidate['resolvedDecisions'])
    source_messages.extend(copy.deepcopy(messages[1:]))
    if ledger_change == 'candidate_acceptance':
        receipt['decisions']['DECISION_1'] = {
            'topic': 'Accept current review uncertainty', 'choice': 'Keep the current candidate.',
            'sourceReferences': ['SOURCE_0'], 'acceptedConcernGroupId': 'CONCERN_0',
            'acceptedCandidateScope': {'draftId': 'candidate'}}
    elif ledger_change == 'bookkeeping':
        receipt['decisions']['DECISION_0']['reason'] = 'Updated receipt rationale for the same approved choice.'
    elif ledger_change == 'null_supersedes':
        receipt['decisions']['DECISION_0']['supersedes'] = None
    candidate['resolvedDecisions'] = copy.deepcopy(receipt['decisions'])
    messages[-1]['content'] = json.dumps(receipt)
    monkeypatch.setattr(programming_guidelines, 'canonical_execution_order_draft', lambda draft, *_args: draft)
    monkeypatch.setattr(planning_tools, 'audit_workout_plan', lambda *_args: {
        'passed': True, 'submittedDraft': source['submittedDraft'], 'audit': {}})
    monkeypatch.setattr(allocation, '_joint_candidate_comparison_context', lambda *_args, **_kwargs: {
        'qualifiedRoleEvidence': {}})
    calls = []
    def compare(*args, **kwargs):
        calls.append(args)
        return {'decision': 'retain_baseline', 'reason': 'first_differing_approved_objective',
                'firstDifferingObjective': 'duration_economy', 'comparisons': []}
    monkeypatch.setattr(joint_planning, 'compare_audited_joint_candidates', compare)
    # Keep the exact-artifact exemption out of this deliberately regressing comparison.
    fingerprints = iter(['source', 'candidate'])
    monkeypatch.setattr(joint_planning, 'prescription_fingerprint', lambda _workouts: next(fingerprints))
    result = acceptance.apply_incumbent_promotion_gate(candidate, messages, {})
    assert len(calls) == 1
    assert not result['passed']
    assert result['incumbentComparison']['firstDifferingObjective'] == 'duration_economy'
