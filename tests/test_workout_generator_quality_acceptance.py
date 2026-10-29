import pytest

from workout_generator_pkg import generation_audit


def _credit(**values):
    return {muscle: {'direct': value, 'indirect': 0} for muscle, value in values.items()}


def test_coverage_minimums_count_weekly_sets_and_frequency_weighted_sessions():
    report = {
        'weeklyCoverageSets': {'lateral_delt': 6, 'vertical_pull': 4},
        'workouts': [
            {'name': 'A', 'timesCompletedInAWeek': 1, 'coverageSets': {'lateral_delt': 3, 'vertical_pull': 2}},
            {'name': 'B', 'timesCompletedInAWeek': 1, 'coverageSets': {'lateral_delt': 3, 'vertical_pull': 0}},
            {'name': 'C', 'timesCompletedInAWeek': 2, 'coverageSets': {'lateral_delt': 0, 'vertical_pull': 1}},
        ],
        'issues': [], 'errors': [],
    }

    generation_audit.audit_coverage_minimums(report, [
        {'key': 'lateral_delt', 'minimumWeeklySets': 6, 'minimumSessions': 2},
        {'key': 'vertical_pull', 'minimumWeeklySets': 6, 'minimumSessions': 4},
    ])

    assert report['coverageMinimumEvidence']['lateral_delt'] == {
        'weeklyWorkingSets': 6, 'weeklyTrainingSessions': 2,
        'minimumWeeklySets': 6, 'weeklySetsStatus': 'met',
        'minimumSessions': 2, 'sessionsStatus': 'met'}
    assert report['coverageMinimumEvidence']['vertical_pull']['weeklyTrainingSessions'] == 3
    assert report['coverageMinimumEvidence']['vertical_pull']['sessionsStatus'] == 'below_minimum'
    assert {error['code'] for error in report['errors']} == {
        'required_coverage_weekly_sets_below_minimum', 'required_coverage_sessions_below_minimum'}


@pytest.mark.parametrize('development_roles', [
    ['lateral_delt'], ['vertical_pull', 'lateral_delt'], ['lateral_delt', 'vertical_pull']])
def test_qualified_menu_reports_lateral_ceiling_binding_constraints_and_minimum_conflict(development_roles):
    candidates = [
        {'id': 'PRESS', 'name': 'Press', 'creditsPerWorkingSet': _credit(chest=1, shoulders=.5)},
        {'id': 'ROW', 'name': 'Row', 'creditsPerWorkingSet': _credit(back=1, shoulders=.5)},
        {'id': 'VERTICAL', 'name': 'Vertical Press', 'creditsPerWorkingSet': _credit(shoulders=1)},
        {'id': 'REAR', 'name': 'Rear Delt', 'creditsPerWorkingSet': _credit(shoulders=1)},
        {'id': 'LATERAL', 'name': 'Lateral Raise', 'creditsPerWorkingSet': _credit(shoulders=1)},
    ]
    requirements = {
        'auditTargets': {'weeklyEffectiveSets': {
            'chest': {'minimum': 15, 'maximum': 18},
            'back': {'minimum': 15, 'maximum': 18},
            'shoulders': {'minimum': 0, 'maximum': 21},
        }},
        'requiredCoverage': [
            {'key': 'vertical_push', 'scope': 'weekly', 'intent': 'inclusion'},
            *[{'key': role, 'scope': 'weekly', 'intent': 'development',
               'minimumWeeklySets': 6, 'minimumSessions': 2} for role in development_roles],
        ],
    }
    coverage = {
        'PRESS': [], 'ROW': ['vertical_pull'], 'VERTICAL': ['vertical_push'], 'REAR': [], 'LATERAL': ['lateral_delt'],
    }

    result = generation_audit.development_menu_limits(candidates, requirements, coverage,
        source_set_cap=150, training_occurrences=3, minimum_work_sets=2)

    assert result['roleUpperBounds']['lateral_delt'] == pytest.approx(4)
    assert result['status'] == 'infeasible_relaxation'
    assert result['approvedMinimumConflicts'] == [{
        'role': 'lateral_delt', 'kind': 'minimumWeeklySets',
        'required': 6, 'qualifiedMenuUpperBound': pytest.approx(4)}]
    constraints = result['roleUpperBoundConstraints']['lateral_delt']
    assert {(item['kind'], item.get('key')) for item in constraints if item['kind'] != 'source_set_cap'} >= {
        ('weekly_muscle_maximum', 'shoulders'),
        ('weekly_muscle_minimum', 'chest'),
        ('weekly_muscle_minimum', 'back'),
        ('required_coverage_minimum', 'vertical_push'),
    }
    cap = next(item for item in constraints if item['kind'] == 'source_set_cap')
    assert cap['slack'] == pytest.approx(114)
    assert cap['binding'] is False


def test_regional_targets_use_sourced_anatomy_and_gate_unknown_aggregate_contributions():
    known = generation_audit.muscle_credits_per_set({
        'id': 'occurrence', 'libraryDefinitionId': '3c366a30-29b9-5b1d-86d6-3bc55935584a',
        'exerciseType': 'WEIGHT', 'muscleGroups': ['BACK_UPPER_BACK'], 'secondaryMuscleGroups': [],
    })
    assert known['back']['direct'] == 1
    assert known['latissimus_dorsi']['direct'] == 1
    assert known['upper_back']['direct'] == 1
    assert 'latissimus_dorsi' not in generation_audit.available_muscle_targets()

    report = generation_audit.audit_workout_package({
        'workouts': [{'name': 'A', 'workoutComponents': [{
            'type': 'Exercise', 'id': 'occurrence', 'libraryDefinitionId': 'c5912ea4-1f3e-4a01-8e45-1989ea06ddaa',
            'name': 'Unannotated Row', 'exerciseType': 'WEIGHT', 'muscleGroups': ['BACK_UPPER_BACK'],
            'secondaryMuscleGroups': [], 'sets': [{'type': 'WeightSet', 'reps': 8, 'weight': 20}],
        }]}]},
        {'weeklyEffectiveSets': {'latissimus_dorsi': {'minimum': 1, 'maximum': 10}}})

    assert report['regionalTargetEvidence']['latissimus_dorsi']['status'] == 'unknown_selected_aggregate_contributions'
    assert 'regional_target_evidence_unknown' in {error['code'] for error in report['errors']}
    assert 'volume_below_target' not in {error['code'] for error in report['errors']}


def test_regional_summary_keeps_unknown_incomplete_without_losing_known_evidence():
    known_id = '3c366a30-29b9-5b1d-86d6-3bc55935584a'
    unknown_id = 'c5912ea4-1f3e-4a01-8e45-1989ea06ddaa'
    exercises = []
    for identifier, definition_id, name in (
            ('KNOWN_ROW', known_id, 'Reviewed Row'), ('UNKNOWN_ROW', unknown_id, 'Unannotated Row')):
        exercises.append({'type': 'Exercise', 'id': identifier,
            'name': name, 'exerciseType': 'WEIGHT', 'muscleGroups': ['BACK_UPPER_BACK'],
            'secondaryMuscleGroups': [], 'sets': [
                {'type': 'WeightSet', 'subCategory': 'WorkSet', 'reps': 8, 'weight': 20} for _ in range(2)]})
    report = generation_audit.audit_workout_package({'workouts': [
        {'name': 'Day', 'timesCompletedInAWeek': 2, 'workoutComponents': exercises}]}, {})
    source_draft = {'workouts': [{'name': 'Day', 'exercises': [
        {'definition_id': 'LIBRARY_0', 'numWorkSets': 2}, {'definition_id': 'LIBRARY_1', 'numWorkSets': 2}]}]}
    plan_index = {'exercises': [
        {'id': exercise['id'], 'name': exercise['name'], 'libraryDefinitionId': definition_id,
            'muscleGroups': exercise['muscleGroups']}
        for exercise, definition_id in zip(exercises, (known_id, unknown_id), strict=True)],
        'workouts': [{'name': 'Day', 'exerciseIds': ['KNOWN_ROW', 'UNKNOWN_ROW'],
            'timesCompletedInAWeek': 2}]}
    review_draft = {'exercises': [
        {'id': 'KNOWN_ROW', 'libraryDefinitionId': 'LIBRARY_0'},
        {'id': 'UNKNOWN_ROW', 'libraryDefinitionId': 'LIBRARY_1'}],
        'libraryDefinitions': {
            'LIBRARY_0': {'name': 'Reviewed Row', 'muscleGroups': ['BACK_UPPER_BACK']},
            'LIBRARY_1': {'name': 'Unannotated Row', 'muscleGroups': ['BACK_UPPER_BACK']}}}
    summary = generation_audit.build_programming_summary(report, report, source_draft,
        plan_index, review_draft, {}, {}, final_artifact={'workouts': [{
            'name': 'Day', 'components': exercises}]})

    lats = summary['regionalMuscleSummary']['latissimus_dorsi']
    assert lats['status'] == 'unknown_selected_aggregate_contributions'
    assert lats['weeklyEffectiveSets'] is None
    assert lats['knownWeeklyEffectiveSets'] == 4
    assert lats['unknownOccurrences'] == [{
        'exerciseId': 'UNKNOWN_ROW', 'exercise': 'Unannotated Row', 'session': 'Day',
        'sessionsPerWeek': 2, 'aggregateParentWorkingSetCredits': 4}]
    exposures = summary['exposures']
    known_lat_facts = exposures['LIBRARY_0']['occurrences'][0]['regionalMuscleEvidence']['known']['latissimus_dorsi']
    assert known_lat_facts['effectiveSets'] == 2
    assert known_lat_facts['weeklyEffectiveSets'] == 4
    assert known_lat_facts['source'].startswith('https://')
    assert exposures['LIBRARY_1']['occurrences'][0]['regionalMuscleEvidence'] == {
        'known': {}, 'unknownRegions': ['latissimus_dorsi', 'upper_back']}


def test_quality_disclosure_keeps_valid_export_separate_from_incomplete_objectives():
    disclosure = generation_audit.render_optimization_disclosure({
        'approvedPriorities': [
            {'owner': 'joint_solver', 'priority': 'demand_distribution', 'status': 'unavailable_evidence'},
            {'owner': 'joint_solver', 'priority': 'duration_balance', 'status': 'optimal'},
            {'owner': 'joint_solver', 'priority': 'exercise_distribution', 'status': 'unavailable_evidence'},
            {'owner': 'joint_solver', 'priority': 'workload_economy', 'status': 'optimal'},
            {'owner': 'joint_solver', 'priority': 'distribution', 'status': 'feasible'},
        ],
        'developmentEmphasis': {
            'roleKeys': ['lateral_delt', 'vertical_pull'],
            'status': 'optimal',
            'minimumWeeklyWorkingSets': 6,
            'roleWeeklyWorkingSets': {'lateral_delt': 8, 'vertical_pull': 8},
            'sourceBudget': {},
        },
    })

    assert 'Quality completion: incomplete.' in disclosure
    assert 'not optimized because verified exercise evidence is unavailable' in disclosure
    assert 'accepted export does not establish that objective as achieved' in disclosure
    assert 'lateral delt: 8 raw working sets/week' in disclosure
    assert 'vertical pull: 8 raw working sets/week' in disclosure


def test_quality_disclosure_only_claims_priority_completion_within_recorded_scope():
    disclosure = generation_audit.render_optimization_disclosure({
        'approvedPriorities': [
            {'owner': 'joint_solver', 'priority': 'demand_distribution', 'status': 'optimal'},
            {'owner': 'joint_solver', 'priority': 'duration_balance', 'status': 'optimal'},
        ],
        'developmentEmphasis': {
            'roleKeys': ['lateral_delt'],
            'status': 'optimal',
            'minimumWeeklyWorkingSets': 6,
            'roleWeeklyWorkingSets': {'lateral_delt': 7},
            'sourceBudget': {},
        },
    })

    assert 'Quality completion: requested optimization stages are proven' in disclosure
    assert 'within their recorded menu, evidence and preceding-priority scopes' in disclosure
    assert 'Native compliance and export acceptance are separate checks' in disclosure


def test_unrequested_development_does_not_imply_maximization_or_a_source_cap():
    disclosure = generation_audit.render_optimization_disclosure({
        'developmentEmphasis': {
            'roleKeys': ['lateral_delt', 'vertical_pull'],
            'status': 'not_requested',
            'roleWeeklyWorkingSets': {'lateral_delt': 4, 'vertical_pull': 4},
            'combinedExposure': {'weeklyWorkingSets': 8},
            'sourceBudget': {
                'status': 'unbounded_by_user',
                'source': 'unbounded_by_user',
                'variableSourceWorkingSets': None,
                'fixedExistingWorkingSets': 0,
                'sourceBudgetWeeklyWorkingSets': None,
                'variableMenuCapWorkingSets': None,
            },
            'scope': 'STALE source weekly set budget scope',
        },
    })

    assert 'no additional exposure optimization was requested' in disclosure
    assert 'lateral delt: 4 raw working sets/week' in disclosure
    assert 'vertical pull: 4 raw working sets/week' in disclosure
    assert 'No user-set weekly working-set cap was supplied' in disclosure
    assert 'maximize the minimum' not in disclosure
    assert 'combined development-role exposure' not in disclosure
    assert 'variable-menu cap' not in disclosure
    assert 'STALE source weekly set budget scope' not in disclosure


def test_explicit_development_source_cap_remains_disclosed():
    disclosure = generation_audit.render_optimization_disclosure({
        'developmentEmphasis': {
            'roleKeys': ['lateral_delt'],
            'status': 'optimal',
            'minimumWeeklyWorkingSets': 6,
            'roleWeeklyWorkingSets': {'lateral_delt': 7},
            'sourceBudget': {
                'status': 'applied',
                'source': 'submitted_candidate_session_counts',
                'variableSourceWorkingSets': 91,
                'fixedExistingWorkingSets': 0,
                'sourceBudgetWeeklyWorkingSets': 91,
                'variableMenuCapWorkingSets': 91,
            },
        },
    })

    assert 'active source-set cap' in disclosure
    assert '91 weekly variable-session sets' in disclosure
    assert 'variable-menu cap is 91 weekly sets' in disclosure
