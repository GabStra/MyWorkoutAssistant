import copy
import json

import pytest

from test_workout_generator_joint_prescriptions import prescription_case
from workout_generator_pkg.conflict_resolution import (
    CONFLICT_RESOLUTION_VERSION,
    _tighten_to_audited_volume,
    accept_workout_alternative,
    diagnose_conflict_and_propose,
    render_alternative_preview,
)
from workout_generator_pkg.user_interaction import answer_question, pending_question
from workout_generator_pkg.requirement_accounting import ACCOUNTING_SCHEMA, validate_accounting
from jsonschema import validate


def _review(workouts, requirements, receipt):
    from workout_generator_pkg.plan_review import REVIEW_VERSION
    return {'passed': True, 'reviewId': 'focused-test', 'version': REVIEW_VERSION,
        'preview': 'Full reviewed session and prescriptions.'}


def _alternative_inputs():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 16, 'maximum': 20}
    requirements['requirementAccounting'] = [{
        'instruction': 'Negotiable weekly chest minimum', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest'], 'priority': 'negotiable',
        'relaxationDirection': 'lower_minimum',
        'enforcement': 'constraint', 'reason': 'User authorized this target to be negotiable.'}]
    return equipment, requirements, sessions


def _alternative_case(allocation_conflict=None, *, expect_stale=False, messages=None):
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = _alternative_inputs()
    def solve(workouts, candidate_requirements, *args, **kwargs):
        minimum = candidate_requirements['auditTargets']['weeklyEffectiveSets']['chest']['minimum']
        if minimum > 15:
            return {'feasible': False, 'status': 'infeasible', 'problemFingerprint': 'fixture-conflict'}
        return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
            'audit': {'errors': [], 'weeklyVolume': {'chest': {'effective': 15}}, 'workouts': []}}

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(joint_planning, 'solve_prescribed_week', solve)
        result = diagnose_conflict_and_propose(requirements_id='REQ_TEST', base_draft_id='DRAFT_TEST',
            workouts=sessions, requirements=requirements, equipment=equipment, restriction_policy=None,
            review_candidate=_review, max_solver_attempts=8,
            allocation_conflict=allocation_conflict, messages=messages)
    assert result['outcome'] == ('unresolved' if expect_stale else 'alternatives_ready'), result
    if not expect_stale:
        assert len(result['proposals']) == 1
    return equipment, requirements, result


def test_relaxed_volume_is_tightened_to_audited_output_and_reviewed():
    _, _, result = _alternative_case()
    proposal = result['proposals'][0]
    assert proposal['changes'] == [{
        'path': '/auditTargets/weeklyEffectiveSets/chest/minimum', 'from': 16, 'to': 15,
        'basis': 'audited candidate volume'}]
    assert proposal['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] == 15
    assert proposal['audit']['weeklyVolume']['chest']['effective'] == 15
    assert proposal['independentReview']['passed']
    assert proposal['shortfallsAgainstOriginalRequirements'] == [{
        'path': '/auditTargets/weeklyEffectiveSets/chest/minimum', 'required': 16,
        'actual': 15, 'shortfall': 1, 'unit': 'effective sets', 'priority': 'negotiable',
        'instruction': 'Negotiable weekly chest minimum', 'sourceReferences': ['SOURCE_0']}]
    preview = render_alternative_preview(proposal)
    assert 'Original requirements remain active until you approve this proposal.' in preview
    assert '15 vs 16 effective sets (shortfall 1)' in preview


def test_menu_scoped_proposal_binds_the_current_count_conflict():
    equipment, requirements, sessions = _alternative_inputs()
    from workout_generator_pkg.allocation import allocation_input_fingerprint
    input_fingerprint = allocation_input_fingerprint({'workouts': sessions}, 'REQ_TEST', equipment,
        history_fingerprint=None, resolved_decisions={}, allow_educated_load_guesses=True,
        requirements=requirements)
    conflict = {'status': 'infeasible', 'scope': 'count_allocation_for_current_draft',
        'requirementsId': 'REQ_TEST', 'baseDraftId': 'DRAFT_TEST',
        'conflictFingerprint': input_fingerprint, 'inputFingerprint': input_fingerprint,
        'libraryFingerprint': 'library-fp',
        'historyFingerprint': None, 'allowEducatedLoadGuesses': True,
        'resolvedDecisions': {}, 'conflictingTargets': ['chest', 'shoulders']}
    from workout_generator_pkg.planning_tools import library_fingerprint
    conflict['libraryFingerprint'] = library_fingerprint(equipment)
    _, _, result = _alternative_case(conflict)
    assert result['outcome'] == 'alternatives_ready', result
    assert result['allocationConflictFingerprint'] == input_fingerprint
    assert result['proposals'][0]['allocationConflictFingerprint'] == input_fingerprint


def test_stale_count_conflict_cannot_start_tradeoff_search():
    equipment, _, _ = prescription_case()
    conflict = {'status': 'infeasible', 'scope': 'count_allocation_for_current_draft',
        'requirementsId': 'REQ_TEST', 'baseDraftId': 'DRAFT_TEST',
        'conflictFingerprint': 'count-conflict-fp', 'libraryFingerprint': 'stale-library',
        'historyFingerprint': None, 'allowEducatedLoadGuesses': True,
        'resolvedDecisions': {}}
    _, _, result = _alternative_case(conflict, expect_stale=True)
    assert result['outcome'] == 'unresolved'
    assert 'stale or does not match' in result['reason']


def test_unneeded_temporary_relaxations_are_restored_to_approved_values():
    _, original, _ = prescription_case()
    original['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 10, 'maximum': 20}
    original['auditTargets']['maximumSessionSeconds'] = 1000
    temporary = copy.deepcopy(original)
    temporary['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 100}
    temporary['auditTargets']['maximumSessionSeconds'] = None
    receipt = {'audit': {'weeklyVolume': {'chest': {'effective': 15}},
        'workouts': [{'estimatedSeconds': 900}]}}
    paths = [
        '/auditTargets/weeklyEffectiveSets/chest/minimum',
        '/auditTargets/weeklyEffectiveSets/chest/maximum',
        '/auditTargets/maximumSessionSeconds',
    ]
    tightened, changes = _tighten_to_audited_volume(temporary, paths, receipt, original)
    assert tightened == original
    assert changes == []


def test_time_cap_is_removed_then_tightened_to_audited_duration():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 500
    requirements['requirementAccounting'] = [{
        'instruction': 'Negotiable session cap', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/maximumSessionSeconds'], 'priority': 'negotiable',
        'relaxationDirection': 'increase_duration', 'enforcement': 'constraint',
        'reason': 'User authorized this duration target to be negotiable.'}]
    result = diagnose_conflict_and_propose(requirements_id='REQ_TIME', base_draft_id='DRAFT_TIME',
        workouts=sessions, requirements=requirements, equipment=equipment, restriction_policy=None,
        review_candidate=_review, max_solver_attempts=8)
    assert result['outcome'] == 'alternatives_ready', result
    proposal = result['proposals'][0]
    actual = max(row['estimatedSeconds'] for row in proposal['audit']['workouts'])
    assert actual > 500
    assert proposal['requirements']['auditTargets']['maximumSessionSeconds'] == actual


def test_upper_volume_cap_is_raised_then_tightened_to_audited_output():
    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 0, 'maximum': 10}
    requirements['executionRules'] = [{'kind': 'workSets', 'coverageKey': None,
                                      'minimumSets': 5, 'maximumSets': 5}]
    for day in sessions:
        day['exercises'][0]['allocationBounds'] = {'minimum': 1, 'maximum': 1}
    requirements['requirementAccounting'] = [{
        'instruction': 'Negotiable weekly chest upper bound', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest/maximum'],
        'priority': 'negotiable', 'relaxationDirection': 'raise_maximum', 'enforcement': 'constraint',
        'reason': 'User authorized this upper volume target to be negotiable.'}]
    result = diagnose_conflict_and_propose(requirements_id='REQ_UPPER', base_draft_id='DRAFT_UPPER',
        workouts=sessions, requirements=requirements, equipment=equipment, restriction_policy=None,
        review_candidate=_review, max_solver_attempts=8)
    assert result['outcome'] == 'alternatives_ready', result
    proposal = result['proposals'][0]
    actual = proposal['audit']['weeklyVolume']['chest']['effective']
    assert actual > 10
    assert proposal['changes'] == [{
        'path': '/auditTargets/weeklyEffectiveSets/chest/maximum', 'from': 10,
        'to': actual, 'basis': 'audited candidate volume'}]
    assert proposal['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['maximum'] == actual


def test_conflict_diagnosis_has_no_elapsed_deadline(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = prescription_case()
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *args, **kwargs: {
        'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
        'audit': {'errors': []}})
    result = diagnose_conflict_and_propose(requirements_id='REQ_NO_DEADLINE',
        base_draft_id='DRAFT_NO_DEADLINE', workouts=sessions, requirements=requirements,
        equipment=equipment, restriction_policy=None, review_candidate=_review)
    assert result['outcome'] == 'verified_feasible'
    assert 'diagnosisDeadlineUTC' not in result


def test_provider_review_timeout_is_unresolved_not_feasible_or_conflict(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = prescription_case()
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *args, **kwargs: {
        'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
        'audit': {'errors': [], 'workouts': []}})

    def timed_out_review(*args):
        raise TimeoutError('provider review request timed out')

    result = diagnose_conflict_and_propose(requirements_id='REQ_PROVIDER_TIMEOUT',
        base_draft_id='DRAFT_PROVIDER_TIMEOUT', workouts=sessions, requirements=requirements,
        equipment=equipment, restriction_policy=None, review_candidate=timed_out_review)

    assert result['outcome'] == 'unresolved'


def test_second_alternative_review_timeout_preserves_first_validated_proposal(monkeypatch):
    from workout_generator_pkg import cancellation, joint_planning
    from workout_generator_pkg.plan_review import REVIEW_VERSION

    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 16, 'maximum': 20}
    requirements['auditTargets']['maximumSessionSeconds'] = 500
    requirements['requirementAccounting'] = [
        {'instruction': 'Negotiable weekly chest minimum', 'sourceReferences': ['SOURCE_0'],
         'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest'], 'priority': 'negotiable',
         'relaxationDirection': 'lower_minimum', 'enforcement': 'constraint',
         'reason': 'User authorized lowering this target.'},
        {'instruction': 'Negotiable session duration', 'sourceReferences': ['SOURCE_1'],
         'requirementPaths': ['/auditTargets/maximumSessionSeconds'], 'priority': 'negotiable',
         'relaxationDirection': 'increase_duration', 'enforcement': 'constraint',
         'reason': 'User authorized increasing this target.'},
    ]

    def solve(workouts, candidate_requirements, *args, **kwargs):
        targets = candidate_requirements['auditTargets']
        if targets['weeklyEffectiveSets']['chest']['minimum'] >= 16 and targets['maximumSessionSeconds'] == 500:
            return {'feasible': False, 'status': 'infeasible', 'problemFingerprint': 'fixture-conflict'}
        return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
            'audit': {'errors': [], 'weeklyVolume': {'chest': {'effective': 15}},
                'workouts': [{'estimatedSeconds': 600}]}}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    calls = 0

    def review_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError('second candidate review timed out')
        return {'passed': True, 'preview': 'Complete reviewed proposal.',
            'review': {'version': REVIEW_VERSION}}

    monkeypatch.setattr(cancellation, 'run_cancellable', review_call)
    result = diagnose_conflict_and_propose(requirements_id='REQ_TIMEOUT_REVIEW',
        base_draft_id='DRAFT_TIMEOUT_REVIEW', workouts=sessions, requirements=requirements,
        equipment=equipment, restriction_policy=None, review_candidate=_review, max_solver_attempts=8)

    assert result['outcome'] == 'alternatives_ready', result
    assert len(result['proposals']) == 1
    assert result['proposals'][0]['independentReview']['passed'] is True
    assert result['searchComplete'] is False
    assert 'independent_review' in result['unexploredTradeoffAxes']
    assert result['attempts'][-1]['review'] == 'timeout'


def test_matching_infeasible_receipt_skips_repeating_original_joint_solve(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 500
    requirements['requirementAccounting'] = [{
        'instruction': 'Negotiable session cap', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/maximumSessionSeconds'], 'priority': 'negotiable',
        'relaxationDirection': 'increase_duration', 'enforcement': 'constraint',
        'reason': 'User authorized this duration target to be negotiable.'}]
    fingerprint = joint_planning.joint_problem_fingerprint(
        sessions, requirements, equipment, None, [], restriction_policy=None,
        existing=None, allow_educated_load_guesses=True)
    existing = {'status': 'infeasible', 'problemFingerprint': fingerprint,
        'consideredConstraints': ['session duration']}
    real_solve = joint_planning.solve_prescribed_week
    solver_requirements = []

    def track_solve(workouts, candidate_requirements, *args, **kwargs):
        solver_requirements.append(copy.deepcopy(candidate_requirements))
        return real_solve(workouts, candidate_requirements, *args, **kwargs)

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', track_solve)
    result = diagnose_conflict_and_propose(requirements_id='REQ_CACHE', base_draft_id='DRAFT_CACHE',
        workouts=sessions, requirements=requirements, equipment=equipment, restriction_policy=None,
        review_candidate=_review, existing_conflict=existing, max_solver_attempts=8)
    assert result['attempts'][0] == {
        'scenario': 'approved_requirements', 'status': 'infeasible', 'reused': True}
    assert solver_requirements
    assert all(candidate != requirements for candidate in solver_requirements)


def test_current_required_coverage_failure_stops_numeric_relaxation(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 500
    requirements['requirementAccounting'] = [{
        'instruction': 'Negotiable session cap', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/maximumSessionSeconds'], 'priority': 'negotiable',
        'relaxationDirection': 'increase_duration', 'enforcement': 'constraint',
        'reason': 'User authorized this duration target to be negotiable.'}]
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-current', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-current', 'content': json.dumps({
            'requirementsId': 'REQ_MENU', 'currentDraftId': 'DRAFT_MENU', 'passed': False,
            'submittedDraft': {'workouts': sessions},
            'errors': [{'code': 'required_coverage_missing', 'coverageKey': 'horizontal_pull',
                        'path': '/workouts'}]})}]

    def unexpected_solve(*args, **kwargs):
        raise AssertionError('Numeric relaxation cannot repair missing required coverage.')

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', unexpected_solve)
    result = diagnose_conflict_and_propose(requirements_id='REQ_MENU', base_draft_id='DRAFT_MENU',
        workouts=sessions, requirements=requirements, equipment=equipment, restriction_policy=None,
        review_candidate=_review, messages=messages)
    assert result['outcome'] == 'unresolved'
    assert result['nextStep'] == 'expand_candidate_menu'
    assert result['blockerCoverageKeys'] == ['horizontal_pull']

    current = copy.deepcopy(messages)
    current.append({'role': 'assistant', 'tool_calls': [{'id': 'audit-valid', 'type': 'function',
        'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]})
    current.append({'role': 'tool', 'tool_call_id': 'audit-valid', 'content': json.dumps({
        'requirementsId': 'REQ_MENU', 'currentDraftId': 'DRAFT_MENU', 'passed': True,
        'submittedDraft': {'workouts': sessions}, 'errors': []})})
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', lambda *args, **kwargs: {
        'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions), 'audit': {'errors': []}})
    cleared = diagnose_conflict_and_propose(requirements_id='REQ_MENU', base_draft_id='DRAFT_MENU',
        workouts=sessions, requirements=requirements, equipment=equipment, restriction_policy=None,
        review_candidate=_review, messages=current)
    assert cleared['outcome'] == 'verified_feasible'


def test_validated_menu_scoped_tradeoff_is_available_without_claiming_global_best():
    from workout_generator_pkg import joint_planning
    from workout_generator_pkg.planning_tools import library_fingerprint

    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['maximumSessionSeconds'] = 500
    requirements['requirementAccounting'] = [{
        'instruction': 'Negotiable session cap', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/maximumSessionSeconds'], 'priority': 'negotiable',
        'relaxationDirection': 'increase_duration', 'enforcement': 'constraint',
        'reason': 'User authorized this target to be negotiable.'}]
    fingerprint = joint_planning.joint_problem_fingerprint(
        sessions, requirements, equipment, None, [], restriction_policy=None,
        existing=None, allow_educated_load_guesses=True)
    infeasible = {'status': 'infeasible', 'problemFingerprint': fingerprint}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-current', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-current', 'content': json.dumps({
            'requirementsId': 'REQ_NARROW_MENU', 'currentDraftId': 'DRAFT_NARROW_MENU',
            'passed': False, 'submittedDraft': {'workouts': sessions},
            'libraryFingerprint': library_fingerprint(equipment), 'historyFingerprint': None,
            'resolvedDecisions': {}, 'coordinatedJointPlanning': infeasible, 'errors': []})},
    ]

    result = diagnose_conflict_and_propose(requirements_id='REQ_NARROW_MENU',
        base_draft_id='DRAFT_NARROW_MENU', workouts=sessions, requirements=requirements,
        equipment=equipment, restriction_policy=None, review_candidate=_review,
        messages=messages, existing_conflict=infeasible)

    assert result['outcome'] == 'alternatives_ready', result
    assert 'Structural alternatives remain unresolved' in result['structuralSearchStatus']
    assert result['proposals'][0]['searchScope'] == 'the supplied exercise menu'
    assert 'No global optimum or impossibility' in result['proposals'][0]['claim']


def test_source_rank_requires_supported_negotiable_numeric_constraint():
    _, requirements, _ = prescription_case()
    entry = {'instruction': 'Prioritize shorter sessions over volume.', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/maximumSessionSeconds'], 'priority': 'negotiable',
        'relaxationDirection': 'increase_duration', 'relaxationRank': 2,
        'enforcement': 'constraint', 'reason': 'The user explicitly ordered this compromise.'}
    requirements['auditTargets']['maximumSessionSeconds'] = 600
    requirements['requirementAccounting'] = [entry]
    sources = {'SOURCE_0': {'role': 'user'}}
    validate([entry], ACCOUNTING_SCHEMA)
    validate_accounting(requirements, sources)

    for mutate, message in [
        (lambda row: row.update(relaxationRank=0), 'positive integer'),
        (lambda row: row.update(priority='preference'), 'negotiable'),
        (lambda row: row.update(relaxationDirection='lower_minimum'), 'supported numeric'),
    ]:
        invalid = copy.deepcopy(requirements)
        mutate(invalid['requirementAccounting'][0])
        with pytest.raises(ValueError, match=message):
            validate_accounting(invalid, sources)


def test_changing_explicit_relaxation_rank_invalidates_approval_inheritance():
    from workout_generator_pkg.planning_tools import _accounting_refresh_preserves_approved_requirements

    entry = {'instruction': 'Time can yield before volume.', 'requirementPaths': ['/auditTargets/maximumSessionSeconds'],
        'priority': 'negotiable', 'enforcement': 'constraint', 'relaxationDirection': 'increase_duration',
        'relaxationRank': 1}
    base = {'requirements': {'requirementAccounting': [entry]}, 'sourceMessages': [],
        'resolvedDecisions': {}, 'supportedMuscleTargets': [], 'restrictionPolicy': None}
    current = copy.deepcopy(base)
    current['requirements']['requirementAccounting'][0]['relaxationRank'] = 2
    assert not _accounting_refresh_preserves_approved_requirements(base, current)


def test_ranked_tradeoffs_advance_only_after_lower_rank_is_proven_infeasible(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 16, 'maximum': 20}
    requirements['auditTargets']['maximumSessionSeconds'] = 400
    requirements['requirementAccounting'] = [
        {'instruction': 'Volume compromise first', 'sourceReferences': ['SOURCE_0'],
         'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest'], 'priority': 'negotiable',
         'relaxationDirection': 'lower_minimum', 'relaxationRank': 1,
         'enforcement': 'constraint', 'reason': 'Explicit rank one.'},
        {'instruction': 'Longer sessions second', 'sourceReferences': ['SOURCE_0'],
         'requirementPaths': ['/auditTargets/maximumSessionSeconds'], 'priority': 'negotiable',
         'relaxationDirection': 'increase_duration', 'relaxationRank': 2,
         'enforcement': 'constraint', 'reason': 'Explicit rank two.'},
    ]
    tried = []

    def solve(workouts, candidate_requirements, *args, **kwargs):
        tried.append(copy.deepcopy(candidate_requirements))
        if candidate_requirements == requirements:
            return {'feasible': False, 'status': 'infeasible'}
        chest_minimum = candidate_requirements['auditTargets']['weeklyEffectiveSets']['chest']['minimum']
        if chest_minimum == 0 and candidate_requirements['auditTargets']['maximumSessionSeconds'] == 400:
            assert candidate_requirements['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] == 0
            return {'feasible': False, 'status': 'infeasible'}
        if chest_minimum == 15 and candidate_requirements['auditTargets']['maximumSessionSeconds'] == 700:
            return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
                'audit': {'errors': [], 'weeklyVolume': {'chest': {'effective': 15}},
                          'workouts': [{'estimatedSeconds': 700}]}}
        # Rank two alone is insufficient; rank two is admitted only cumulatively
        # with the already-proven-infeasible rank-one relaxation.
        assert chest_minimum == 0
        assert candidate_requirements['auditTargets']['maximumSessionSeconds'] is None
        return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
            'audit': {'errors': [], 'weeklyVolume': {'chest': {'effective': 15}},
                      'workouts': [{'estimatedSeconds': 700}]}}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    result = diagnose_conflict_and_propose(requirements_id='REQ_RANKED', base_draft_id='DRAFT_RANKED',
        workouts=sessions, requirements=requirements, equipment=equipment, restriction_policy=None,
        review_candidate=_review)
    assert result['outcome'] == 'alternatives_ready', result
    labels = [attempt['scenario'] for attempt in result['attempts']]
    assert labels.index('relax:rank:1') < labels.index('relax:rank:2')
    assert result['proposals'][0]['relaxationRanks'] == {
        '/auditTargets/weeklyEffectiveSets/chest/minimum': 1,
        '/auditTargets/maximumSessionSeconds': 2,
    }
    assert CONFLICT_RESOLUTION_VERSION == 4


def test_feasible_lower_rank_holds_higher_rank_fixed(monkeypatch):
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = prescription_case()
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 16, 'maximum': 20}
    requirements['auditTargets']['maximumSessionSeconds'] = 400
    requirements['requirementAccounting'] = [
        {'instruction': 'Volume first', 'sourceReferences': ['SOURCE_0'],
         'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest'], 'priority': 'negotiable',
         'relaxationDirection': 'lower_minimum', 'relaxationRank': 1,
         'enforcement': 'constraint', 'reason': 'Rank one.'},
        {'instruction': 'Time second', 'sourceReferences': ['SOURCE_0'],
         'requirementPaths': ['/auditTargets/maximumSessionSeconds'], 'priority': 'negotiable',
         'relaxationDirection': 'increase_duration', 'relaxationRank': 2,
         'enforcement': 'constraint', 'reason': 'Rank two.'},
    ]
    tried = []

    def solve(workouts, candidate_requirements, *args, **kwargs):
        tried.append(copy.deepcopy(candidate_requirements))
        if candidate_requirements == requirements:
            return {'feasible': False, 'status': 'infeasible'}
        return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
            'audit': {'errors': [], 'weeklyVolume': {'chest': {'effective': 15}},
                      'workouts': []}}

    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    result = diagnose_conflict_and_propose(requirements_id='REQ_RANK_HOLD', base_draft_id='DRAFT_RANK_HOLD',
        workouts=sessions, requirements=requirements, equipment=equipment, restriction_policy=None,
        review_candidate=_review)
    assert result['outcome'] == 'alternatives_ready', result
    assert 'relax:rank:1' in [attempt['scenario'] for attempt in result['attempts']]
    assert 'relax:rank:2' not in [attempt['scenario'] for attempt in result['attempts']]
    assert len(tried) == 3  # original, rank-one candidate, then audited-output tightening
    assert result['searchComplete'] is False
    assert result['unexploredTradeoffAxes'] == ['relax:rank:2']


def test_alternative_requires_latest_draft_display_and_exact_approval():
    equipment, requirements, result = _alternative_case()
    proposal = result['proposals'][0]
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-1', 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-1', 'content': json.dumps({'currentDraftId': 'DRAFT_TEST', 'draftId': 'DRAFT_TEST'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'proposal-1', 'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'proposal-1', 'content': json.dumps(result)},
        {'role': 'assistant', 'content': render_alternative_preview(proposal),
         'canonicalAlternativePreview': proposal['proposalId']},
    ]
    arguments = {'proposal_id': proposal['proposalId'], 'proposal_result': result, 'messages': messages,
        'current_requirements': {'requirementsId': 'REQ_TEST', 'requirements': requirements}, 'equipment': equipment}
    with pytest.raises(ValueError, match='Explicitly approve'):
        accept_workout_alternative(**arguments)
    question = pending_question(messages)
    assert answer_question(question, '1') == 'APPROVE ALTERNATIVE ' + proposal['proposalId']
    assert answer_question(question, '2').startswith('Keep the current requirements')
    declined = copy.deepcopy(messages)
    declined.append({'role': 'user', 'content': 'Keep the current requirements.',
        'userInteraction': {'input': '2', 'question': question}})
    assert pending_question(declined) is None
    with pytest.raises(ValueError, match='Explicitly approve'):
        accept_workout_alternative(**{**arguments, 'messages': declined})
    changed = copy.deepcopy(messages)
    changed.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-2', 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-2', 'content': json.dumps({'currentDraftId': 'DRAFT_CHANGED', 'draftId': 'DRAFT_CHANGED'})},
        {'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']},
    ])
    with pytest.raises(ValueError, match='draft changed'):
        accept_workout_alternative(**{**arguments, 'messages': changed})
    tampered = copy.deepcopy(messages)
    tampered[-1]['content'] += '\nA different workout.'
    with pytest.raises(ValueError, match='Display the exact alternative'):
        accept_workout_alternative(**{**arguments, 'messages': tampered + [
            {'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']}]})
    accepted = accept_workout_alternative(**{**arguments,
        'messages': messages + [{'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']}]})
    assert accepted['supersedesRequirementsId'] == 'REQ_TEST'
    assert accepted['approvedAlternativeId'] == proposal['proposalId']
    revoked = messages + [
        {'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']},
        {'role': 'user', 'content': 'Keep the current requirements; do not accept an alternative.'},
    ]
    with pytest.raises(ValueError, match='Explicitly approve'):
        accept_workout_alternative(**{**arguments, 'messages': revoked})
    continued = messages + [
        {'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']},
        {'role': 'user', 'content': '/continue'},
    ]
    continued_result = accept_workout_alternative(**{**arguments, 'messages': continued})
    assert continued_result['approvedAlternativeId'] == proposal['proposalId']


def test_program_guidance_is_reviewed_rendered_bound_and_approved_with_alternative():
    from workout_generator_pkg.conflict_resolution import _hash, _proposal_core

    equipment, requirements, sessions = _alternative_inputs()
    guidance = 'Use stable double progression and keep two reps in reserve.'
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-source', 'function': {
            'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-source', 'content': json.dumps({
            'requirementsId': 'REQ_TEST', 'currentDraftId': 'DRAFT_TEST', 'draftId': 'DRAFT_TEST',
            'passed': True, 'submittedDraft': {'requirementsId': 'REQ_TEST', 'name': 'Plan',
                'workouts': sessions, 'programGuidance': guidance}})},
    ]
    _, _, result = _alternative_case(messages=messages)
    proposal = result['proposals'][0]
    assert proposal['programGuidance'] == guidance
    assert guidance in render_alternative_preview(proposal)
    assert proposal['proposalId'] == 'ALT_' + _hash(_proposal_core(proposal))[:24]
    altered = copy.deepcopy(proposal)
    altered['programGuidance'] += ' Change the plan.'
    assert ('ALT_' + _hash(_proposal_core(altered))[:24]) != proposal['proposalId']

    stored_messages = copy.deepcopy(messages) + [
        {'role': 'assistant', 'tool_calls': [{'id': 'proposal', 'function': {
            'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'proposal', 'content': json.dumps(result)},
        {'role': 'assistant', 'content': render_alternative_preview(proposal),
            'canonicalAlternativePreview': proposal['proposalId']},
        {'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']},
    ]
    accepted = accept_workout_alternative(proposal_id=proposal['proposalId'], proposal_result=result,
        messages=stored_messages, current_requirements={'requirementsId': 'REQ_TEST',
            'requirements': requirements}, equipment=equipment)
    assert accepted['programGuidance'] == guidance


def test_repaired_alternative_acceptance_preserves_fixed_restrictions_and_opens_current_generation_gate(monkeypatch):
    from types import SimpleNamespace

    from workout_generator_pkg.constants import EXACT_GENERATION_CONFIRMATION
    from workout_generator_pkg.generation_audit import ASSUMPTIONS
    from workout_generator_pkg.interactive_shell import handle_function_call
    from workout_generator_pkg.plan_review import REQUIREMENTS_REVIEW_VERSION, _requirements_context, _hash
    from workout_generator_pkg.planning_tools import (REQUIREMENTS_VERSION, requirements_approved,
        set_workout_requirements)
    from workout_generator_pkg.restriction_policy import resolve_restrictions
    from workout_generator_pkg import joint_planning

    equipment, requirements, sessions = prescription_case()
    equipment['exerciseDefinitions'].append({**copy.deepcopy(equipment['exerciseDefinitions'][0]),
        'id': 'zzz_burpee', 'name': 'Burpee'})
    requirements['auditTargets']['weeklyEffectiveSets']['chest'] = {'minimum': 16, 'maximum': 20}
    requirements['exerciseRestrictions'] = {'excludeNameTerms': ['Burpee'], 'exceptNameTerms': []}
    requirements['requirementAccounting'] = [{
        'instruction': 'Negotiable weekly chest minimum', 'sourceReferences': ['SOURCE_0'],
        'requirementPaths': ['/auditTargets/weeklyEffectiveSets/chest'], 'priority': 'negotiable',
        'relaxationDirection': 'lower_minimum', 'enforcement': 'constraint',
        'reason': 'The user authorized reducing this minimum if needed.'}]
    source = {'role': 'user', 'content':
        'Plan three sessions with 16–20 weekly chest sets. Avoid burpees. I authorize reducing the chest minimum if needed.'}
    source_messages = [source]
    stored = set_workout_requirements(requirements, source_messages, equipment)
    policy = resolve_restrictions(requirements['exerciseRestrictions'], equipment)
    assert stored['restrictionPolicy'] == policy

    def add_source_review(candidate):
        reviewed = copy.deepcopy(candidate)
        reviewed['requirementsVersion'] = REQUIREMENTS_VERSION
        reviewed['sourceReview'] = {'version': REQUIREMENTS_REVIEW_VERSION,
            'inputHash': _hash(_requirements_context(reviewed)), 'passed': True, 'findings': [],
            'auditPolicy': copy.deepcopy(ASSUMPTIONS)}
        return reviewed

    stored = add_source_review(stored)
    def solve(workouts, candidate_requirements, *args, **kwargs):
        minimum = candidate_requirements['auditTargets']['weeklyEffectiveSets']['chest']['minimum']
        if minimum > 15:
            return {'feasible': False, 'status': 'infeasible', 'problemFingerprint': 'fixture-conflict'}
        return {'feasible': True, 'status': 'optimal', 'sessions': copy.deepcopy(sessions),
            'audit': {'errors': [], 'weeklyVolume': {'chest': {'effective': 15}}, 'workouts': []}}
    monkeypatch.setattr(joint_planning, 'solve_prescribed_week', solve)
    stored_messages = [
        source,
        {'role': 'assistant', 'tool_calls': [{'id': 'requirements', 'function': {'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'requirements', 'content': json.dumps(stored)},
        {'role': 'assistant', 'canonicalRequirementsPreview': stored['requirementsId'],
         'content': stored['requirementsPreview']},
        {'role': 'user', 'content': 'CONFIRM REQUIREMENTS'},
    ]
    diagnosis = diagnose_conflict_and_propose(requirements_id=stored['requirementsId'],
        base_draft_id='DRAFT_REPAIRED', workouts=sessions, requirements=stored['requirements'],
        equipment=equipment, restriction_policy=policy, review_candidate=_review, max_solver_attempts=8)
    assert diagnosis['outcome'] == 'alternatives_ready', diagnosis
    proposal = diagnosis['proposals'][0]
    assert proposal['requirements']['exerciseRestrictions'] == requirements['exerciseRestrictions']
    messages = stored_messages + [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'audit', 'content': json.dumps({'currentDraftId': 'DRAFT_REPAIRED',
            'draftId': 'DRAFT_REPAIRED'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'diagnosis', 'function': {'name': 'propose_workout_alternatives'}}]},
        {'role': 'tool', 'tool_call_id': 'diagnosis', 'content': json.dumps(diagnosis)},
        {'role': 'assistant', 'canonicalAlternativePreview': proposal['proposalId'],
         'content': render_alternative_preview(proposal)},
        {'role': 'assistant', 'tool_calls': [{'id': 'repair', 'function': {'name': 'repair_workout_alternative'}}]},
        {'role': 'tool', 'tool_call_id': 'repair', 'content': json.dumps({'passed': True,
            'outcome': 'alternatives_ready', 'repairStatus': 'repaired_and_reviewed', 'proposal': proposal})},
        {'role': 'assistant', 'canonicalAlternativePreview': proposal['proposalId'],
         'content': render_alternative_preview(proposal)},
        {'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']},
        {'role': 'assistant', 'tool_calls': [{'id': 'accept', 'function': {
            'name': 'accept_workout_alternative', 'arguments': json.dumps({'proposalId': proposal['proposalId']})}}]},
    ]

    def deterministic_source_review(_client, candidate, _messages, *_args, **_kwargs):
        reviewed = add_source_review(candidate)
        from workout_generator_pkg.planning_tools import render_requirements
        reviewed['requirementsPreview'] = render_requirements(reviewed['requirements'],
            reviewed.get('restrictionPolicy'), confirmation=True)
        reviewed['passed'] = True
        return reviewed

    monkeypatch.setattr('workout_generator_pkg.interactive_shell.review_requirements', deterministic_source_review)
    accepted_call = handle_function_call(None, messages, 'accept_workout_alternative',
        {'proposalId': proposal['proposalId']}, provided_equipment=equipment,
        deps=SimpleNamespace(execute_workout_generation=lambda *args, **kwargs: None))
    accepted = json.loads(accepted_call['result'])
    assert accepted['approvedAlternativeId'] == proposal['proposalId']
    assert accepted['requirements']['exerciseRestrictions'] == requirements['exerciseRestrictions']
    assert accepted['restrictionPolicy'] == policy

    messages.extend([
        {'role': 'tool', 'tool_call_id': 'accept', 'content': json.dumps(accepted)},
        {'role': 'assistant', 'canonicalRequirementsPreview': accepted['requirementsId'],
         'content': accepted['requirementsPreview']},
    ])
    assert requirements_approved(messages, accepted)
    from workout_generator_pkg.user_interaction import pending_question
    assert pending_question(messages) is None  # Alternative approval already approved this exact revision.

    changed_messages = copy.deepcopy(messages)
    changed = copy.deepcopy(accepted)
    changed['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] += 1
    changed['requirementsId'] = 'REQ_CHANGED_AFTER_ALTERNATIVE'
    from workout_generator_pkg.planning_tools import render_requirements
    changed['requirementsPreview'] = render_requirements(changed['requirements'], changed.get('restrictionPolicy'), confirmation=True)
    changed_messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'changed-requirements', 'function': {
            'name': 'set_workout_requirements'}}]},
        {'role': 'tool', 'tool_call_id': 'changed-requirements', 'content': json.dumps(changed)},
        {'role': 'assistant', 'canonicalRequirementsPreview': changed['requirementsId'],
         'content': changed['requirementsPreview']},
    ])
    assert not requirements_approved(changed_messages, changed)
    changed_question = pending_question(changed_messages)
    assert changed_question and changed_question['kind'] == 'requirements'

    current_draft = {'passed': True, 'requirementsId': accepted['requirementsId'],
        'draftId': 'DRAFT_CURRENT', 'preview': 'Current reviewed plan'}
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'current-audit', 'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'current-audit', 'content': json.dumps(current_draft)},
        {'role': 'assistant', 'canonicalDraftPreview': current_draft['draftId'],
         'content': current_draft['preview']},
    ])
    question = pending_question(messages)
    assert question and question['kind'] == 'generation' and question['reference'] == 'DRAFT_CURRENT'
    messages.append({'role': 'user', 'content': EXACT_GENERATION_CONFIRMATION})
    assert requirements_approved(messages, accepted)
    assert pending_question(messages) is None


def test_alternative_from_stale_diagnosis_cannot_be_approved():
    equipment, requirements, result = _alternative_case()
    proposal = result['proposals'][0]
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-1', 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-1', 'content': json.dumps({'currentDraftId': 'DRAFT_TEST', 'draftId': 'DRAFT_TEST'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'proposal-1', 'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'proposal-1', 'content': json.dumps({**result, 'diagnosisVersion': CONFLICT_RESOLUTION_VERSION - 1})},
        {'role': 'assistant', 'content': render_alternative_preview(proposal),
         'canonicalAlternativePreview': proposal['proposalId']},
        {'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']},
    ]
    with pytest.raises(ValueError, match='diagnosis is stale'):
        accept_workout_alternative(proposal_id=proposal['proposalId'], proposal_result=result, messages=messages,
            current_requirements={'requirementsId': 'REQ_TEST', 'requirements': requirements}, equipment=equipment)


def test_alternative_from_stale_independent_review_cannot_be_approved(monkeypatch):
    import workout_generator_pkg.plan_review as plan_review

    equipment, requirements, result = _alternative_case()
    proposal = result['proposals'][0]
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'audit-1', 'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'audit-1', 'content': json.dumps({'currentDraftId': 'DRAFT_TEST', 'draftId': 'DRAFT_TEST'})},
        {'role': 'assistant', 'tool_calls': [{'id': 'proposal-1', 'function': {'name': 'propose_workout_alternatives', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'proposal-1', 'content': json.dumps(result)},
        {'role': 'assistant', 'content': render_alternative_preview(proposal),
         'canonicalAlternativePreview': proposal['proposalId']},
        {'role': 'user', 'content': 'APPROVE ALTERNATIVE ' + proposal['proposalId']},
    ]
    monkeypatch.setattr(plan_review, 'REVIEW_VERSION', plan_review.REVIEW_VERSION + 1)
    with pytest.raises(ValueError, match='review is stale'):
        accept_workout_alternative(proposal_id=proposal['proposalId'], proposal_result=result, messages=messages,
            current_requirements={'requirementsId': 'REQ_TEST', 'requirements': requirements}, equipment=equipment)
