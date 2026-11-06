import math

import pytest

from workout_generator_pkg import cp_solver, joint_planning
from workout_generator_pkg.generation_audit import executable_setup_evidence, setup_resource_profile


@pytest.mark.parametrize('shared', [False, True])
@pytest.mark.parametrize('superset', [False, True])
def test_physical_setup_cp_matches_retained_resource_audit(shared, superset):
    groups = [['bar', 'floor']] if shared else []
    requirements = {'executionRules': [{'kind': 'supersetNoReconfiguration', 'sharedResourceGroups': groups}]}
    definitions = {
        'flat': {'id': 'flat', 'equipmentId': 'bar', 'exerciseType': 'WEIGHT',
            'reviewedExecution': {'setupConfiguration': [{'resourceId': 'bar',
                'state': {'rack': 'low'}, 'source': 'https://example.test/rack', 'basis': 'Required rack state.'}]}},
        'high': {'id': 'high', 'equipmentId': 'bar', 'exerciseType': 'WEIGHT',
            'reviewedExecution': {'setupConfiguration': [{'resourceId': 'bar',
                'state': {'rack': 'high'}, 'source': 'https://example.test/rack', 'basis': 'Required rack state.'}]}},
        'floor': {'id': 'floor', 'equipmentId': 'floor', 'exerciseType': 'BODY_WEIGHT'},
    }
    sources = [{'definition_id': reference, 'numWorkSets': 2, 'requiresLoadCalibration': True,
        'superset': 'pair' if superset and index < 2 else None}
        for index, reference in enumerate(('flat', 'floor', 'high'))]
    source_blocks = [sources[:2], sources[2:]] if superset else [[source] for source in sources]
    variables, constraints = [], []

    def variable(upper=1, lower=0, integer=True, domain_identity=None):
        index = len(variables)
        variables.append({'upper': upper, 'lower': lower, 'integer': integer,
            'domainIdentity': domain_identity, 'objectiveCost': 0})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        constraints.append((label, lower, upper, intercept, coefficients))

    def conjunction(indices, identity):
        result = variable(domain_identity={'kind': 'test_conjunction', **identity})
        for index in indices:
            constraint(('and_upper', result, index), -math.inf, 0, {result: 1, index: -1})
        constraint(('and_lower', result), 1 - len(indices), math.inf,
            {result: 1, **dict.fromkeys(indices, -1)})
        return result

    blocks, present = [], []
    for members in source_blocks:
        option = variable(lower=1)
        present.append(option)
        blocks.append({'options': [option], 'optionValues': {option: {'count': 2,
            'setupProfiles': [setup_resource_profile(definitions[source['definition_id']], source)
                for source in members]}}})
    before = {(first, second): variable(lower=int(first < second), upper=int(first < second))
        for first in range(len(blocks)) for second in range(len(blocks)) if first != second}
    costs, evidence = joint_planning._add_physical_setup_sequence(blocks, requirements,
        variable, constraint, 0, 2, present, [], [], before, conjunction)
    status, chosen = cp_solver.solve(variables, constraints, timeout_seconds=5)
    assert status == 'optimal'
    audit = executable_setup_evidence({'exercises': sources}, definitions, groups)
    for metric, audit_metric in (('setup_economy', 'physicalPreparationCount'),
            ('setup_economy_transitions', 'physicalRequiredChanges'),
            ('initialResourceActivationCount', 'initialResourceActivationCount'),
            ('unknownPhysicalPreparationCount', 'unknownPhysicalPreparationCount')):
        assert sum(chosen[index] * cost for index, cost in costs[metric].items()) == 2 * audit[audit_metric]
    assert evidence['physicalSetupResourcesComplete'] is True
