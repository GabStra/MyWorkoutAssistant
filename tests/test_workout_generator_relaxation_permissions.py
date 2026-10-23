import copy

import pytest

from workout_generator_pkg.requirement_accounting import (
    alternative_evaluation_contract,
    has_unresolved_numeric_relaxation,
    relaxation_paths,
    relaxation_rank_by_path,
    validate_accounting,
    validate_relaxation_permissions,
)


MINIMUM = '/auditTargets/weeklyEffectiveSets/chest/minimum'
MAXIMUM = '/auditTargets/weeklyEffectiveSets/chest/maximum'


def test_explicit_permissions_replace_legacy_accounting_and_keep_rank():
    requirements = {
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 8, 'maximum': 16}}},
        'requirementAccounting': [{
            'instruction': 'The chest floor is fixed.', 'sourceReferences': ['SOURCE_0'],
            'requirementPaths': [MINIMUM], 'priority': 'mandatory', 'enforcement': 'constraint',
            'reason': 'Explicit floor.'}],
        'relaxationPermissions': [{'path': MAXIMUM, 'direction': 'raise_maximum', 'rank': 2}],
    }

    validate_relaxation_permissions(requirements)
    validate_accounting(requirements, {'SOURCE_0': {'role': 'user', 'content': 'Keep at least 8 sets.'}})
    assert relaxation_paths(requirements) == [MAXIMUM]
    assert relaxation_rank_by_path(requirements) == {MAXIMUM: 2}
    assert not has_unresolved_numeric_relaxation(requirements)


def test_explicit_empty_permissions_override_legacy_permission_and_unresolved_direction():
    requirements = {
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 8}}},
        'requirementAccounting': [{
            'instruction': 'The minimum may be negotiable.', 'sourceReferences': ['SOURCE_0'],
            'requirementPaths': [MINIMUM], 'priority': 'negotiable', 'enforcement': 'constraint',
            'reason': 'Legacy record.'}],
        'relaxationPermissions': [],
    }

    validate_accounting(requirements, {'SOURCE_0': {'role': 'user', 'content': 'Plan chest work.'}})
    assert relaxation_paths(requirements) == []
    assert not has_unresolved_numeric_relaxation(requirements)


def test_saved_legacy_records_keep_their_accounting_permission_fallback():
    requirements = {
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 8}}},
        'requirementAccounting': [{
            'instruction': 'The chest minimum may be reduced.', 'sourceReferences': ['SOURCE_0'],
            'requirementPaths': [MINIMUM], 'priority': 'negotiable', 'enforcement': 'constraint',
            'relaxationDirection': 'lower_minimum', 'reason': 'Source permits a lower floor.'}],
    }

    assert relaxation_paths(requirements) == [MINIMUM]
    assert not has_unresolved_numeric_relaxation(requirements)


@pytest.mark.parametrize('permission', [
    {'path': '/exerciseRestrictions/excludedDefinitionIds', 'direction': 'lower_minimum'},
    {'path': MINIMUM, 'direction': 'raise_maximum'},
    {'path': '/auditTargets/weeklyEffectiveSets/back/minimum', 'direction': 'lower_minimum'},
    {'path': MINIMUM, 'direction': 'lower_minimum', 'rank': True},
    {'path': MINIMUM, 'direction': 'lower_minimum', 'rank': 0},
])
def test_explicit_permissions_reject_unsupported_paths_directions_and_ranks(permission):
    requirements = {
        'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 8, 'maximum': 16}}},
        'relaxationPermissions': [permission],
    }

    with pytest.raises(ValueError):
        validate_relaxation_permissions(requirements)


def test_explicit_permission_cannot_be_duplicated_and_survives_candidate_boundaries():
    original = {'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 8}}},
        'relaxationPermissions': [{'path': MINIMUM, 'direction': 'lower_minimum'}]}
    duplicate = copy.deepcopy(original)
    duplicate['relaxationPermissions'].append(copy.deepcopy(duplicate['relaxationPermissions'][0]))
    with pytest.raises(ValueError, match='only once'):
        validate_relaxation_permissions(duplicate)

    candidate = copy.deepcopy(original)
    candidate['auditTargets']['weeklyEffectiveSets']['chest']['minimum'] = 0
    validate_relaxation_permissions(candidate)
    assert relaxation_paths(candidate) == [MINIMUM]


def test_explicit_permission_allows_only_the_hypothetical_change_and_never_approves_it():
    original = {'requirementsId': 'REQ_1', 'restrictionPolicy': {},
        'requirements': {
            'auditTargets': {'weeklyEffectiveSets': {'chest': {'minimum': 8, 'maximum': 16}}},
            'relaxationPermissions': [{'path': MAXIMUM, 'direction': 'raise_maximum'}]}}
    candidate = copy.deepcopy(original)
    candidate['requirementsId'] = 'REQ_2'
    candidate['requirements']['auditTargets']['weeklyEffectiveSets']['chest']['maximum'] = 20
    candidate['proposedAlternative'] = {'originalRequirementsId': 'REQ_1',
        'changes': [{'path': MAXIMUM, 'from': 16, 'to': 20}], 'requiresUserApproval': True}

    contract = alternative_evaluation_contract(original, candidate)

    assert contract['proposedOverrides'] == [{'path': MAXIMUM, 'from': 16, 'to': 20}]
    assert contract['approval']['status'] == 'pending'
