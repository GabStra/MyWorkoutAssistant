from workout_generator_pkg.plan_review import _context
from workout_generator_pkg.planner_context import (
    _compact_programming_selection_facts,
    _movement_selection_context,
)
from workout_generator_pkg.planning_tools import audit_workout_plan, library_fingerprint
from workout_generator_pkg.planner_context import _programming_selection_facts_from_receipt
from test_workout_generator_planning_tools import planning_case, requirement_messages


def _facts(unsupported, axial, eccentric):
    def item(value, source):
        return {'status': value, 'source': source}

    return {
        'unsupported_trunk': item(*unsupported),
        'axial_loading': item(*axial),
        'eccentric_emphasis': item(*eccentric),
    }


def test_selector_projects_only_sourced_library_demand_facts_and_marks_unknown_groups():
    first = _facts(('present', 'catalog: row entry'), ('absent', 'catalog: row entry'), ('unknown', None))
    second = _facts(('absent', 'catalog: press entry'), ('present', 'catalog: press entry'), ('unknown', None))
    state = {
        'requirements': {'objectiveOrder': ['demand_distribution']},
        'exerciseCandidates': {
            'LIBRARY_0': {'id': 'LIBRARY_0', 'name': 'Unsupported Trunk Row',
                'exerciseCategory': 'ROW', 'programmingDemandFacts': first},
            'LIBRARY_1': {'id': 'LIBRARY_1', 'name': 'Axially Loaded Press',
                'exerciseCategory': 'PRESS', 'programmingDemandFacts': second},
        },
    }

    _movement_selection_context(state)

    evidence = state['exerciseDemandEvidence']
    assert evidence['programmingDemandFacts'] == {'LIBRARY_0': first, 'LIBRARY_1': second}
    distribution = evidence['demandDistribution']
    assert set(distribution['groups']) == {'unsupported_trunk', 'axial_loading'}
    assert distribution['groups']['unsupported_trunk']['presentDefinitionIds'] == ['LIBRARY_0']
    assert distribution['groups']['axial_loading']['presentDefinitionIds'] == ['LIBRARY_1']
    assert distribution['unavailableGroups'] == {'eccentric_emphasis': ['LIBRARY_0', 'LIBRARY_1']}
    # Labels and exercise categories cannot supply missing programming metadata.
    assert first['eccentric_emphasis'] == {'status': 'unknown', 'source': None}


def test_selector_does_not_infer_demand_properties_from_names_or_categories():
    state = {'requirements': {'objectiveOrder': []}, 'exerciseCandidates': {
        'LIBRARY_0': {'id': 'LIBRARY_0', 'name': 'Unsupported Trunk Axial Eccentric Row',
            'exerciseCategory': 'ROW', 'muscleGroups': ['BACK_UPPER_BACK']}}}

    _movement_selection_context(state)

    facts = state['exerciseDemandEvidence']['programmingDemandFacts']['LIBRARY_0']
    assert set(facts) == {'unsupported_trunk', 'axial_loading', 'eccentric_emphasis'}
    assert all(fact == {'status': 'unknown', 'source': None} for fact in facts.values())
    assert state['exerciseDemandEvidence']['demandDistribution']['status'] == 'unavailable'


def test_review_projects_the_same_source_facts_for_selected_definitions():
    equipment, _, stored, draft = planning_case()
    selected_id = draft['workouts'][0]['exercises'][0]['definition_id']
    selected_index = int(selected_id.removeprefix('LIBRARY_'))
    definition = sorted(equipment['exerciseDefinitions'], key=lambda item: item['id'])[selected_index]
    definition['programmingDemands'] = {
        'unsupported_trunk': {'present': True, 'source': 'catalog: explicit support note'},
        'axial_loading': {'present': False, 'source': 'catalog: explicit support note'},
    }
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    assert result['passed']
    distribution = {'status': 'partial', 'groups': {}, 'unavailableGroups': {'eccentric_emphasis': ['LIBRARY_0']}}
    result['coordinatedJointPlanning'] = {'demandDistribution': distribution}

    context = _context(result, messages, equipment, None, len(messages) - 1)

    selected_reference = context['draft']['exercises'][0]['libraryDefinitionId']
    assert context['programmingDemandFacts'][selected_reference] == {
        'unsupported_trunk': {'status': 'present', 'source': 'catalog: explicit support note'},
        'axial_loading': {'status': 'absent', 'source': 'catalog: explicit support note'},
        'eccentric_emphasis': {'status': 'unknown', 'source': None},
    }
    assert context['programmingSummary']['demandDistribution'] == distribution
    assert 'not measure fatigue or recovery capacity' in context['demandReviewPolicy']['meaning']
    assert 'not absent' in context['demandReviewPolicy']['unknownEvidence']
    assert 'residual alone is not a violation' in context['demandReviewPolicy']['residuals']


def test_compact_selection_facts_retain_audited_demand_distribution():
    distribution = {'status': 'partial', 'groups': {'axial_loading': {'presentDefinitionIds': ['LIBRARY_0']}},
        'unavailableGroups': {'eccentric_emphasis': ['def-2']}}
    demand_facts = _facts(('unknown', None), ('present', 'catalog: explicit load note'), ('absent', 'catalog: explicit load note'))
    facts = _compact_programming_selection_facts({
        'sessions': [{'name': 'Day A', 'muscles': {}, 'movementSets': {}}],
        'exposures': {'LIBRARY_0': {'name': 'Example', 'weeklyWorkingSets': 2, 'occurrences': [
            {'exercise': 'EXERCISE_0', 'sets': 2, 'programmingDemandFacts': demand_facts}]}},
        'demandDistribution': distribution,
    })

    assert facts['demandDistribution'] == distribution
    assert facts['exerciseExposures'][0]['occurrences'][0]['programmingDemandFacts'] == demand_facts


def test_saved_selection_summary_carries_solver_distribution_and_library_sources():
    equipment, _, stored, draft = planning_case()
    selected_index = int(draft['workouts'][0]['exercises'][0]['definition_id'].removeprefix('LIBRARY_'))
    selected_definition = sorted(equipment['exerciseDefinitions'], key=lambda item: item['id'])[selected_index]
    selected_definition['programmingDemands'] = {
        'unsupported_trunk': {'present': True, 'source': 'catalog: selected entry'},
    }
    messages = requirement_messages(stored)
    receipt = audit_workout_plan(draft, equipment, messages)
    distribution = {'status': 'unavailable', 'groups': {}, 'unavailableGroups': {
        'unsupported_trunk': [selected_definition['id']]}}
    receipt['coordinatedJointPlanning'] = {'demandDistribution': distribution}
    state = {'currentDraftId': receipt['currentDraftId'], 'resolvedDecisions': receipt['resolvedDecisions']}

    facts = _programming_selection_facts_from_receipt(receipt, state, stored,
        library_fingerprint(equipment), None, equipment)

    assert facts['demandDistribution'] == distribution
    selected = next(item for item in facts['exerciseExposures']
        if item['definitionReference'] == f'LIBRARY_{selected_index}')
    assert selected['occurrences'][0]['programmingDemandFacts']['unsupported_trunk'] == {
        'status': 'present', 'source': 'catalog: selected entry'}
    assert selected['occurrences'][0]['programmingDemandFacts']['axial_loading'] == {
        'status': 'unknown', 'source': None}
