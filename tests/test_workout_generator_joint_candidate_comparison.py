from workout_generator_pkg.joint_planning import (
    _add_exercise_distribution_objective,
    _ordered_joint_objective_names,
    compare_audited_joint_candidates,
)


def _candidate(session_sets, *, errors=None, search_status='not_searched', durations=None,
               definition_id='LIBRARY_1', definition_ids=None):
    workouts = []
    audit_days = []
    for index, count in enumerate(session_sets):
        workouts.append({
            'name': f'Session {index + 1}',
            'timesCompletedInAWeek': 1,
            'exercises': [{
                'id': f'EXERCISE_{index}',
                'definition_id': (definition_ids[index] if definition_ids else definition_id),
                'numWorkSets': count,
                'satisfiesCoverage': [],
            }],
        })
        audit_days.append({
            'estimatedSeconds': (durations or [300] * len(session_sets))[index],
            'volume': {'CHEST': {'effective': count}},
            'coverageSets': {},
        })
    audit = {
        'errors': list(errors or []),
        'targets': {'weeklyEffectiveSets': {'CHEST': {'minimum': 0, 'maximum': 10}}},
        'workouts': audit_days,
        'weeklyVolume': {'CHEST': {'effective': sum(session_sets)}},
        'weeklyCoverageSets': {},
    }
    return {'workouts': workouts, 'audit': audit, 'searchStatus': search_status}


def _context(*, demand_status='available'):
    return {
        'restrictionPolicy': {},
        'libraryFingerprint': 'library-sha',
        'historyFingerprint': None,
        'sourceWorkingSetBudget': {
            'source': 'approved_preparation',
            'variableWeeklyWorkingSets': 10,
        },
        'qualifiedRoleEvidence': {'LIBRARY_1': [], 'LIBRARY_2': []},
        'exerciseFamilyEvidence': {'familyByReference': {'LIBRARY_1': 'FAMILY_1', 'LIBRARY_2': 'FAMILY_2'}},
        'demandEvidence': {
            'status': demand_status,
            'groups': {},
        },
        'demandUnion': None,
    }


def _requirements(order):
    return {
        'objectiveOrder': order,
        'auditTargets': {'weeklyEffectiveSets': {'CHEST': {'minimum': 0, 'maximum': 10}}},
        'requiredCoverage': [],
        'executionRules': [],
    }


def test_distribution_cost_matches_joint_solver_formula_and_promotes_a_better_audited_plan():
    requirements = _requirements(['distribution'])
    baseline = _candidate([2, 0])
    candidate = _candidate([1, 1], search_status='feasible', definition_id='LIBRARY_2')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'distribution'
    assert result['comparisons'] == [{
        'objective': 'distribution',
        'baselineCost': 8,
        'candidateCost': 0,
        'status': 'candidate_better',
    }]
    assert result['candidateSearchStatus'] == 'feasible'


def test_unknown_higher_priority_demand_evidence_blocks_duration_promotion():
    requirements = _requirements(['demand_distribution', 'duration_balance'])
    baseline = _candidate([1, 1], durations=[300, 300])
    candidate = _candidate([1, 1], durations=[300, 200])

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements,
        context=_context(demand_status='partial'))

    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'higher_priority_demand_evidence_unavailable'
    assert result['comparisons'] == []


def test_unmapped_demand_definition_ids_do_not_score_as_zero_exposure():
    requirements = _requirements(['demand_distribution'])
    baseline = _candidate([1, 1])
    candidate = _candidate([1, 1], definition_id='LIBRARY_2')
    context = _context()
    context['demandEvidence'] = {
        'status': 'available',
        'groups': {'axial_loading': {'presentDefinitionIds': ['uuid-for-definition']}},
    }

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)

    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'higher_priority_demand_evidence_unavailable'


def test_candidate_cannot_drop_a_role_from_its_pinned_qualification():
    requirements = _requirements(['distribution'])
    requirements['requiredCoverage'] = [{'key': 'LATERAL_DELT', 'intent': 'development'}]
    baseline = _candidate([1, 1])
    candidate = _candidate([1, 1], definition_id='LIBRARY_2')
    context = _context()
    context['qualifiedRoleEvidence']['LIBRARY_1'] = ['LATERAL_DELT']
    context['qualifiedRoleEvidence']['LIBRARY_2'] = ['LATERAL_DELT']
    for plan in (baseline, candidate):
        for workout in plan['workouts']:
            workout['exercises'][0]['satisfiesCoverage'] = []

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)

    assert result['decision'] == 'incomparable'
    assert 'candidate_role_claim_exceeds_qualified_evidence' in result['baselineAuditErrors']


def test_progression_is_a_terminal_unknown_when_earlier_numeric_priorities_tie():
    requirements = _requirements(['distribution', 'progression'])
    baseline = _candidate([1, 1])
    candidate = _candidate([1, 1], search_status='feasible')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'incomparable'
    assert result['firstDifferingObjective'] == 'progression'
    assert result['reason'] == 'progression_requires_app_owned_evidence'


def test_earlier_progression_unknown_blocks_a_later_distribution_improvement():
    requirements = _requirements(['progression', 'distribution'])
    baseline = _candidate([2, 0])
    candidate = _candidate([1, 1], search_status='feasible')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'incomparable'
    assert result['firstDifferingObjective'] == 'progression'
    assert result['comparisons'] == []


def test_candidate_with_native_audit_errors_cannot_displace_passing_baseline():
    requirements = _requirements(['distribution'])
    baseline = _candidate([1, 1])
    candidate = _candidate([2, 0], errors=['duration_exceeded'])

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'retain_baseline'
    assert result['reason'] == 'candidate_failed_native_audit_or_scope_checks'


def test_numeric_invalid_baseline_can_be_replaced_to_restore_native_feasibility():
    requirements = _requirements(['distribution'])
    baseline = _candidate([1, 1], errors=[{'code': 'volume_below_target'}])
    candidate = _candidate([1, 1], search_status='feasible')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'native_audit_feasibility'
    assert result['reason'] == 'hard_feasibility_restored'
    assert result['baselineAuditErrors'] == ['native_audit_has_errors']
    assert result['candidateAuditErrors'] == []


def test_solver_owned_coverage_floor_error_can_be_repaired_by_joint_candidate():
    requirements = _requirements(['distribution'])
    baseline = _candidate([1, 1], errors=[{'code': 'required_coverage_weekly_sets_below_minimum'}])
    candidate = _candidate([1, 1], search_status='feasible')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'native_audit_feasibility'
    assert result['reason'] == 'hard_feasibility_restored'
    assert result['baselineAuditErrors'] == ['native_audit_has_errors']
    assert result['candidateAuditErrors'] == []


def test_solver_owned_coverage_floor_does_not_mask_an_unknown_native_error():
    requirements = _requirements(['distribution'])
    baseline = _candidate([1, 1], errors=[
        {'code': 'required_coverage_weekly_sets_below_minimum'},
        {'code': 'unsupported_hard_failure'},
    ])
    candidate = _candidate([1, 1], search_status='feasible')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'baseline_not_eligible_for_comparison'
    assert result['baselineAuditErrors'] == ['native_audit_has_unclassified_errors']


def test_numeric_repair_cannot_bypass_a_baseline_scope_mismatch():
    requirements = _requirements(['distribution'])
    baseline = _candidate([1, 1], errors=['volume_below_target'])
    baseline['workouts'][0]['exercises'][0]['satisfiesCoverage'] = ['PULL']
    candidate = _candidate([1, 1], search_status='feasible', definition_id='LIBRARY_2')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'baseline_not_eligible_for_comparison'
    assert result['baselineAuditErrors'] == ['candidate_role_claim_exceeds_qualified_evidence']


def test_unclassified_native_baseline_errors_do_not_authorize_automatic_promotion():
    requirements = _requirements(['distribution'])
    baseline = _candidate([1, 1], errors=['unsupported_hard_failure'])
    candidate = _candidate([1, 1], search_status='feasible')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'baseline_not_eligible_for_comparison'
    assert result['baselineAuditErrors'] == ['native_audit_has_unclassified_errors']


def test_missing_required_coverage_is_not_misclassified_as_a_numeric_floor():
    requirements = _requirements(['distribution'])
    baseline = _candidate([1, 1], errors=[{'code': 'required_coverage_missing'}])
    candidate = _candidate([1, 1], search_status='feasible')

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=_context())

    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'baseline_not_eligible_for_comparison'
    assert result['baselineAuditErrors'] == ['native_audit_has_unclassified_errors']


def test_development_emphasis_precedes_distribution_using_the_solver_order():
    requirements = _requirements(['development_emphasis', 'distribution'])
    requirements['requiredCoverage'] = [
        {'key': 'LATERAL_DELT', 'intent': 'development'},
    ]
    baseline = _candidate([1, 1])
    candidate = _candidate([1, 1])
    for plan, totals in ((baseline, [1, 0]), (candidate, [2, 0])):
        plan['audit']['weeklyCoverageSets'] = {'LATERAL_DELT': sum(totals)}
        for day, value in zip(plan['audit']['workouts'], totals):
            day['coverageSets'] = {'LATERAL_DELT': value}
        for workout, value in zip(plan['workouts'], totals):
            workout['exercises'][0]['satisfiesCoverage'] = ['LATERAL_DELT']
    context = _context()
    context['qualifiedRoleEvidence']['LIBRARY_1'] = ['LATERAL_DELT']

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'development_emphasis'


def test_exercise_distribution_rewards_spreading_a_role_across_reviewed_families():
    requirements = _requirements(['exercise_distribution'])
    requirements['requiredCoverage'] = [
        {'key': 'LATERAL_DELT', 'intent': 'development'},
        {'key': 'VERTICAL_PULL', 'intent': 'development'},
    ]
    baseline = _candidate([2, 0], definition_ids=['LIBRARY_1', 'LIBRARY_2'])
    candidate = _candidate([1, 1], definition_ids=['LIBRARY_1', 'LIBRARY_2'])
    for plan, totals in ((baseline, [2, 0]), (candidate, [1, 1])):
        plan['audit']['weeklyCoverageSets'] = {
            'LATERAL_DELT': sum(totals), 'VERTICAL_PULL': sum(totals)}
        for day, value in zip(plan['audit']['workouts'], totals):
            day['coverageSets'] = {'LATERAL_DELT': value, 'VERTICAL_PULL': value}
        for workout in plan['workouts']:
            workout['exercises'][0]['satisfiesCoverage'] = ['LATERAL_DELT', 'VERTICAL_PULL']
    context = _context()
    context['qualifiedRoleEvidence'] = {
        'LIBRARY_1': ['LATERAL_DELT', 'VERTICAL_PULL'],
        'LIBRARY_2': ['LATERAL_DELT', 'VERTICAL_PULL'],
    }

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'exercise_distribution'
    assert result['comparisons'][-1]['baselineCost'] == 2
    assert result['comparisons'][-1]['candidateCost'] == 1
    assert result['comparisons'][-1]['objective'] == 'exercise_distribution_development'


def test_development_family_profile_is_not_pruned_by_inclusion_superset():
    from workout_generator_pkg.joint_planning import _exercise_distribution_profiles

    profiles = _exercise_distribution_profiles(
        {'DEV': ['A', 'B'], 'INCLUSION': ['A', 'B', 'C']},
        ['DEV', 'INCLUSION'], {'A': 'F1', 'B': 'F2', 'C': 'F3'},
        {'DEV': 'development', 'INCLUSION': 'inclusion'})

    assert [(profile['intent'], profile['roles'], profile['definitionRefs']) for profile in profiles] == [
        ('development', ['DEV'], ['A', 'B']),
        ('inclusion', ['INCLUSION'], ['A', 'B', 'C']),
    ]


def test_exercise_distribution_refuses_to_compare_different_development_role_doses_after_workload():
    requirements = _requirements(['workload_economy', 'exercise_distribution'])
    requirements['requiredCoverage'] = [{'key': 'PULL', 'intent': 'development'}]
    baseline = _candidate([2, 0], definition_ids=['LIBRARY_1', 'LIBRARY_3'])
    candidate = _candidate([0, 2], definition_ids=['LIBRARY_1', 'LIBRARY_3'])
    for plan, totals in ((baseline, [2, 0]), (candidate, [0, 0])):
        plan['audit']['weeklyCoverageSets'] = {'PULL': sum(totals)}
        for day, value in zip(plan['audit']['workouts'], totals):
            day['coverageSets'] = {'PULL': value}
        for workout in plan['workouts']:
            workout['exercises'][0]['satisfiesCoverage'] = (
                ['PULL'] if workout['exercises'][0]['definition_id'] == 'LIBRARY_1' else [])
    context = _context()
    context['qualifiedRoleEvidence'] = {
        'LIBRARY_1': ['PULL'], 'LIBRARY_2': ['PULL'], 'LIBRARY_3': []}
    context['exerciseFamilyEvidence']['familyByReference'].update({'LIBRARY_3': 'FAMILY_3'})

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)

    assert result['decision'] == 'incomparable'
    assert result['firstDifferingObjective'] == 'exercise_distribution'
    assert result['reason'] == 'development_role_doses_differ_at_exercise_distribution'


def test_exercise_distribution_allows_incidental_role_dose_to_change_after_workload():
    requirements = _requirements(['workload_economy', 'exercise_distribution'])
    requirements['requiredCoverage'] = [
        {'key': 'DEV', 'intent': 'development'},
        {'key': 'INC', 'intent': 'inclusion'},
    ]
    baseline = _candidate([2], definition_id='LIBRARY_1')
    candidate = _candidate([2], definition_id='LIBRARY_2')
    for plan, roles in ((baseline, ['DEV', 'INC']), (candidate, ['DEV'])):
        plan['workouts'][0]['exercises'][0]['satisfiesCoverage'] = roles
        plan['audit']['weeklyCoverageSets'] = {role: 2 for role in roles}
        plan['audit']['workouts'][0]['coverageSets'] = {role: 2 for role in roles}
    context = _context()
    context['qualifiedRoleEvidence'] = {
        'LIBRARY_1': ['DEV', 'INC'], 'LIBRARY_2': ['DEV'], 'LIBRARY_3': ['INC'],
    }
    context['exerciseFamilyEvidence']['familyByReference'] = {
        'LIBRARY_1': 'FAMILY_A', 'LIBRARY_2': 'FAMILY_B', 'LIBRARY_3': 'FAMILY_C',
    }

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'exercise_distribution'
    assert result['comparisons'][1] == {
        'objective': 'exercise_distribution_development',
        'baselineCost': 2, 'candidateCost': 2, 'status': 'tie',
    }
    assert result['comparisons'][2] == {
        'objective': 'exercise_distribution',
        'baselineCost': 4, 'candidateCost': 2, 'status': 'candidate_better',
    }


def test_development_intent_does_not_insert_unrequested_objectives():
    requirements = _requirements([
        'distribution', 'source_balance', 'exercise_distribution',
    ])
    requirements['requiredCoverage'] = [{'key': 'LATERAL_DELT', 'intent': 'development'}]
    available = {
        'distribution': True,
        'source_balance': True,
        'exercise_distribution': True,
        'development_emphasis': True,
        'development_exposure': True,
    }

    assert _ordered_joint_objective_names(requirements, available) == requirements['objectiveOrder']


def test_splitting_one_family_between_variants_is_not_a_diversity_improvement():
    requirements = _requirements(['exercise_distribution'])
    requirements['requiredCoverage'] = [{'key': 'POSTERIOR', 'intent': 'inclusion'}]
    baseline = _candidate([6, 0, 2], definition_ids=['LIBRARY_1', 'LIBRARY_2', 'LIBRARY_3'])
    split = _candidate([3, 3, 2], definition_ids=['LIBRARY_1', 'LIBRARY_2', 'LIBRARY_3'])
    context = _context()
    context['qualifiedRoleEvidence'] = {f'LIBRARY_{i}': ['POSTERIOR'] for i in (1, 2, 3)}
    context['exerciseFamilyEvidence']['familyByReference'] = {
        'LIBRARY_1': 'NORDIC', 'LIBRARY_2': 'NORDIC', 'LIBRARY_3': 'HIP_HINGE'}
    for plan in (baseline, split):
        for workout in plan['workouts']:
            workout['exercises'][0]['satisfiesCoverage'] = ['POSTERIOR']

    result = compare_audited_joint_candidates(
        baseline, split, requirements=requirements, context=context)

    assert result['decision'] == 'retain_baseline'
    assert result['comparisons'] == [{'objective': 'exercise_distribution',
        'baselineCost': 6, 'candidateCost': 6, 'status': 'tie'}]


def test_unclassified_family_cannot_prove_a_diversity_improvement():
    requirements = _requirements(['exercise_distribution'])
    requirements['requiredCoverage'] = [{'key': 'POSTERIOR', 'intent': 'inclusion'}]
    baseline, split = _candidate([2, 0]), _candidate([1, 1], definition_ids=['LIBRARY_1', 'LIBRARY_2'])
    context = _context()
    context['qualifiedRoleEvidence'] = {'LIBRARY_1': ['POSTERIOR'], 'LIBRARY_2': ['POSTERIOR']}
    context['exerciseFamilyEvidence']['familyByReference'] = {'LIBRARY_1': 'NORDIC'}
    for plan in (baseline, split):
        for workout in plan['workouts']:
            workout['exercises'][0]['satisfiesCoverage'] = ['POSTERIOR']

    result = compare_audited_joint_candidates(
        baseline, split, requirements=requirements, context=context)

    assert result['decision'] == 'incomparable'
    assert result['reason'] == 'objective_evidence_unavailable:exercise_distribution'


def test_nested_role_pool_cannot_cancel_lowering_the_containing_family_peak():
    from workout_generator_pkg.joint_planning import _joint_candidate_objective_costs
    requirements = _requirements(['exercise_distribution'])
    requirements['requiredCoverage'] = [{'key': role, 'intent': 'inclusion'}
        for role in ('POSTERIOR', 'HIP')]
    context = _context()
    context['qualifiedRoleEvidence'] = {'LIBRARY_1': ['POSTERIOR'],
        'LIBRARY_2': ['POSTERIOR', 'HIP'], 'LIBRARY_3': ['POSTERIOR', 'HIP']}
    context['exerciseFamilyEvidence']['familyByReference'] = {
        'LIBRARY_1': 'NORDIC', 'LIBRARY_2': 'RDL', 'LIBRARY_3': 'HIP_THRUST'}
    baseline = _candidate([13, 2, 0], definition_ids=['LIBRARY_1', 'LIBRARY_2', 'LIBRARY_3'])
    redistributed = _candidate([12, 3, 0], definition_ids=['LIBRARY_1', 'LIBRARY_2', 'LIBRARY_3'])

    before = _joint_candidate_objective_costs(baseline, requirements, context)['exercise_distribution']
    after = _joint_candidate_objective_costs(redistributed, requirements, context)['exercise_distribution']

    assert (before, after) == (13, 12)


def test_exercise_distribution_keeps_approved_order_without_balance_objectives():
    requirements = _requirements([
        'demand_distribution', 'duration_balance', 'exercise_distribution', 'progression',
    ])
    available = {name: True for name in requirements['objectiveOrder']}

    assert _ordered_joint_objective_names(requirements, available) == requirements['objectiveOrder']


def test_development_internals_do_not_reorder_explicit_objective_order():
    requirements = _requirements([
        'demand_distribution', 'duration_balance', 'development_emphasis', 'distribution',
        'source_balance', 'exercise_distribution', 'development_exposure', 'progression',
    ])
    requirements['requiredCoverage'] = [{'key': 'LATERAL_DELT', 'intent': 'development'}]
    available = {name: True for name in requirements['objectiveOrder']}
    available.update(development_emphasis=True, development_exposure=True,
        demand_colocation=True, role_concentration=True, role_concentration_tiebreak=True)

    ordered = _ordered_joint_objective_names(requirements, available)
    explicit = [name for name in ordered if name in requirements['objectiveOrder']]

    assert explicit == requirements['objectiveOrder']
    assert ordered == [
        'demand_distribution', 'demand_colocation', 'duration_balance',
        'development_emphasis', 'distribution', 'source_balance',
        'exercise_distribution', 'development_exposure', 'progression',
        'role_concentration', 'role_concentration_tiebreak',
    ]


def test_role_balance_precedes_muscle_distribution_only_after_workload_economy():
    requirements = _requirements(['workload_economy', 'distribution'])
    requirements['requiredCoverage'] = [{'key': 'HORIZONTAL_PULL', 'intent': 'inclusion'}]
    available = {name: True for name in requirements['objectiveOrder']}
    available.update(demand_colocation=True, role_concentration=True,
        role_concentration_tiebreak=True)

    ordered = _ordered_joint_objective_names(requirements, available)

    assert ordered == [
        'workload_economy', 'role_concentration', 'role_concentration_tiebreak',
        'distribution',
    ]


def test_role_balance_keeps_legacy_position_when_other_priorities_follow_distribution():
    requirements = _requirements([
        'workload_economy', 'distribution', 'source_balance',
        'exercise_distribution', 'development_exposure',
    ])
    requirements['requiredCoverage'] = [{'key': 'VERTICAL_PULL', 'intent': 'development'}]
    available = {name: True for name in requirements['objectiveOrder']}
    available.update(role_concentration=True, role_concentration_tiebreak=True)

    assert _ordered_joint_objective_names(requirements, available) == [
        'workload_economy', 'distribution', 'source_balance',
        'exercise_distribution', 'development_exposure',
        'role_concentration', 'role_concentration_tiebreak',
    ]


def test_exercise_distribution_milp_rows_count_weekly_sets_per_definition():
    variables = []
    rows = []

    def variable(**kwargs):
        index = 100 + len(variables)
        variables.append({'index': index, **kwargs})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        rows.append((label, lower, upper, coefficients, intercept))

    option_variables = [
        (1, 0, 0, {'count': 2, 'items': [
            {'definition_id': 'LIBRARY_A', 'satisfiesCoverage': ['PULL']},
        ]}),
        (2, 1, 0, {'count': 3, 'items': [
            {'definition_id': 'LIBRARY_A', 'satisfiesCoverage': ['PULL']},
            {'definition_id': 'LIBRARY_B', 'satisfiesCoverage': ['PULL']},
            {'definition_id': 'LIBRARY_C', 'satisfiesCoverage': ['PULL']},
        ]}),
    ]
    costs, profiles, peaks = _add_exercise_distribution_objective(
        variable, constraint, option_variables,
        [{'timesCompletedInAWeek': 2}, {'timesCompletedInAWeek': 1}],
        [{'timesCompletedInAWeek': 1, 'exercises': [
            {'definition_id': 'LIBRARY_A', 'numWorkSets': 1},
        ]}],
        ['PULL'], {'LIBRARY_A': 'NORDIC', 'LIBRARY_B': 'HINGE', 'LIBRARY_C': 'NORDIC'},
    )

    peak = peaks[0][1]
    assert len(profiles) == 1
    assert profiles[0]['definitionRefs'] == ['LIBRARY_A', 'LIBRARY_B', 'LIBRARY_C']
    assert costs == {peak: 1}
    assert rows == [
        (('exercise_distribution', 0, 'HINGE'), -float('inf'), 0,
            {2: 3, peak: -1}, 0),
        (('exercise_distribution', 0, 'NORDIC'), -float('inf'), 0,
            {1: 4, 2: 6, peak: -1}, 1),
    ]


def test_single_qualified_definition_does_not_create_an_exercise_distribution_peak():
    costs, profiles, peaks = _add_exercise_distribution_objective(
        lambda **kwargs: 100,
        lambda *args: None,
        [(1, 0, 0, {'count': 2, 'items': [
            {'definition_id': 'LIBRARY_A', 'satisfiesCoverage': ['PULL']},
        ]})],
        [{'timesCompletedInAWeek': 1}], [], ['PULL'], {'LIBRARY_A': 'NORDIC'})

    assert costs == {}
    assert profiles == []
    assert peaks == []


def test_variable_source_cap_does_not_count_approved_fixed_prefix():
    requirements = _requirements(['duration_balance'])
    requirements['requiredCoverage'] = [{'key': 'DEVELOPMENT', 'intent': 'development'}]
    baseline = _candidate([1, 1], durations=[300, 300])
    candidate = _candidate([1, 1], durations=[300, 300])
    for plan in (baseline, candidate):
        for workout in plan['workouts']:
            workout['exercises'][0]['satisfiesCoverage'] = ['DEVELOPMENT']
    fixed = {
        'name': 'Existing', 'timesCompletedInAWeek': 1,
        'exercises': [{'definition_id': 'LIBRARY_1', 'numWorkSets': 20,
            'satisfiesCoverage': ['DEVELOPMENT']}],
    }
    for plan in (baseline, candidate):
        plan['workouts'].insert(0, fixed)
        plan['audit']['workouts'].insert(0, {
            'estimatedSeconds': 300, 'volume': {'CHEST': {'effective': 20}}, 'coverageSets': {},
        })
        plan['audit']['weeklyVolume']['CHEST']['effective'] += 20
    context = _context()
    context['qualifiedRoleEvidence']['LIBRARY_1'] = ['DEVELOPMENT']
    context['sourceWorkingSetBudget']['variableWeeklyWorkingSets'] = 2
    context['fixedWorkouts'] = [fixed]

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)

    assert result['decision'] == 'retain_baseline'
    assert result['reason'] == 'no_numeric_improvement_baseline_wins_tie'


def test_no_development_cap_does_not_treat_source_budget_as_a_hard_quota():
    requirements = _requirements(['distribution'])
    baseline = _candidate([2, 0])
    candidate = _candidate([1, 1], definition_id='LIBRARY_2')
    for source_budget in (None, {
            'source': 'code_preparation_volume_only_seed', 'variableWeeklyWorkingSets': 0,
    }):
        context = _context()
        context['sourceWorkingSetBudget'] = source_budget

        result = compare_audited_joint_candidates(
            baseline, candidate, requirements=requirements, context=context)

        assert result['decision'] == 'promote_candidate'
        assert result['firstDifferingObjective'] == 'distribution'


def test_role_concentration_cost_matches_shared_peak_and_can_resolve_a_tie():
    requirements = _requirements(['distribution'])
    requirements['requiredCoverage'] = [{'key': 'LATERAL_DELT', 'intent': 'development'}]

    def plan(role_counts):
        workouts = []
        audit_days = []
        for index, (role_sets, other_sets) in enumerate(role_counts):
            exercises = []
            if role_sets:
                exercises.append({'id': f'R{index}', 'definition_id': 'LIBRARY_ROLE',
                    'numWorkSets': role_sets, 'satisfiesCoverage': ['LATERAL_DELT']})
            if other_sets:
                exercises.append({'id': f'O{index}', 'definition_id': 'LIBRARY_OTHER',
                    'numWorkSets': other_sets, 'satisfiesCoverage': []})
            workouts.append({'timesCompletedInAWeek': 1, 'exercises': exercises})
            audit_days.append({'estimatedSeconds': 300,
                'volume': {'CHEST': {'effective': role_sets + other_sets}},
                'coverageSets': {'LATERAL_DELT': role_sets}})
        return {'workouts': workouts, 'searchStatus': 'feasible', 'audit': {
            'errors': [],
            'targets': requirements['auditTargets'],
            'workouts': audit_days,
            'weeklyVolume': {'CHEST': {'effective': 4}},
            'weeklyCoverageSets': {'LATERAL_DELT': sum(value[0] for value in role_counts)},
        }}

    baseline = plan([(2, 0), (0, 2)])
    candidate = plan([(1, 1), (1, 1)])
    context = _context()
    context['qualifiedRoleEvidence'] = {
        'LIBRARY_ROLE': ['LATERAL_DELT'], 'LIBRARY_OTHER': [],
    }

    result = compare_audited_joint_candidates(
        baseline, candidate, requirements=requirements, context=context)

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'role_concentration'
    assert result['comparisons'][-1] == {
        'objective': 'role_concentration', 'baselineCost': 2,
        'candidateCost': 0, 'status': 'candidate_better',
        'unit': 'frequency_scaled_peak_surplus',
    }


def test_role_peak_sum_breaks_a_tie_left_by_an_immovable_role_peak():
    requirements = _requirements(['distribution'])
    requirements['auditTargets'] = {'weeklyEffectiveSets': {}}
    requirements['requiredCoverage'] = [
        {'key': 'LOCKED', 'intent': 'inclusion'},
        {'key': 'PULL', 'intent': 'inclusion'},
    ]

    def plan(pull_counts):
        workouts, audit_days = [], []
        for index, pull_count in enumerate(pull_counts):
            exercises = []
            if index == 0:
                exercises.append({'id': f'LOCK_{index}', 'definition_id': 'LIBRARY_LOCK',
                    'numWorkSets': 8, 'satisfiesCoverage': ['LOCKED']})
            if pull_count:
                exercises.append({'id': f'PULL_{index}', 'definition_id': 'LIBRARY_PULL',
                    'numWorkSets': pull_count, 'satisfiesCoverage': ['PULL']})
            workouts.append({'name': f'Session {index}', 'timesCompletedInAWeek': 1,
                'exercises': exercises})
            audit_days.append({'estimatedSeconds': 300,
                'volume': {'CHEST': {'effective': 8 + pull_count}},
                'coverageSets': {'LOCKED': 8 if index == 0 else 0, 'PULL': pull_count}})
        return {'workouts': workouts, 'searchStatus': 'feasible', 'audit': {
            'errors': [], 'targets': requirements['auditTargets'], 'workouts': audit_days,
            'weeklyVolume': {'CHEST': {'effective': 30}},
            'weeklyCoverageSets': {'LOCKED': 8, 'PULL': 6},
        }}

    concentrated = plan([6, 0, 0])
    spread = plan([2, 2, 2])
    context = _context()
    context['sourceWorkingSetBudget'] = None
    context['qualifiedRoleEvidence'] = {
        'LIBRARY_LOCK': ['LOCKED'], 'LIBRARY_PULL': ['PULL'],
    }

    result = compare_audited_joint_candidates(
        concentrated, spread, requirements=requirements, context=context)

    assert result['decision'] == 'promote_candidate'
    assert result['firstDifferingObjective'] == 'role_concentration_tiebreak'
    assert result['comparisons'] == [
        {'objective': 'role_concentration', 'baselineCost': 16,
            'candidateCost': 16, 'status': 'tie',
            'unit': 'frequency_scaled_peak_surplus'},
        {'objective': 'role_concentration_tiebreak', 'baselineCost': 28,
            'candidateCost': 16, 'status': 'candidate_better',
            'unit': 'frequency_scaled_peak_surplus'},
    ]
    from workout_generator_pkg.generation_audit import render_optimization_disclosure
    disclosure = render_optimization_disclosure({
        'approvedPriorities': [{'priority': 'distribution', 'owner': 'joint_solver',
            'status': 'optimal'}],
        'structuralConcentration': {'rolePlacement': {
            'status': 'optimal', 'solverStatus': 'optimal',
            'profiles': [{'peakSurplusPerOccurrence': 16 / 3}],
            'profilePeakSurplusSumPerOccurrence': 16 / 3,
            'sumTieBreakStatus': 'optimal',
        }},
    })
    assert 'After preserving the worst role peak, the role-balance tie-break reduces the sum' in disclosure
    assert 'The sum of distinct role-profile peak surpluses is 5.33333 sets per occurrence.' in disclosure


def test_role_peak_sum_counts_distinct_role_memberships_even_when_candidate_exposure_matches():
    from workout_generator_pkg.joint_planning import _joint_candidate_objective_costs

    requirements = _requirements(['distribution'])
    requirements['requiredCoverage'] = [
        {'key': 'ROLE_A', 'intent': 'inclusion'},
        {'key': 'ROLE_B', 'intent': 'inclusion'},
    ]
    workouts = [
        {'timesCompletedInAWeek': 1, 'exercises': [
            {'id': 'A0', 'definition_id': 'LIBRARY_A', 'numWorkSets': 2,
                'satisfiesCoverage': ['ROLE_A']},
            {'id': 'B0', 'definition_id': 'LIBRARY_B', 'numWorkSets': 2,
                'satisfiesCoverage': ['ROLE_B']},
        ]},
        {'timesCompletedInAWeek': 1, 'exercises': []},
    ]
    candidate = {'workouts': workouts, 'audit': {
        'workouts': [
            {'coverageSets': {'ROLE_A': 2, 'ROLE_B': 2}, 'estimatedSeconds': 300,
                'volume': {'CHEST': {'effective': 4}}},
            {'coverageSets': {'ROLE_A': 0, 'ROLE_B': 0}, 'estimatedSeconds': 300,
                'volume': {'CHEST': {'effective': 0}}},
        ],
        'weeklyCoverageSets': {'ROLE_A': 2, 'ROLE_B': 2},
        'weeklyVolume': {'CHEST': {'effective': 4}},
    }}
    context = _context()
    context['qualifiedRoleEvidence'] = {
        'LIBRARY_A': ['ROLE_A'], 'LIBRARY_B': ['ROLE_B'],
    }

    costs = _joint_candidate_objective_costs(candidate, requirements, context)
