"""Source-backed execution rules; training recommendations are not universal prohibitions."""

import copy
from itertools import combinations, permutations
from collections import Counter

from .programming_policy import (INTERFERENCE_METRICS, execution_order_phase,
    execution_interference_metric_names, selection_precedes_execution)
from .exercise_contracts import execution_supporting_muscles

from .generation_audit import (_is_work_set, add_audit_issue, MUSCLES,
    setup_resource_profile, _setup_evidence_for_blocks)


_COVERAGE = {'type': 'string', 'minLength': 1, 'description': 'An approved requiredCoverage key. Execution review verifies that each assigned movement actually qualifies.'}
_SELECTOR = {'anyOf': [_COVERAGE, {'type': 'null'}], 'description': 'Coverage key, or null for all exercises to which this rule applies.'}
MINIMUM_WORK_SETS_RULE = {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 20}
SESSION_STRUCTURE_RULE = {'kind': 'sessionStructure', 'maximumExercises': 15, 'maximumSupersetSize': 3}
DEFAULT_ISOLATION_REST_RULE = {'kind': 'rest', 'coverageKey': None, 'exerciseCategory': 'ISOLATION',
    'context': 'straightSets', 'minimumSeconds': 60, 'maximumSeconds': 120}


def default_block_recovery_rules(rules):
    """Reuse approved straight-set ranges for the distinct inter-block boundary."""
    return [{**rule, 'context': 'exerciseTransition'} for rule in rules
        if rule.get('kind') == 'rest' and rule.get('context') == 'straightSets'
        and not any(other.get('kind') == 'rest' and other.get('context') == 'exerciseTransition'
            and other.get('coverageKey') in (None, rule.get('coverageKey'))
            and other.get('exerciseCategory') in (None, rule.get('exerciseCategory')) for other in rules)]


def block_recovery_bounds(block, requirements, definitions):
    categories = ['HEAVY_COMPOUND', 'MODERATE_COMPOUND', 'ISOLATION']
    category = next((category for category in categories if any(
        definitions.get(item['definition_id'], {}).get('exerciseCategory') == category for item in block)), None)
    roles = {role for item in block for role in item.get('satisfiesCoverage', [])}
    rules = [rule for rule in requirements.get('executionRules', []) if rule.get('kind') == 'rest'
        and rule.get('context') == 'exerciseTransition'
        and rule.get('exerciseCategory') in (None, category)
        and (rule.get('coverageKey') is None or rule['coverageKey'] in roles)]
    if not rules:
        return None
    lower, upper = max(rule['minimumSeconds'] for rule in rules), min(rule['maximumSeconds'] for rule in rules)
    if lower > upper:
        raise ValueError('The approved block-recovery ranges conflict.')
    return lower, upper


def prescribe_block_recovery(day, requirements, definitions, *, complete_session=True):
    """Place recovery on each completed block, never inside it or after the session."""
    if not any(rule.get('context') == 'exerciseTransition' for rule in requirements.get('executionRules', [])):
        return
    blocks = []
    for item in day.get('exercises', []):
        if blocks and item.get('superset') is not None and item['superset'] == blocks[-1][-1].get('superset'):
            blocks[-1].append(item)
        else:
            blocks.append([item])
    for index, block in enumerate(blocks):
        bounds = block_recovery_bounds(block, requirements, definitions)
        for item in block[:-1]:
            item['restAfterExerciseSeconds'] = 0
        if complete_session and index == len(blocks) - 1:
            block[-1]['restAfterExerciseSeconds'] = 0
        elif bounds:
            block[-1]['restAfterExerciseSeconds'] = min(bounds[1], max(bounds[0],
                block[-1].get('restAfterExerciseSeconds', 0)))
EXECUTION_ORDER_POLICY = 'approved_ordering_preferences_and_execution_rules'
EXECUTION_ORDER_DESCRIPTION = ('Only approved executionRules and orderingPreferences establish execution precedence. '
    'phaseOrder groups categories that may interleave; explicit order rules take precedence. '
    'protectionOrder ranks separate cumulative direct/supporting exposure proxies only when execution_order is approved. '
    'Supporting exposure includes explicitly reviewed execution support without granting hypertrophy set credit. '
    'These are organizational and exposure facts, not measured fatigue, recovery or personal capacity. '
    'Equipment economy is a separate ranked objective. Counts or movement-family diversity do not establish ROM, '
    'muscle-length complementarity or personal suitability; missing execution evidence remains unknown.')
_CORE_MUSCLES = frozenset({'FRONT_ABS', 'FRONT_OBLIQUES'})


def execution_block_priority(definitions):
    priorities = []
    for definition in definitions:
        muscles = set(definition.get('muscleGroups', []))
        priorities.append(3 if muscles and muscles <= _CORE_MUSCLES else
            {'HEAVY_COMPOUND': 0, 'MODERATE_COMPOUND': 1, 'ISOLATION': 2}.get(
                definition.get('exerciseCategory'), 0))
    return 3 if 3 in priorities else min(priorities, default=0)


def execution_member_order(definitions, requirements=None):
    return sorted(range(len(definitions)), key=lambda index: (
        execution_order_phase(execution_block_priority([definitions[index]]), requirements)
        if requirements is not None else execution_block_priority([definitions[index]])))


def execution_block_order_key(definitions, counts=None):
    """Stable block identity for producer and audit tie-breaking after reordering."""
    counts = counts or [None] * len(definitions)
    identities = tuple(sorted((str(definition.get('libraryDefinitionId')
        or definition.get('exerciseDefinitionId') or definition.get('definition_id')
        or definition.get('id') or ''), count)
        for definition, count in zip(definitions, counts, strict=True)))
    return execution_block_priority(definitions), identities


def execution_order_predecessors(block_roles, requirements):
    predecessors = {index: set() for index in range(len(block_roles))}
    by_role = {}
    for index, roles in enumerate(block_roles):
        for role in roles:
            by_role.setdefault(role, []).append(index)
    for rule in requirements.get('executionRules', []):
        if rule['kind'] != 'order':
            continue
        for before in by_role.get(rule['before'], []):
            for after in by_role.get(rule['after'], []):
                if before != after:
                    predecessors[after].add(before)
    return predecessors


def execution_order_is_admissible(order, block_roles, order_keys, requirements):
    """Check precedence and allowed phases independently of optimization tie-breaking."""
    if sorted(order) != list(range(len(block_roles))):
        return False
    dependencies = execution_order_predecessors(block_roles, requirements)
    phases = [execution_order_phase(key[0], requirements) for key in order_keys]
    for index in order:
        ready = [candidate for candidate, predecessors in dependencies.items() if not predecessors]
        if index not in ready or phases[index] != min(phases[candidate] for candidate in ready):
            return False
        del dependencies[index]
        for predecessors in dependencies.values():
            predecessors.discard(index)
    return True


def equipment_setup_resources(definitions):
    """Known equipment identities only; this does not establish load/configuration compatibility."""
    resources = set()
    for definition in definitions:
        if definition.get('equipmentId'):
            resources.add(definition['equipmentId'])
        resources.update(definition.get('requiredAccessoryEquipmentIds') or [])
    return frozenset(resources)


def superset_resource_relation(first, second, equipment_by_id):
    """Classify only what equipment IDs and structured equipment types establish."""
    first_id, second_id = first.get('equipmentId'), second.get('equipmentId')
    if not first_id and not second_id:
        return 'no_primary_equipment'
    if not first_id or not second_id:
        unassigned = second if not second_id else first
        if unassigned.get('exerciseType') == 'BODY_WEIGHT' and not unassigned.get('requiresLoadCalibration'):
            return 'no_primary_equipment'
        return 'identity_unknown'
    if first_id == second_id:
        return 'same_record'
    first_gear, second_gear = equipment_by_id.get(first_id), equipment_by_id.get(second_id)
    if not first_gear or not second_gear:
        return 'identity_unknown'
    first_type, second_type = first_gear.get('type'), second_gear.get('type')
    if not first_type or not second_type:
        return 'identity_unknown'
    # The app models these as single-implement and paired-implement dumbbell
    # variants; distinct records do not prove independent physical inventory.
    dumbbell_types = {'DUMBBELL', 'DUMBBELLS'}
    if first_type == second_type or {first_type, second_type} <= dumbbell_types:
        return 'potentially_shared_family'
    return 'different_family_types'


def shared_superset_station_group(first, second, requirements, first_coverage=None, second_coverage=None):
    """Return an explicitly approved resource group touched by both exercises."""
    first_resources = {first.get('equipmentId'), *(first.get('requiredAccessoryEquipmentIds') or [])} - {None}
    second_resources = {second.get('equipmentId'), *(second.get('requiredAccessoryEquipmentIds') or [])} - {None}
    groups = []
    for rule in requirements.get('executionRules', []):
        if rule.get('kind') != 'supersetNoReconfiguration':
            continue
        coverage_key = rule.get('coverageKey')
        if (coverage_key is not None and first_coverage is not None and second_coverage is not None
                and coverage_key not in first_coverage and coverage_key not in second_coverage):
            continue
        for values in rule.get('sharedResourceGroups', []):
            group = set(values)
            if len(group) < 2:
                continue
            overlaps = [index for index, existing in enumerate(groups) if existing & group]
            for index in reversed(overlaps):
                group.update(groups.pop(index))
            groups.append(group)
    return next((frozenset(group) for group in groups
        if first_resources & group and second_resources & group), None)


def superset_setup_compatibility(first, second, requirements, first_coverage=None, second_coverage=None):
    """A resource conflict overrides access confirmation; equipment types never confirm access."""
    shared = shared_superset_station_group(first, second, requirements, first_coverage, second_coverage)
    if shared:
        return {'status': 'incompatible', 'sharedResourceGroup': sorted(shared)}
    policies = [rule for rule in requirements.get('executionRules', [])
        if rule.get('kind') == 'supersetNoReconfiguration' and 'confirmedIndependentPairs' in rule
        and (rule.get('coverageKey') is None or rule['coverageKey'] in (first_coverage or [])
             or rule['coverageKey'] in (second_coverage or []))]
    pair = frozenset(definition.get('libraryDefinitionId') or definition.get('id')
                     for definition in (first, second))
    confirmed = bool(policies) and len(pair) == 2 and all(
        pair in [frozenset(values) for values in rule['confirmedIndependentPairs']] for rule in policies)
    return {'status': 'compatible' if confirmed else 'unknown', 'confirmationRequired': bool(policies)}


def bind_confirmed_superset_access(requirements, equipment, confirmations, sources):
    """Bind confirmed independent configurations to their declared retained station resources."""
    result = copy.deepcopy(requirements)
    definitions = {item['id']: item for item in equipment.get('exerciseDefinitions', [])}
    available_resources = {item['id'] for key in ('equipments', 'accessoryEquipments')
        for item in equipment.get(key, [])}
    bindings = []
    for confirmation in confirmations:
        shared = confirmation.get('confirmedSharedStation')
        if shared is None:
            continue
        references = confirmation['sourceReferences']
        if (len(set(shared)) < 2 or len(shared) != len(set(shared))
                or not set(shared) <= available_resources or not references
                or any(reference not in sources or sources[reference].get('role') != 'user'
                       for reference in references)):
            raise ValueError('A shared station confirmation requires current resources and user sources.')
        for rule in result.get('executionRules', []):
            if rule.get('kind') == 'supersetNoReconfiguration':
                groups = rule.setdefault('sharedResourceGroups', [])
                if set(shared) not in [set(group) for group in groups]:
                    groups.append(sorted(shared))
    for confirmation in confirmations:
        if 'independentDefinitionIds' not in confirmation:
            continue
        independent = confirmation['independentDefinitionIds']
        retained = set(confirmation['retainedResourceIds'])
        references = confirmation['sourceReferences']
        if (not independent or not retained or not references
                or len(independent) != len(set(independent))
                or not set(independent) <= definitions.keys()
                or not retained <= available_resources
                or any(reference not in sources or sources[reference].get('role') != 'user'
                       for reference in references)):
            raise ValueError('Setup access confirmation requires current configurations, resources and user sources.')
        for identifier in independent:
            first = definitions[identifier]
            if equipment_setup_resources([first]) & retained:
                raise ValueError('An independent configuration cannot use the retained station resources.')
            for second_id, second in sorted(definitions.items()):
                resources = equipment_setup_resources([second])
                if (identifier == second_id or not resources or not resources <= retained
                        or shared_superset_station_group(first, second, result)):
                    continue
                pair = sorted([identifier, second_id])
                for index, rule in enumerate(result.get('executionRules', [])):
                    if rule.get('kind') != 'supersetNoReconfiguration':
                        continue
                    pairs = rule.setdefault('confirmedIndependentPairs', [])
                    if frozenset(pair) not in {frozenset(values) for values in pairs}:
                        pairs.append(pair)
                    bindings.append({'pair': pair,
                        'independentDefinitionId': identifier, 'retainedResourceIds': sorted(retained),
                        'sourceReferences': list(references),
                        'requirementPath': f'/requirements/executionRules/{index}/confirmedIndependentPairs'})
    return {'requirements': result, 'bindings': bindings}


def movement_overlap_roles(roles):
    """Shared planes, parent coverage and limb modes do not establish redundant work."""
    return set(roles) & {'knee_dominant', 'hip_dominant', 'knee_flexion_hamstring',
        'horizontal_push', 'horizontal_pull', 'vertical_push', 'vertical_pull',
        'lateral_movement', 'rotational_core'}


def execution_priority_rank(roles, requirements):
    priorities = {rule['before'] for rule in requirements.get('executionRules', [])
                  if rule.get('kind') == 'order'}
    return 0 if set(roles) & priorities else 1



def superset_lower_body_pair_sets(definitions, counts):
    """Raw paired sets involving two major lower-body movements, not predicted fatigue."""
    lower_body = {'quads', 'hamstrings', 'glutes'}
    members = [index for index, definition in enumerate(definitions)
        if any(muscle in lower_body and tags & set(definition.get('muscleGroups', []))
            for muscle, tags in MUSCLES.items())]
    return sum(min(counts[first], counts[second]) for first, second in combinations(members, 2))


def execution_interference_profile(definitions, counts, roles, requirements):
    primary, supporting = Counter(), Counter()
    heavy_primary, heavy_supporting = set(), set()
    main_primary, main_supporting = set(), set()
    primary_known = True
    support_evidence = []
    for definition, count in zip(definitions, counts, strict=True):
        direct = {muscle for muscle, tags in MUSCLES.items()
                  if tags & set(definition.get('muscleGroups', []))}
        secondary = {muscle for muscle, tags in MUSCLES.items()
                     if tags & set(definition.get('secondaryMuscleGroups', []))} - direct
        # Execution support is a sequencing fact, separate from muscle-volume credits.
        execution_support = execution_supporting_muscles(definition)
        execution = definition.get('reviewedExecution') or {}
        support_evidence.append({'definitionId': definition.get('id'),
            'status': 'documented_non_exhaustive' if execution_support is not None else 'unknown',
            'supportingMuscles': sorted(execution_support) if execution_support is not None else None,
            **({key: execution[key] for key in ('source', 'basis')} if execution_support is not None else {})})
        if execution_support is not None:
            secondary.update(execution_support - direct)
        primary_known = primary_known and bool(direct)
        primary.update(dict.fromkeys(direct, count))
        supporting.update(dict.fromkeys(secondary, count))
        if definition.get('exerciseCategory') in {'HEAVY_COMPOUND', 'MODERATE_COMPOUND'}:
            main_primary.update(direct)
            main_supporting.update(secondary)
        if definition.get('exerciseCategory') == 'HEAVY_COMPOUND':
            heavy_primary.update(direct)
            heavy_supporting.update(secondary)
    return {'primary': dict(primary), 'supporting': dict(supporting), 'primaryKnown': primary_known,
            'executionSupportEvidence': support_evidence,
            'supportingCountsMeaning': 'Library secondary tags plus documented execution support only; '
                'counts are lower bounds on recorded overlap. Unlisted support is unknown, not absent. '
                'Positive annotations are not exhaustive or physiological fatigue estimates.',
            'priority': execution_priority_rank(roles, requirements) == 0,
            'heavy_primary': sorted(heavy_primary), 'heavy_supporting': sorted(heavy_supporting),
            'main_primary': sorted(main_primary), 'main_supporting': sorted(main_supporting),
            'main_compound': any(definition.get('exerciseCategory') in {'HEAVY_COMPOUND', 'MODERATE_COMPOUND'}
                                 for definition in definitions)}


def execution_interference_score(order, profiles, requirements=None):
    """Protect explicit priorities, then heavy/main work, before adjacent overlap."""
    primary, supporting = Counter(), Counter()
    priority_direct = priority_support = adjacent_direct = adjacent_support = 0
    heavy_direct, heavy_support, main_direct, main_support = [], [], [], []
    previous = None
    for index in order:
        profile = profiles[index]
        direct, secondary = profile['primary'], profile['supporting']
        prior_direct = sum(primary[muscle] for muscle in direct)
        prior_support = (sum(supporting[muscle] for muscle in direct)
            + sum(primary[muscle] + supporting[muscle] for muscle in secondary if muscle not in direct))
        if profile['priority']:
            priority_direct += prior_direct
            priority_support += prior_support
        if profile['heavy_primary']:
            heavy_direct.append(sum(primary[muscle] for muscle in profile['heavy_primary']))
            heavy_support.append(sum(supporting[muscle] for muscle in profile['heavy_primary'])
                + sum(primary[muscle] + supporting[muscle] for muscle in profile['heavy_supporting']
                      if muscle not in profile['heavy_primary']))
        if profile['main_compound']:
            main_direct.append(sum(primary[muscle] for muscle in profile['main_primary']))
            main_support.append(sum(supporting[muscle] for muscle in profile['main_primary'])
                + sum(primary[muscle] + supporting[muscle] for muscle in profile['main_supporting']
                      if muscle not in profile['main_primary']))
        if previous is not None:
            adjacent_direct += sum(previous['primary'].get(muscle, 0) for muscle in direct)
            adjacent_support += (sum(previous['supporting'].get(muscle, 0) for muscle in direct)
                + sum(previous['primary'].get(muscle, 0) + previous['supporting'].get(muscle, 0)
                      for muscle in secondary if muscle not in direct))
        primary.update(direct)
        supporting.update(secondary)
        previous = profile
    values = (priority_direct, priority_support, max(heavy_direct, default=0), max(heavy_support, default=0),
        max(main_direct, default=0), max(main_support, default=0), adjacent_direct, adjacent_support)
    if requirements is None:
        return values
    facts = dict(zip(INTERFERENCE_METRICS, values, strict=True))
    facts.update(heavy_direct_total=sum(heavy_direct), heavy_support_total=sum(heavy_support),
        main_direct_total=sum(main_direct), main_support_total=sum(main_support))
    return tuple(facts[name] for name in execution_interference_metric_names(requirements))


def _setup_resource_groups(requirements):
    return [group for rule in requirements.get('executionRules', [])
        if rule.get('kind') == 'supersetNoReconfiguration'
        for group in rule.get('sharedResourceGroups', [])]


def execution_order_indices(block_roles, order_keys, requirements, setup_resources=None, interference_profiles=None, setup_profiles=None, setup_rounds=None):
    dependencies = execution_order_predecessors(block_roles, requirements)
    ordered = []
    preferences = requirements.get('objectiveOrder') or []
    overlap = 'movement_overlap' in preferences
    score_interference = ('execution_order' in preferences and interference_profiles
                          and all(profile['primaryKnown'] for profile in interference_profiles))
    score_setup = 'setup_economy' in preferences and setup_profiles is not None
    setup_first = (any(goal['metric'] == 'setup_economy'
        for tier in requirements.get('objectiveTiers', []) for goal in tier)
        or 'setup_economy' in preferences and 'execution_order' in preferences
        and preferences.index('setup_economy') < preferences.index('execution_order'))
    shared_groups = _setup_resource_groups(requirements)
    setup_blocks = ([{'profiles': profiles,
        'rounds': setup_rounds[index] if setup_rounds is not None else 1,
        'componentIndex': index, 'exerciseRefs': [],
        'kind': 'superset' if len(profiles) > 1 else 'exercise'}
        for index, profiles in enumerate(setup_profiles)] if score_setup else [])
    resource_only_setup = ('setup_economy' in preferences and setup_resources is not None
        and setup_profiles is None)
    priority = [execution_priority_rank(roles, requirements) for roles in block_roles]
    while dependencies:
        ready = [index for index, predecessors in dependencies.items() if not predecessors]
        if not ready:
            raise ValueError('Selected recipe ordering is cyclic.')
        if ordered and (overlap or resource_only_setup):
            previous = ordered[-1]
            index = min(ready, key=lambda index: (
                execution_order_phase(order_keys[index][0], requirements),
                priority[index] if overlap else 1,
                int(bool(movement_overlap_roles(block_roles[previous])
                         & movement_overlap_roles(block_roles[index]))) if overlap else 0,
                len(setup_resources[previous] ^ setup_resources[index])
                    if resource_only_setup
                    and not score_interference else 0,
                order_keys[index][1:], index))
        else:
            index = min(ready, key=lambda index: (execution_order_phase(order_keys[index][0], requirements),
                priority[index] if overlap else 1, *order_keys[index][1:], index))
        ordered.append(index)
        del dependencies[index]
        for predecessors in dependencies.values():
            predecessors.discard(index)
    if not score_interference and not score_setup:
        return ordered

    scores = {}

    def score(order):
        key = tuple(order)
        if key in scores:
            return scores[key]
        setup = switches = ()
        if score_setup:
            evidence = _setup_evidence_for_blocks([setup_blocks[index] for index in order], shared_groups)
            setup = (evidence['physicalPreparationCount'], evidence['physicalRequiredChanges'])
            if evidence['physicalPrimaryInventorySwitchCount'] is not None:
                switches = (evidence['physicalPrimaryInventorySwitchCount'],)
        interference = execution_interference_score(order, interference_profiles, requirements) if score_interference else ()
        if setup_first and selection_precedes_execution(requirements) and setup:
            scores[key] = (setup[0], *interference, setup[1], *switches)
        else:
            scores[key] = ((*setup, *interference, *switches) if setup_first
                else (*interference, *setup, *switches))
        return scores[key]

    # Precedence and phases constrain the opener; its stable identity does not.
    while True:
        best, best_score = ordered, score(ordered)
        for first, second in combinations(range(len(ordered)), 2):
            first_phase, second_phase = (order_keys[ordered[index]][0] for index in (first, second))
            if execution_order_phase(first_phase, requirements) != execution_order_phase(second_phase, requirements):
                continue
            candidate = ordered.copy()
            candidate[first], candidate[second] = candidate[second], candidate[first]
            if not execution_order_is_admissible(candidate, block_roles, order_keys, requirements):
                continue
            value = score(candidate)
            if value < best_score:
                best, best_score = candidate, value
        if best is ordered and score_interference:
            main_positions = [position for position in range(len(ordered))
                              if order_keys[ordered[position]][0] < 2]
            # shortcut: above seven movable main blocks keep local search; widen only with a measured search budget.
            if 1 < len(main_positions) <= 7:
                for arrangement in permutations(ordered[position] for position in main_positions):
                    candidate = ordered.copy()
                    for position, index in zip(main_positions, arrangement, strict=True):
                        candidate[position] = index
                    if not execution_order_is_admissible(candidate, block_roles, order_keys, requirements):
                        continue
                    value = score(candidate)
                    if value < best_score:
                        best, best_score = candidate, value
            return best
        if best is ordered:
            return ordered
        ordered = best


def canonical_execution_order_draft(draft, requirements, equipment):
    """Apply the audited block/member order without changing exercise prescriptions."""
    ordered_draft = copy.deepcopy(draft)
    definitions = {f'LIBRARY_{index}': definition for index, definition in enumerate(
        sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id']))}
    shared_groups = _setup_resource_groups(requirements)
    equipment_by_id = {gear['id']: gear for gear in equipment.get('equipments', [])}
    for day in ordered_draft.get('workouts', []):
        source_exercises = day.get('exercises', [])
        blocks = []
        for index, item in enumerate(source_exercises):
            same_group = (index > 0 and item.get('superset') is not None
                and item.get('superset') == source_exercises[index - 1].get('superset'))
            if same_group:
                blocks[-1].append(index)
            else:
                blocks.append([index])

        reordered_blocks = []
        block_roles = []
        order_keys = []
        profiles = []
        for block in blocks:
            members = [source_exercises[index] for index in block]
            member_definitions = [definitions.get(item.get('definition_id'), {}) for item in members]
            member_order = execution_member_order(member_definitions, requirements)
            if len(block) > 1:
                rest_slots = [(members[index].get('restAfterSupersetExerciseSeconds'),
                               members[index].get('restAfterExerciseSeconds'))
                              for index in range(len(members))]
            else:
                rest_slots = []
            ordered_members = [copy.deepcopy(members[index]) for index in member_order]
            for slot_index, member in enumerate(ordered_members):
                if rest_slots:
                    member['restAfterSupersetExerciseSeconds'], member['restAfterExerciseSeconds'] = rest_slots[slot_index]
            reordered_blocks.append(ordered_members)
            block_roles.append(set().union(*(set(item.get('satisfiesCoverage', [])) for item in members)))
            order_keys.append(execution_block_order_key(member_definitions,
                [source_exercises[index]['numWorkSets'] for index in block]))
            profiles.append(execution_interference_profile(member_definitions,
                [item['numWorkSets'] for item in members], block_roles[-1], requirements))

        try:
            block_order = execution_order_indices(block_roles, order_keys, requirements,
                [equipment_setup_resources([definitions.get(item.get('definition_id'), {})
                    for item in members]) for members in reordered_blocks], profiles,
                [[setup_resource_profile(definitions.get(item.get("definition_id"), {}), item,
                    shared_groups, equipment_by_id)
                    for item in members] for members in reordered_blocks],
                [min(item['numWorkSets'] for item in members) for members in reordered_blocks])
        except ValueError:
            return None
        day['exercises'] = [item for block_index in block_order for item in reordered_blocks[block_index]]
        prescribe_block_recovery(day, requirements, definitions)
    return ordered_draft


def is_canonical_execution_order_change(before, after, requirements, equipment):
    """True only when the entire draft change is the shared deterministic ordering repair."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    canonical = canonical_execution_order_draft(before, requirements, equipment)
    return canonical is not None and canonical != before and canonical == after


def _rule(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


EXECUTION_RULES_SCHEMA = {'type': 'array', 'maxItems': 30,
    'description': 'Extract explicit user execution constraints and any programming choices the original source explicitly delegates. Do not invent universal exercise caps or defaults. An approved exerciseExposure rule applies the selected limits to each exact library definition; variants with the same definition ID share exposure, and separate IDs are independent. Use requiredCoverage for source-backed roles such as priority lifts. Never turn general recommendations into mandatory requirements. Order is checked within each session where both roles occur; earlier blocks must finish before later blocks. Rest ranges are inclusive, and apply only to rests the app actually executes: straightSets and supersetRound require at least two working sets; supersetTransition executes once per round even with one working set.',
    'items': {'oneOf': [
        _rule({'kind': {'const': 'sessionStructure'},
               'maximumExercises': {'type': 'integer', 'minimum': 1, 'maximum': 100},
               'maximumSupersets': {'type': 'integer', 'minimum': 0, 'maximum': 50},
               'maximumSupersetSize': {'type': 'integer', 'minimum': 2, 'maximum': 100}}, ['kind']),
        _rule({'kind': {'const': 'order'}, 'before': _COVERAGE, 'after': _COVERAGE}, ['kind', 'before', 'after']),
        _rule({'kind': {'const': 'coverageBalance'}, 'first': _COVERAGE, 'second': _COVERAGE,
               'scope': {'enum': ['weekly', 'eachSession']},
               'relationship': {'enum': ['balanced', 'first_not_less_than_second'],
                   'description': 'Use balanced only for a source-backed balance request. Use first_not_less_than_second only when the source explicitly prioritizes the first role at least as much as the second; this is a soft comparison, never a ratio or quota.'}},
              ['kind', 'first', 'second', 'scope']),
        # Disjoint object shapes support either/both caps under strict provider delivery.
        *[_rule({'kind': {'const': 'exerciseExposure'},
                 **{field: {'type': 'integer', 'minimum': 0} for field in fields}}, ['kind', *fields])
          for fields in (('maximumSessionsPerWeek',), ('maximumWeeklySets',),
                         ('maximumSessionsPerWeek', 'maximumWeeklySets'))],
        _rule({'kind': {'const': 'straightSets'}, 'coverageKey': _COVERAGE}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'warmup'}, 'coverageKey': _COVERAGE}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'workSets'}, 'coverageKey': _SELECTOR,
               'exerciseCategory': {'enum': ['HEAVY_COMPOUND', 'MODERATE_COMPOUND', 'ISOLATION']},
               'minimumSets': {'type': 'integer', 'minimum': 1, 'maximum': 20},
               'maximumSets': {'type': 'integer', 'minimum': 1, 'maximum': 20}},
              ['kind', 'coverageKey', 'minimumSets', 'maximumSets']),
        _rule({'kind': {'const': 'supersetNoReconfiguration',
            'description': 'Keep the same shared-equipment load between superset partners; Python checks compatible prescribed loads. Native per-exercise calibration does not establish a shared load. Optional sharedResourceGroups lists code-enumerated equipment/accessory ID groups that are one physical station; two exercises using resources in the same group cannot be paired in a superset.'},
            'sharedResourceGroups': {'type': 'array', 'items': {'type': 'array', 'minItems': 2,
                'uniqueItems': True, 'items': {'type': 'string', 'minLength': 1}}},
            'confirmedIndependentPairs': {'type': 'array', 'uniqueItems': True,
                'description': 'When present, only these user-confirmed pairs of immutable exercise-definition IDs have independent simultaneous access. An empty list confirms no pairs. This does not establish compatible loads or measured changeover time.',
                'items': {'type': 'array', 'minItems': 2, 'maxItems': 2, 'uniqueItems': True,
                    'items': {'type': 'string', 'minLength': 1}}},
            'coverageKey': _SELECTOR}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'rest'}, 'coverageKey': _SELECTOR,
               'exerciseCategory': {'enum': ['HEAVY_COMPOUND', 'MODERATE_COMPOUND', 'ISOLATION']},
               'context': {'enum': ['straightSets', 'supersetTransition', 'supersetRound', 'exerciseTransition']},
               'minimumSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 1800},
               'maximumSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 1800}},
              ['kind', 'coverageKey', 'context', 'minimumSeconds', 'maximumSeconds']),
    ]}}

# Shared by planner and independent reviewer; no additional model call.
GUIDELINE_POLICY = {
    'version': 12,
    'goalAuthority': 'Apply programming preferences to the approved structured requirements and original source instructions. Training goals are not interchangeable. A weekly muscle target creates no direct-work or each-session coverage requirement. Only explicit requiredCoverage scopes and qualified roles establish coverage. Direct and substantial secondary credits contribute to effective volume; incidental stabilization receives no credit. Balance the settled weekly doses by reducing the worst per-muscle session imbalance before aggregate imbalance, while preserving weekly ranges and higher-ranked priorities. If explicit approved coverage is infeasible, report the conflict rather than silently dropping it. Distinguish requested inclusion from development emphasis: `requiredCoverage.intent=inclusion` establishes presence only; `development` marks a source-backed purpose for semantic assessment. Development intent does not create an extra-set bonus or a numeric floor: only explicit `minimumWeeklySets` and `minimumSessions` fields establish floors, and additional development-emphasis/exposure objectives run only when explicitly listed in the authoritative `objectiveOrder`. `workload_economy` is a soft preference to minimize total physical weekly working sets after higher-ranked preferences; it cannot change user-owned numbers or hard constraints. A source-backed coverageBalance relationship may express balanced exposure or that the first role should not receive less exposure than the second; neither defines a ratio or hard minimum. Compare direct and weighted secondary contributions; regional stimulus needs supported execution evidence. The app owns progression and load calibration. Clarify only material source ambiguity; do not invent user requirements or numeric thresholds for qualitative goals. Apply code-owned defaults only when shown in the approved requirements. Recommendations never authorize compromise; `objectiveOrder` is authoritative and omitted preferences do not run.',
    'deterministic': 'New requirements candidates include the application policy of at least two working sets per selected exercise occurrence, at most 15 exercise occurrences per session including every superset member, and at most three exercises per superset. These session limits apply to the selected plan, not the candidate pool. Aggregate muscle roles are derived from each library definition’s primary muscleGroups; eachSession requirements for aggregate muscle roles require primary contributions, not secondary credit. Only minimum/maximum fields establish hard effective-set bounds; preferredMinimum/preferredMaximum are soft ranges and missed preferences are disclosed tradeoffs. preferredSessionSeconds is a soft budget separate from the hard maximum. exerciseSelection counts distinct qualified definitions across the week using direct or substantial secondary credit and does not prove complementarity. If these floors cannot fit the approved exercise library and other hard requirements, expose the infeasibility for a scoped decision. The existing working-set cap of 20 is a numeric domain limit, not a training recommendation. The approved rules are shown for approval and shared by selection and audit. Existing approved requirements are not retroactively changed. Other executionRules enforce explicit working-set limits, exercise-block order, straight sets, generated ramp-ups and rest ranges. Selectors use requiredCoverage assignments; code derives aggregate muscle roles from primary tags and the independent reviewer verifies semantic movement roles. Volume, time, load suitability and required coverage use the existing audits.',
    'review': [
        'Prescription authority: structured fields own rep ranges, rest intervals and loading configuration. Python renders the standard working-set underperformance stop/re-audit rule; it is fixed behavior, not a local-note repair. Preserve source-backed movement-specific technique and safety cues. Assess only rests the app executes: a straightSets restBetweenSetsSeconds field does not represent an executed rest when numWorkSets is 1, and a superset-round rest is likewise inactive for one round. Do not repair an inactive between-set/round rest field; check actual prescribed recovery during every executed interval. In notes, refer to the prescribed range/rest instead of repeating those numbers. Explain only execution and acceptance details not already represented. A note contradicting a structured prescription is an established violation, not uncertainty. New loading configurations or exercise variants require selection and re-audit before use.',
        'Execution capabilities: every working, warm-up, calibration, assistance, progression and fallback action must use confirmed equipment and available help. Describe bodyweight assistance operationally; an unspecified assistance setting does not establish a usable method. A re-audit instruction does not authorize using new gear, help or a different movement before confirmation and validation. Unavailable alternatives may be proposed for confirmation, never prescribed as executable fallbacks. The app owns native load calibration; generator notes must not add a second calibration procedure. Conflicting instructions are blocking, not merely uncertain load suitability.',
        'Sequencing compliance: the shared deterministic audit owns only approved orderingPreferences and explicit executionRules, for whole blocks and superset members. Do not raise a sequencing-rule finding after that audit passes. Use the audited sequence only when assessing fatigue or whether earlier work materially undermines a stated priority. Core-only status uses primary muscle groups, not secondary credits.',
        'Fatigue and recovery: assess the complete week, not just each muscle total. Trace repeated demands on prime movers, grip, trunk bracing and spinal loading through exercise order, working-set counts, effort, rest and actual scheduled recovery. Include eccentric/unfamiliar work and how earlier fatigue may limit later technical or priority lifts. Ground each concern in supplied movement definitions, prescriptions and comparable history; do not infer spinal loading or recovery from muscle credits alone. No universal ban on consecutive compounds, fixed exercise count, fatigue score or invented recovery threshold. Do not infer actual weekday spacing from frequency alone.',
    'Fatigue management: prefer distributing demanding exposures, reducing redundant work, using a supported less fatiguing variant, or changing order/pairing before changing approved targets. Sequence support counts include sourced execution-support facts without adding muscle-volume credit or estimating fatigue/recovery; missing facts remain unknown. Preserve the approved training goal, practical progression, equipment feasibility and numerical constraints. Do not claim a token rest day, different exercise name or a generic recovery note resolves repeated loading. When evidence makes feasibility materially uncertain, repair the exercise selection or supported prescription conservatively; never silently count reduced fallback volume toward the original target.',
    'Supersets and rest: assess each pairing in its full session and repeated interleaved rounds, using the code-computed prior primary/supporting exposure before each member; do not judge pair compatibility in isolation. Verify physical setup and recovery between successive sets of each member, including partner work. Use supported equipment transitions, unilateral execution and timing assumptions to assess practicality; similar duration does not establish similar fatigue. Recurring setup transitions are counted as occurrences but have no measured physical duration unless explicitly estimated. Do not double-count setup time, prohibit all supersets or impose antagonist-only pairings. Enforce source-backed setup/rest constraints.',
        'Progression: use comparable history and selectable resistance. Do not transfer loads across variants as proven equivalents. The app owns progression; use native requiresLoadCalibration for unknown starting loads; neither mandatory rep drop-off nor increasing load every week proves adequate effort.',
        'Warm-ups and effort: match preparation to the planned demand and account for stated tempo, setup and prescribed warm-ups in timing; native calibration mode is not an additional generator-prescribed activity. A warm-up flag cannot prove preparation is sufficient, and prescribed sets cannot prove actual effort.',
        'For supported exercises without usable comparable load history, enable the existing app requiresLoadCalibration mode. The app owns load selection and calibration behavior. Do not require numeric starting loads, trial counts, search strategies, separate trial sets, calibration notes or invented recovery overhead. Missing comparable history alone is not an exercise-selection defect or proof of infeasibility. Native calibration does not prove future measured effort; continue checking actual equipment eligibility and explicit source requirements.',
    ],
    'severity': 'Established requirement violations, contradictions and unsupported material claims block. Material uncertainty also blocks when cited plan/evidence leaves a required outcome unverifiable and no adequate mitigation exists; identify the affected requirement, interacting exposures or missing evidence, consequence and smallest permitted resolution. Mere possibility of fatigue, absent historical RIR, individual response variation or a preferred alternative alone is an advisory warning, not a veto. Native load calibration handles unknown starting loads without a generator-authored protocol; it cannot prove actual stimulus in advance. Ask only about genuine user ambiguity; do not invent targets, universal fatigue limits or silently rewrite requirements.',
    'sources': [
        'https://pmc.ncbi.nlm.nih.gov/articles/PMC12965823/',
        'https://pubmed.ncbi.nlm.nih.gov/32077380/',
        'https://pmc.ncbi.nlm.nih.gov/articles/PMC12011898/',
    ],
}


def execution_rule_errors(requirements, equipment=None):
    """Validate links and bounds before a rule can be presented for approval."""
    coverage = {item['key'] for item in requirements.get('requiredCoverage', [])}
    errors = []
    effort = requirements.get('workingSetRIR')
    if effort and effort['minimum'] > effort['maximum']:
        errors.append({'code': 'invalid_effort_range', 'path': '/workingSetRIR', 'message': 'Minimum RIR exceeds maximum RIR.',
                       'repair': 'Correct the effort range against the user instructions; do not invent a new effort target.'})
    exercise_exposure_rules = [(index, rule) for index, rule in enumerate(requirements.get('executionRules', []))
                                if rule.get('kind') == 'exerciseExposure']
    if len(exercise_exposure_rules) > 1:
        errors.append({'code': 'duplicate_exercise_exposure_rule',
            'path': f'/executionRules/{exercise_exposure_rules[1][0]}',
            'message': 'Use one global exercise exposure rule for all exact library exercise definitions.',
            'repair': 'Combine the approved session and weekly-set caps in one exerciseExposure rule.'})
    for index, rule in enumerate(requirements.get('executionRules', [])):
        path = f'/executionRules/{index}'
        keys = ([] if rule['kind'] in ('sessionStructure', 'exerciseExposure') else
                [rule['first'], rule['second']] if rule['kind'] == 'coverageBalance' else
                [rule['before'], rule['after']] if rule['kind'] == 'order' else [rule['coverageKey']])
        missing = set(keys) - coverage - {None}
        reason = f'Coverage keys not declared in requiredCoverage: {sorted(missing)}.' if missing else None
        if rule['kind'] == 'sessionStructure' and not any(key in rule for key in (
                'maximumExercises', 'maximumSupersets', 'maximumSupersetSize')):
            reason = 'A session structure rule must specify at least one upper bound.'
        if rule['kind'] == 'exerciseExposure' and not any(key in rule for key in (
                'maximumSessionsPerWeek', 'maximumWeeklySets')):
            reason = 'An exercise exposure rule must specify a session cap, a weekly set cap, or both.'
        if rule['kind'] == 'order' and rule['before'] == rule['after']:
            reason = 'An execution role cannot precede itself.'
        if rule['kind'] == 'coverageBalance' and rule['first'] == rule['second']:
            reason = 'A coverage comparison requires two different roles.'
        if (rule['kind'] == 'coverageBalance'
                and rule.get('relationship', 'balanced') not in ('balanced', 'first_not_less_than_second')):
            reason = 'The coverage comparison relationship is unsupported.'
        if rule['kind'] == 'rest' and rule['minimumSeconds'] > rule['maximumSeconds']:
            reason = 'Minimum rest exceeds maximum rest.'
        if rule['kind'] == 'workSets' and rule['minimumSets'] > rule['maximumSets']:
            reason = 'Minimum working sets exceeds maximum working sets.'
        if rule['kind'] == 'supersetNoReconfiguration' and 'sharedResourceGroups' in rule:
            groups = rule['sharedResourceGroups']
            available = ({item.get('id') for key in ('equipments', 'accessoryEquipments')
                for item in (equipment or {}).get(key, []) if isinstance(item, dict) and item.get('id')}
                if equipment is not None else None)
            invalid_refs = sorted({reference for group in groups for reference in group
                if available is not None and reference not in available})
            if invalid_refs:
                reason = f'Shared resource groups reference equipment IDs not in the loaded inventory: {invalid_refs}.'
            elif any(len(set(group)) < 2 for group in groups):
                reason = 'Each shared resource group must identify at least two distinct equipment or accessory resources.'
        if rule['kind'] == 'supersetNoReconfiguration' and 'confirmedIndependentPairs' in rule and equipment is not None:
            available = {definition.get('id') for definition in equipment.get('exerciseDefinitions', [])}
            invalid_refs = sorted({reference for pair in rule['confirmedIndependentPairs']
                                   for reference in pair if reference not in available})
            if invalid_refs:
                reason = f'Confirmed access pairs reference unknown exercise-definition IDs: {invalid_refs}.'
        if reason:
            error = {'code': 'invalid_execution_rule', 'path': path, 'message': reason,
                     'repair': 'Correct the rule using existing source-backed requiredCoverage keys and valid bounds. Ask if the requested execution is ambiguous; do not invent a role or relax requirements.'}
            if missing:
                error['repair'] = ('Reference a declared requiredCoverage key, or declare a supported role there when the original source explicitly requires it. '
                    'An undeclared reference does not mean the role is unavailable. Do not substitute a different movement role or relax the source requirement.')
                error['allowedCoverageKeys'] = sorted(coverage)
                error['invalidReferences'] = {field: value for field, value in rule.items()
                    if field in ('first', 'second', 'before', 'after', 'coverageKey') and value in missing}
            errors.append(error)
    work_set_rules = [(index, rule) for index, rule in enumerate(requirements.get('executionRules', []))
                      if rule['kind'] == 'workSets' and rule['minimumSets'] <= rule['maximumSets']]
    for position, (index, rule) in enumerate(work_set_rules):
        for other_index, other in work_set_rules[position + 1:]:
            coverage_overlaps = (rule['coverageKey'] is None or other['coverageKey'] is None
                                 or rule['coverageKey'] == other['coverageKey'])
            category_overlaps = (rule.get('exerciseCategory') is None or other.get('exerciseCategory') is None
                                 or rule['exerciseCategory'] == other['exerciseCategory'])
            minimum = max(rule['minimumSets'], other['minimumSets'])
            maximum = min(rule['maximumSets'], other['maximumSets'])
            if coverage_overlaps and category_overlaps and minimum > maximum:
                errors.append({'code': 'conflicting_execution_rules', 'path': f'/executionRules/{other_index}',
                    'message': f'Overlapping working-set rules at /executionRules/{index} and /executionRules/{other_index} have no compatible set count.',
                    'repair': 'Resolve the conflicting set-count constraints before approval; preserve the code-owned two-set minimum.'})
    return errors


def render_execution_rule(rule):
    kind = rule['kind']
    if kind == 'exerciseExposure':
        limits = []
        if 'maximumSessionsPerWeek' in rule:
            limits.append(f"at most {rule['maximumSessionsPerWeek']} scheduled sessions per week")
        if 'maximumWeeklySets' in rule:
            limits.append(f"at most {rule['maximumWeeklySets']} working sets per week")
        return ('For each exact library exercise definition, ' + ' and '.join(limits)
            + '; equipment or recipe variants sharing that definition share the cap, while separate definition IDs are counted separately.')
    if kind == 'sessionStructure':
        labels = {'maximumExercises': 'exercise occurrences per session (including every superset member)',
                  'maximumSupersets': 'superset groups per session',
                  'maximumSupersetSize': 'exercises per superset'}
        return '; '.join(f'At most {rule[key]} {label}' for key, label in labels.items() if key in rule) + '.'
    if kind == 'coverageBalance':
        scope = 'over the week' if rule['scope'] == 'weekly' else 'within each session'
        if rule.get('relationship', 'balanced') == 'first_not_less_than_second':
            return (f"Prefer `{rule['first']}` to receive at least as much exposure as `{rule['second']}` {scope}; "
                    'this is a source-backed comparison, not a fixed ratio or hard minimum.')
        return f"Balance `{rule['first']}` with `{rule['second']}` {scope}. Assess comparable exposure under the approved priority policy; no numerical tolerance was specified."
    if kind == 'order':
        return f"`{rule['before']}` blocks before `{rule['after']}` blocks (when both occur in a session)."
    selector = f"`{rule['coverageKey']}`" if rule['coverageKey'] else 'All applicable exercises'
    if kind == 'workSets':
        category = f" ({rule['exerciseCategory']})" if rule.get('exerciseCategory') else ''
        text = f"{selector}{category}: {rule['minimumSets']}–{rule['maximumSets']} working sets per occurrence."
        if rule['coverageKey'] is None:
            text += " The maximum also applies to the exercise’s total within each session, including superset members."
        return text
    if kind == 'supersetNoReconfiguration':
        text = f'{selector}: same shared-equipment load between superset partners.'
        if rule.get('sharedResourceGroups'):
            text += ' Do not superset two exercises that use resources in the same approved shared-station group.'
        if 'confirmedIndependentPairs' in rule:
            text += f" Require confirmed independent access; {len(rule['confirmedIndependentPairs'])} exercise pairs are confirmed. Other pairs remain unknown and must be separated or explicitly confirmed before selection."
        return text + ' Native per-exercise calibration does not establish a shared load.'
    if kind == 'rest':
        label = {'straightSets': 'between straight sets', 'supersetTransition': 'between superset partners',
                 'supersetRound': 'after each superset round',
                 'exerciseTransition': 'between completed exercise blocks (most demanding member category; no recovery after the session)'}[rule['context']]
        category = f" ({rule['exerciseCategory']})" if rule.get('exerciseCategory') else ''
        applicability = (' (only when at least two working sets are prescribed)' if rule['context'] in ('straightSets', 'supersetRound')
                         else ' (for each executed transition)')
        text = f"{selector}{category}: {rule['minimumSeconds']}–{rule['maximumSeconds']}s prescribed recovery {label}{applicability}."
        if rule['context'] in ('supersetTransition', 'exerciseTransition'):
            text += ' Physical changeover and setup time are separate from prescribed recovery.'
        return text
    return f"{selector}: " + ('straight sets.' if kind == 'straightSets' else 'generated ramp-up sets before working sets.')


def native_warmup_supported(definition, equipment_ids):
    """Whether the app's generated ramp-up path can run for this library configuration."""
    return bool(definition
        and definition.get('exerciseType') in ('WEIGHT', 'BODY_WEIGHT')
        and definition.get('equipmentId') in equipment_ids
        and (definition.get('exerciseType') != 'BODY_WEIGHT'
             or definition.get('bodyWeightPercentage') is not None))


def replacement_supports_required_warmup(source_coverage, definition, equipment_ids, requirements):
    """Keep source-required generated warm-ups when replacing an occurrence."""
    required_roles = {rule.get('coverageKey') for rule in (requirements or {}).get('executionRules', [])
        if rule.get('kind') == 'warmup'}
    if not required_roles:
        return True
    if not isinstance(source_coverage, list) or required_roles.intersection(source_coverage):
        return native_warmup_supported(definition, equipment_ids)
    return True


def exercise_exposure_counts(draft, plan=None, *, definition_id_by_reference=None,
                             require_mapped_identity=False):
    """Count exact library-definition exposure, weighting scheduled weekly frequency."""
    definitions = {item['id']: item.get('libraryDefinitionId', item['id'])
                   for item in (plan or {}).get('exercises', [])}
    counts, unknown = {}, []
    for day in draft.get('workouts', []):
        frequency = day.get('timesCompletedInAWeek', 1)
        present = set()
        for item in day.get('exercises', []):
            reference = item.get('definition_id', item.get('libraryDefinitionId'))
            if reference is None:
                reference = item.get('id') if item.get('id') in definitions else None
            if not isinstance(reference, str) or not reference:
                unknown.append(reference)
                continue
            definition_id = definitions.get(reference)
            if definition_id is None and definition_id_by_reference is not None:
                definition_id = definition_id_by_reference.get(reference)
            if definition_id is None:
                if require_mapped_identity or reference.startswith('LIBRARY_') or reference.startswith('EXERCISE_'):
                    unknown.append(reference)
                    continue
                definition_id = reference
            sets = item.get('numWorkSets')
            if sets is None:
                sets = sum(_is_work_set(value) for value in item.get('sets', []))
            if sets <= 0:
                continue
            present.add(definition_id)
            entry = counts.setdefault(definition_id, {'weeklyWorkingSets': 0, 'weeklySessions': 0})
            entry['weeklyWorkingSets'] += sets * frequency
        for definition_id in present:
            counts[definition_id]['weeklySessions'] += frequency
    return counts, unknown


def exercise_exposure_cap_errors(exposure, rule):
    """Return the shared deterministic findings for an audited exposure map."""
    errors = []
    for definition_id, counts in exposure.items():
        for field, actual_field, code, label in (
                ('maximumSessionsPerWeek', 'weeklySessions', 'exercise_sessions_above_maximum', 'scheduled sessions'),
                ('maximumWeeklySets', 'weeklyWorkingSets', 'exercise_weekly_sets_above_maximum', 'working sets')):
            maximum = rule.get(field)
            actual = counts[actual_field]
            if maximum is not None and actual > maximum:
                errors.append({'code': code, 'exerciseDefinitionId': definition_id,
                    'actual': actual, 'maximum': maximum, 'label': label})
    return errors


def audit_execution_rules(draft, requirements, report, plan=None):
    """Check the actual submitted order/grouping/rest fields without parsing exercise names or notes."""
    rules = requirements.get('executionRules', [])
    findings = 0
    definitions = {e['id']: e for e in (plan or {}).get('exercises', [])}
    exposure_rules = [(index, rule) for index, rule in enumerate(rules)
                      if rule['kind'] == 'exerciseExposure']
    if exposure_rules and 'weeklyExerciseExposure' not in report:
        rule_index, rule = exposure_rules[0]
        exposure, unknown = exercise_exposure_counts(draft, plan)
        report['weeklyExerciseExposure'] = exposure
        if unknown:
            findings += 1
            add_audit_issue(report, 'exercise_exposure_identity_unknown',
                'An approved per-exercise cap cannot be verified because a selected exercise lacks its definition identity.',
                'Restore the selected exercise’s exact library definition ID and re-audit.',
                path='/workouts', rulePath=f'/executionRules/{rule_index}', exerciseReferences=unknown)
        for error in exercise_exposure_cap_errors(exposure, rule):
            findings += 1
            add_audit_issue(report, error['code'],
                f"Exercise definition {error['exerciseDefinitionId']} has {error['actual']:g} weekly {error['label']}; approved maximum is {error['maximum']}.",
                'Change the exercise selection or its exposure to meet the approved cap, preserving all other requirements; re-audit.',
                path='/workouts', rulePath=f'/executionRules/{rule_index}',
                exerciseDefinitionId=error['exerciseDefinitionId'], actual=error['actual'], maximum=error['maximum'])
    for day_index, day in enumerate(draft['workouts']):
        exercises = day['exercises']
        day_definitions = {}
        if plan:
            for item, identifier in zip(exercises, plan['workouts'][day_index]['exerciseIds']):
                day_definitions[item.get('definition_id')] = definitions.get(identifier, {})
        for reference, maximum in session_work_set_caps(exercises, day_definitions, requirements).items():
            indices = [i for i, item in enumerate(exercises) if item.get('definition_id') == reference]
            actual = sum(exercises[i]['numWorkSets'] for i in indices)
            if len(indices) > 1 and actual > maximum:
                findings += 1
                add_audit_issue(report, 'execution_workSets',
                    f"{day['name']}: exercise {reference} totals {actual} working sets across blocks; approved session maximum is {maximum}.",
                    'Reduce or consolidate repeated blocks within the approved cap; preserve weekly requirements and re-audit.',
                    path=f'/workouts/{day_index}/exercises/{indices[0]}/numWorkSets',
                    rulePath='/executionRules', exerciseReference=reference,
                    exerciseIndices=indices, actual=actual, maximum=maximum)
        blocks = []
        invalid_explicit_order = False
        for index, item in enumerate(exercises):
            same_group = index and item['superset'] is not None and item['superset'] == exercises[index - 1]['superset']
            blocks.append(blocks[-1] if same_group else index)
        reported_shared_station_pairs = set()
        for rule_index, rule in enumerate(rules):
            kind = rule['kind']
            if kind == 'coverageBalance':
                continue  # A qualitative balance goal does not authorize an invented hard ratio.
            if kind == 'exerciseExposure':
                continue  # Counted weekly by canonical definition above.
            if kind == 'sessionStructure':
                groups = {}
                for index, item in enumerate(exercises):
                    if item.get('superset') is not None:
                        groups.setdefault(item['superset'], []).append(index)
                counts = {'maximumExercises': len(exercises), 'maximumSupersets': len(groups),
                          'maximumSupersetSize': max(map(len, groups.values()), default=0)}
                for key, actual in counts.items():
                    if key in rule and actual > rule[key]:
                        findings += 1
                        add_audit_issue(report, 'execution_sessionStructure',
                            f"{day['name']}: {key} is {actual}; approved maximum is {rule[key]}.",
                            'Reselect or regroup exercises within the approved session limits, preserving required coverage, volume and timing; re-audit.',
                            path=f'/workouts/{day_index}/exercises', rulePath=f'/executionRules/{rule_index}',
                            limit=key, actual=actual, maximum=rule[key])
                continue

            def matches(item, key):
                return key is None or key in item.get('satisfiesCoverage', [])

            def issue(index, field, message, repair, **details):
                nonlocal findings
                findings += 1
                add_audit_issue(report, 'execution_' + kind, f"{day['name']}: {message}", repair,
                    path=f'/workouts/{day_index}/exercises/{index}' + (f'/{field}' if field else ''),
                    rulePath=f'/executionRules/{rule_index}', **details)

            if kind == 'rest' and rule['context'] == 'exerciseTransition':
                block_groups = [[i for i, start in enumerate(blocks) if start == block_start]
                    for block_start in dict.fromkeys(blocks)]
                aliases = {item['definition_id']: definitions.get(
                    plan['workouts'][day_index]['exerciseIds'][i], {}) if plan else {}
                    for i, item in enumerate(exercises)}
                for indices in block_groups[:-1]:
                    bounds = block_recovery_bounds([exercises[i] for i in indices],
                        {'executionRules': [rule]}, aliases)
                    if bounds:
                        actual = exercises[indices[-1]]['restAfterExerciseSeconds']
                        if not bounds[0] <= actual <= bounds[1]:
                            issue(indices[-1], 'restAfterExerciseSeconds',
                                f'{actual}s violates {render_execution_rule(rule)}',
                                'Prescribe recovery after the complete block, separately from setup, and re-audit duration.',
                                actual=actual, minimum=bounds[0], maximum=bounds[1])
                continue

            if kind == 'supersetNoReconfiguration' and plan:
                equipment_by_id = {gear.get('id'): gear for gear in plan.get('equipments', [])}
                compatibility = report.setdefault('supersetEquipmentResources', [])
                for (first, a), (second, b) in combinations(enumerate(exercises), 2):
                    if a['superset'] is None or a['superset'] != b['superset']:
                        continue
                    if not (matches(a, rule['coverageKey']) or matches(b, rule['coverageKey'])):
                        continue
                    ea, eb = [definitions[plan['workouts'][day_index]['exerciseIds'][i]] for i in (first, second)]
                    relation = superset_resource_relation(ea, eb, equipment_by_id)
                    compatibility.append({'workoutIndex': day_index, 'memberIndices': [first, second],
                        'equipmentIds': [ea.get('equipmentId'), eb.get('equipmentId')], 'relation': relation})
                    setup = superset_setup_compatibility(ea, eb, requirements,
                        a.get('satisfiesCoverage', []), b.get('satisfiesCoverage', []))
                    compatibility[-1]['setupCompatibility'] = setup
                    shared_group = setup.get('sharedResourceGroup')
                    if shared_group:
                        occurrence = (first, second, tuple(sorted(shared_group)))
                        if occurrence in reported_shared_station_pairs:
                            continue
                        reported_shared_station_pairs.add(occurrence)
                        issue(second, 'superset',
                            'Both superset members use resources in the same approved shared physical station.',
                            'Separate the exercises into different blocks or remove the pairing; the approved station rule applies even when the exercises use different inventory records.',
                            partnerIndex=first, sharedResourceGroup=sorted(shared_group))
                        continue
                    if setup['status'] == 'unknown' and setup['confirmationRequired']:
                        issue(second, 'superset', 'Independent simultaneous access is not confirmed for this pair.',
                            'Separate the exercises or obtain explicit confirmation for this exact pair; different equipment types do not establish access. Re-audit timing without inventing physical facts.',
                            partnerIndex=first, setupCompatibility='unknown')
                        continue
                    if relation in {'different_family_types', 'no_primary_equipment'}:
                        continue
                    loads = [{p['workSetIndex']: p.get('weight', p.get('additionalWeight'))
                              for p in item.get('targetSetPrescriptions', [])} for item in (ea, eb)]
                    same_load_convention = (relation == 'same_record' or
                        (equipment_by_id.get(ea.get('equipmentId'), {}).get('type') ==
                         equipment_by_id.get(eb.get('equipmentId'), {}).get('type')))
                    conflict = (same_load_convention and any(
                        loads[0][r] != loads[1][r] for r in loads[0].keys() & loads[1].keys()))
                    uncertain = (relation == 'identity_unknown' or not all(loads)
                        or not same_load_convention)
                    calibration_choices = []
                    for item in (ea, eb):
                        if item.get('requiresLoadCalibration') is True:
                            from .domain_ops import get_selectable_weights_for_exercise
                            gear = next((gear for gear in plan.get('equipments', [])
                                         if gear['id'] == item['equipmentId']), None)
                            choices = (get_selectable_weights_for_exercise(item.get('exerciseType'), gear)
                                       if gear else [])
                            uncertain = uncertain or len(set(choices)) != 1
                            calibration_choices.append(set(choices))
                    if relation == 'potentially_shared_family' and calibration_choices:
                        uncertain = uncertain or not all(calibration_choices[0] == choices
                            for choices in calibration_choices[1:])
                    if conflict or uncertain:
                        if conflict:
                            message = ('Shared superset equipment has different prescribed loads.' if relation == 'same_record'
                                else 'Equipment records in a potentially shared family prescribe different loads; independent inventory is unverified.')
                        else:
                            message = 'A common usable configuration is unverified for equipment records that may share physical inventory.'
                        issue(second, 'superset', message,
                            'Use a common prescribed load justified for both movements, or separate/change the pairing. Native per-exercise calibration does not guarantee a shared load. Do not transfer historical loads or invent extra equipment. Re-audit timing and volume.',
                            partnerIndex=first, equipmentResourceRelation=relation)
                continue
            if kind == 'order':
                before = [i for i, item in enumerate(exercises) if matches(item, rule['before'])]
                after = [i for i, item in enumerate(exercises) if matches(item, rule['after'])]
                if before and after and max(blocks[i] for i in before) >= min(blocks[i] for i in after):
                    invalid_explicit_order = True
                    issue(after[0], '', render_execution_rule(rule),
                        'Move complete exercise/superset blocks using JSON Patch so the approved order holds. Preserve group contiguity, prescriptions, rest constraints and volume; re-audit.',
                        beforeIndices=before, afterIndices=after)
                continue
            for index, item in enumerate(exercises):
                if not matches(item, rule['coverageKey']):
                    continue
                if rule.get('exerciseCategory') and plan:
                    identifier = plan['workouts'][day_index]['exerciseIds'][index]
                    if definitions[identifier].get('exerciseCategory') != rule['exerciseCategory']:
                        continue
                if kind == 'workSets' and not rule['minimumSets'] <= item['numWorkSets'] <= rule['maximumSets']:
                    issue(index, 'numWorkSets', render_execution_rule(rule),
                        'Restore a working-set count within the approved requirement; re-audit volume and duration.')
                elif kind == 'straightSets' and item['superset'] is not None:
                    issue(index, 'superset', render_execution_rule(rule),
                        'Remove this occurrence from the superset and restore its approved between-set rest. Repair remaining group members and re-audit timing; do not delete required work.')
                elif kind == 'warmup' and not item['generateWarmUpSets']:
                    identifiers = (plan or {}).get('workouts', [{}])[day_index].get('exerciseIds', []) \
                        if plan and day_index < len(plan.get('workouts', [])) else []
                    identifier = identifiers[index] if index < len(identifiers) else None
                    definition = definitions.get(identifier)
                    equipment_ids = {gear.get('id') for gear in (plan or {}).get('equipments', [])}
                    if plan and not native_warmup_supported(definition, equipment_ids):
                        issue(index, '', 'The approved generated-ramp-up rule applies, but this exercise configuration cannot produce native ramp-up sets.',
                            'Replace this occurrence with a library configuration supported by the app warm-up generator while preserving required coverage. If no such option is available, ask the user to resolve the conflict; do not toggle the flag or change the requirement.',
                            warmupCapability='unsupported')
                    else:
                        issue(index, 'generateWarmUpSets', render_execution_rule(rule),
                            'Set generateWarmUpSets=true for this supported occurrence; preserve working sets and re-audit the added preparation time.')
                elif kind == 'rest':
                    grouped = item['superset'] is not None
                    last = grouped and (index == len(exercises) - 1 or exercises[index + 1]['superset'] != item['superset'])
                    context = 'supersetRound' if last else 'supersetTransition' if grouped else 'straightSets'
                    if context != rule['context'] or (context != 'supersetTransition' and item['numWorkSets'] == 1):
                        continue  # No executed between-set/final-round recovery for one working set.
                    field = 'restAfterSupersetExerciseSeconds' if grouped else 'restBetweenSetsSeconds'
                    actual = item[field]
                    if not rule['minimumSeconds'] <= actual <= rule['maximumSeconds']:
                        issue(index, field, f"{actual}s violates {render_execution_rule(rule)}",
                            f"Patch {field} within the approved range and re-audit duration. Do not shorten another required recovery or relax the time/volume targets.",
                            actual=actual, minimum=rule['minimumSeconds'], maximum=rule['maximumSeconds'])
        if plan and not invalid_explicit_order:
            identifiers = plan['workouts'][day_index]['exerciseIds']
            members = {}
            for index, start in enumerate(blocks):
                members.setdefault(start, []).append(index)
            groups = list(members.values())
            for group in groups:
                phases = [execution_block_priority([definitions[identifiers[i]]]) for i in group]
                if (3 in phases and min(phases) < 2
                        and execution_order_phase(3, requirements) > execution_order_phase(min(phases), requirements)):
                    findings += 1
                    add_audit_issue(report, 'execution_superset_order_conflict',
                        f"{day['name']}: this superset combines main compound work with core-late work.",
                        'Split this group using the existing straight-set alternatives; preserve doses and recovery.',
                        path=f'/workouts/{day_index}/exercises/{group[0]}/superset')
                member_order = execution_member_order([definitions[identifiers[i]] for i in group], requirements)
                if member_order != list(range(len(group))):
                    findings += 1
                    add_audit_issue(report, 'execution_order',
                        f"{day['name']}: superset members violate the default execution order.",
                        'Reorder members with the shared category policy while retaining transition and round-rest '
                        'positions, then re-audit timing and setup.',
                        path=f'/workouts/{day_index}/exercises/{group[0]}/superset',
                        orderingPolicy=EXECUTION_ORDER_POLICY,
                        beforeIndices=[group[i] for i in member_order], afterIndices=group)
            roles = [set().union(*(set(exercises[i].get('satisfiesCoverage', [])) for i in group))
                     for group in groups]
            keys = [execution_block_order_key([definitions[identifiers[i]] for i in group],
                [exercises[i]['numWorkSets'] for i in group]) for group in groups]
            if not execution_order_is_admissible(list(range(len(groups))), roles, keys, requirements):
                findings += 1
                add_audit_issue(report, 'execution_order',
                    f"{day['name']}: exercise blocks violate the allowed execution phases or approved precedence.",
                    'Reorder complete blocks with the shared execution-order policy; preserve supersets, prescriptions '
                    'and approved order rules, then re-audit timing. ' + EXECUTION_ORDER_DESCRIPTION,
                    path=f'/workouts/{day_index}/exercises', orderingPolicy=EXECUTION_ORDER_POLICY)
    report['executionGuidelines'] = {'checkedRules': len(rules), 'findings': findings,
        'defaultOrderPolicy': EXECUTION_ORDER_POLICY,
        'assignmentVerification': 'Coverage-role semantics and contextual training recommendations require independent review.'}


def session_structure_limits(requirements):
    """Intersect approved session bounds without applying them to an unselected candidate pool."""
    limits = {}
    for rule in requirements.get('executionRules', []):
        if rule['kind'] == 'sessionStructure':
            for key in ('maximumExercises', 'maximumSupersets', 'maximumSupersetSize'):
                if key in rule:
                    limits[key] = min(limits.get(key, rule[key]), rule[key])
    return limits


def approved_work_set_bounds(item, definition, requirements):
    """Only confirmed execution rules may restrict a candidate's native set domain."""
    minimum, maximum = 1, 20
    for rule in requirements.get('executionRules', []):
        if rule['kind'] != 'workSets':
            continue
        if rule['coverageKey'] is not None and rule['coverageKey'] not in item.get('satisfiesCoverage', []):
            continue
        if rule.get('exerciseCategory') and rule['exerciseCategory'] != definition.get('exerciseCategory'):
            continue
        minimum = max(minimum, rule['minimumSets'])
        maximum = min(maximum, rule['maximumSets'])
    return {'minimum': minimum, 'maximum': maximum}


def session_work_set_caps(exercises, definitions, requirements):
    """Apply approved maxima to exact exercise identities across all session blocks."""
    rules = [rule for rule in requirements.get('executionRules', [])
             if rule['kind'] == 'workSets' and rule['coverageKey'] is None]
    if not rules:
        return {}
    caps = {}
    for item in exercises:
        reference = item.get('definition_id')
        if reference is None:
            continue
        maximum = approved_work_set_bounds(item, definitions.get(reference, {}),
            {'executionRules': rules})['maximum']
        caps[reference] = min(caps.get(reference, maximum), maximum)
    return caps


def normalize_work_set_bounds(draft, equipment, requirements):
    import copy
    result = copy.deepcopy(draft)
    definitions = {f'LIBRARY_{i}': definition for i, definition in enumerate(
        sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id']))}
    for day in result['workouts']:
        for item in day['exercises']:
            definition = definitions.get(item.get('definition_id'))
            if definition is not None and ('allocationBounds' in item or
                    approved_work_set_bounds(item, definition, requirements) != {'minimum': 1, 'maximum': 20}):
                item['allocationBounds'] = approved_work_set_bounds(item, definition, requirements)
    return result


def audit_training_schedule(workouts, requirements, report):
    """Validate the repeating calendar independently of exercise prescriptions."""
    scheduled = []
    spacing = requirements.get('minimumRestDaysBetweenSessions')
    approved_days = requirements.get('trainingDays')
    for day_index, day in enumerate(workouts):
        path = f'/workouts/{day_index}'
        if 'trainingDays' in day:
            if len(day['trainingDays']) != day['timesCompletedInAWeek']:
                add_audit_issue(report, 'schedule_frequency_mismatch', f"{day['name']}: trainingDays does not match weekly frequency.",
                    'Assign one weekday per weekly occurrence and re-audit the full schedule.', path=path + '/trainingDays')
            scheduled.extend((value, day_index) for value in day['trainingDays'])
        elif spacing is not None or approved_days is not None:
            add_audit_issue(report, 'schedule_days_required', f"{day['name']}: weekdays are required to verify recovery spacing.",
                'Set trainingDays to Monday=0 through Sunday=6, respecting any user-selected days. Do not infer spacing from frequency alone.', path=path + '/trainingDays')
    if approved_days is not None and (any(value not in approved_days for value, _ in scheduled)
            or all('trainingDays' in day for day in workouts)
            and sorted(value for value, _ in scheduled) != sorted(approved_days)):
        add_audit_issue(report, 'schedule_approved_days_mismatch',
            'The weekly calendar differs from the explicitly approved training days.',
            'Preserve the approved weekdays; correct session placement or ask about a genuine conflict.',
            path='/workouts', expected=approved_days, actual=sorted(value for value, _ in scheduled))
    if spacing is not None and scheduled:
        ordered = sorted(scheduled)
        for index, (value, day_index) in enumerate(ordered):
            next_day = ordered[(index + 1) % len(ordered)][0] + (7 if index == len(ordered) - 1 else 0)
            rest_days = max(0, next_day - value - 1)
            if rest_days < spacing:
                add_audit_issue(report, 'schedule_recovery_gap', f'Only {rest_days} full rest days between weekdays {value} and {next_day % 7}; required {spacing}.',
                    'Patch trainingDays to preserve the approved frequency and minimum spacing, including Sunday-to-Monday. Ask about a genuine scheduling conflict; do not relax the rule.',
                    path=f'/workouts/{day_index}/trainingDays', actual=rest_days, minimum=spacing)


def complete_training_schedule(workouts, requirements, fixed_workouts=()):
    """Assign only omitted weekdays; supplied and already accepted calendars stay authoritative."""
    result = copy.deepcopy(workouts)
    combined = [*fixed_workouts, *result]
    report = {'issues': [], 'errors': []}
    audit_training_schedule(combined, requirements, report)
    if any(error['code'] != 'schedule_days_required' for error in report['errors']):
        return result
    missing = [day for day in result if 'trainingDays' not in day]
    if not missing:
        return result
    occupied = {weekday for day in combined for weekday in day.get('trainingDays', [])}
    count = sum(day['timesCompletedInAWeek'] for day in missing)
    # shortcut: automatic examples use distinct days; denser schedules need explicit user weekdays.
    candidates = combinations([day for day in requirements.get('trainingDays', range(7))
                               if day not in occupied], count)

    def calendar_score(days):
        ordered = sorted(occupied | set(days))
        gaps = [(ordered[(index + 1) % len(ordered)] - day) % 7 or 7
                for index, day in enumerate(ordered)]
        return (-min(gaps), sum(gap * gap for gap in gaps), days)

    for days in sorted(candidates, key=calendar_score):
        cursor = 0
        for day in missing:
            frequency = day['timesCompletedInAWeek']
            day['trainingDays'] = list(days[cursor:cursor + frequency])
            cursor += frequency
        report = {'issues': [], 'errors': []}
        audit_training_schedule(combined, requirements, report)
        if not report['errors']:
            return result
    for day in missing:
        day.pop('trainingDays', None)
    return result


def audit_execution_details(draft, requirements, report):
    """Use the shared calendar check and require explicit execution-time assumptions."""
    audit_training_schedule(draft['workouts'], requirements, report)
    for day_index, day in enumerate(draft['workouts']):
        path = f'/workouts/{day_index}'
        if requirements['auditTargets'].get('maximumSessionSeconds'):
            for index, item in enumerate(day['exercises']):
                if 'setupSeconds' not in item:
                    add_audit_issue(report, 'setup_time_required', f"{day['name']}: setup estimate missing before exercise {index + 1}.",
                        'Add setupSeconds for this transition, including implement, plate, rack, bench and attachment changes. Use an explicit estimate or ask for missing setup information; do not assert measured precision. It replaces the default allowance and does not replace prescribed rest.',
                        path=f'{path}/exercises/{index}/setupSeconds')
