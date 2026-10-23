"""Executable contracts for supported structural workout repairs."""

from __future__ import annotations

import copy
import json


REDISTRIBUTION_UPDATE_FIELDS = frozenset({
    'numWorkSets', 'superset', 'restBetweenSetsSeconds', 'restAfterSupersetExerciseSeconds', 'restAfterExerciseSeconds'})


class RepairContractError(ValueError):
    def __init__(self, code, message, path='/edits/exerciseRedistributions'):
        super().__init__(message)
        self.code = code
        self.path = path


def _stable_refs(draft):
    workouts, exercises, index = {}, {}, 0
    for workout_index, workout in enumerate(draft.get('workouts', [])):
        workouts[f'WORKOUT_{workout_index}'] = workout_index
        for exercise_index, _ in enumerate(workout.get('exercises', [])):
            exercises[f'EXERCISE_{index}'] = (workout_index, exercise_index)
            index += 1
    return workouts, exercises


def _recipe(exercise):
    recipe = copy.deepcopy(exercise)
    for field in ('numWorkSets', 'targetSetPrescriptions', 'allocationBounds',
                  'name', 'nameOverride', 'placementNotes', 'setupSeconds', 'reference', 'generateWarmUpSets',
                  'superset', 'restBetweenSetsSeconds', 'restAfterSupersetExerciseSeconds',
                  'restAfterExerciseSeconds'):
        recipe.pop(field, None)
    return recipe


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def target_content(target):
    return {key: value for key, value in target.items() if key != 'workSetIndex'}


def normalized_target_signature(target):
    return _json(target_content(target))


def _indexed_targets(targets):
    return [{'workSetIndex': index, **target_content(target)} for index, target in enumerate(targets)]


def redistribution_recipe_signature(exercise):
    return _json(_recipe(exercise))


def redistribution_work_set_bounds(source_items, requirements=None, definitions=None):
    """Return the intersection of source bounds and applicable approved set rules."""
    from .programming_guidelines import approved_work_set_bounds

    minimum, maximum = 1, 20
    definitions = definitions or {}
    for item in source_items:
        source_bounds = item.get('allocationBounds')
        if source_bounds is not None:
            if (not isinstance(source_bounds, dict)
                    or type(source_bounds.get('minimum')) is not int
                    or type(source_bounds.get('maximum')) is not int
                    or not 1 <= source_bounds['minimum'] <= source_bounds['maximum'] <= 20):
                _fail('A redistribution source has invalid approved allocation bounds.',
                      'redistribution_source_bounds_invalid')
            minimum = max(minimum, source_bounds['minimum'])
            maximum = min(maximum, source_bounds['maximum'])
        if requirements:
            definition = definitions.get(item.get('definition_id'), {})
            approved_bounds = approved_work_set_bounds(item, definition, requirements)
            minimum = max(minimum, approved_bounds['minimum'])
            maximum = min(maximum, approved_bounds['maximum'])
    return {'minimum': minimum, 'maximum': maximum}


def redistribution_destination_count_bounds(source_items, eligible_count, requirements=None, definitions=None):
    """Return the feasible destination-count interval for an even code-owned split."""
    total_sets = sum(item.get('numWorkSets', 0) for item in source_items)
    bounds = redistribution_work_set_bounds(source_items, requirements, definitions)
    if bounds['minimum'] > bounds['maximum']:
        return {**bounds, 'minimumDestinations': 1, 'maximumDestinations': 0, 'totalWorkSets': total_sets}
    minimum_destinations = max(1, (total_sets + bounds['maximum'] - 1) // bounds['maximum'])
    maximum_destinations = min(eligible_count, total_sets // bounds['minimum'])
    return {**bounds, 'minimumDestinations': minimum_destinations,
            'maximumDestinations': maximum_destinations, 'totalWorkSets': total_sets}


def _normalize_contract_groups(contract, draft):
    normalized = copy.deepcopy(contract)
    workouts, exercises = _stable_refs(draft)
    for group in normalized.get('redistributions', []):
        group['recipe'] = _recipe(group['recipe'])
        group['recipeSignature'] = redistribution_recipe_signature(group['recipe'])
        target_indexes = group.get('targetWorkoutIndexes', [])
        if (not isinstance(target_indexes, list) or not target_indexes
                or any(not isinstance(index, int) or isinstance(index, bool)
                       or index < 0 or index >= len(workouts) for index in target_indexes)
                or len(set(target_indexes)) != len(target_indexes)):
            _fail('A carried redistribution has invalid target session indexes.',
                  'carried_repair_contract_changed')
        targets = [f'WORKOUT_{index}' for index in target_indexes]
        matching = []
        for reference, (workout_index, exercise_index) in exercises.items():
            item = draft['workouts'][workout_index]['exercises'][exercise_index]
            if workout_index in target_indexes and _recipe(item) == group.get('recipe'):
                matching.append((reference, workout_index, exercise_index))
        group['targetWorkoutRefs'] = targets
        group['workoutRefs'] = list(targets)
        group['exerciseRefs'] = [reference for reference, _, _ in matching]
        group['sourcePositions'] = {reference: [workout_index, exercise_index]
            for reference, workout_index, exercise_index in matching}
        group['expectedRefByWorkout'] = {
            f'WORKOUT_{workout_index}': reference
            for reference, workout_index, _ in matching if workout_index in target_indexes}
    return normalized


def _fail(message, code='invalid_redistribution', path='/edits/exerciseRedistributions'):
    raise RepairContractError(code, message, path)


def _recipe_objectives(objectives, current_draft):
    """Partition semantic movement lists into the compiler's homogeneous recipes."""
    _, references = _stable_refs(current_draft)
    for objective in objectives:
        recipes = {}
        for reference in objective['exerciseRefs']:
            if reference not in references:
                _fail('Redistribution references an exercise outside the current draft.')
            day, index = references[reference]
            signature = redistribution_recipe_signature(current_draft['workouts'][day]['exercises'][index])
            recipes.setdefault(signature, []).append(reference)
        for signature in recipes:
            all_sources = [reference for reference, (day, index) in references.items()
                if redistribution_recipe_signature(current_draft['workouts'][day]['exercises'][index]) == signature]
            yield {**copy.deepcopy(objective), 'exerciseRefs': all_sources}


def assessed_redistributions(task, current_draft=None):
    """Give each assessed source recipe a stable destination-only input slot."""
    objectives = [objective for group in (task.get('findingsAssessment') or {}).get('groups', [])
        if group.get('disposition') == 'repair' for objective in group.get('repairObjectives', [])
        if objective.get('kind') == 'redistribute_work']
    draft = current_draft or task.get('currentDraft')
    if draft is not None:
        objectives = _recipe_objectives(objectives, draft)
    groups, sources = {}, {}
    for objective in objectives:
        identity = tuple(sorted(objective['exerciseRefs']))
        if identity in sources:
            previous = groups[sources[identity]]
            previous['minimumSessions'] = max(previous['minimumSessions'], objective['minimumSessions'])
            continue
        key = f'REDISTRIBUTION_{len(groups)}'
        sources[identity] = key
        groups[key] = copy.deepcopy(objective)
    return groups


def redistribution_objective_choices(draft, requirements=None, definitions=None):
    """Enumerate compiler-executable recipe spreads; whole-plan feasibility is checked later."""
    from itertools import combinations

    draft = copy.deepcopy(draft)
    for day in draft.get('workouts', []):
        day.pop('reference', None)
        for exercise in day.get('exercises', []):
            exercise.pop('reference', None)
    workouts, references = _stable_refs(draft)
    eligible = [ref for ref, index in workouts.items()
                if draft['workouts'][index].get('timesCompletedInAWeek', 1) == 1]
    if len(eligible) < 2 or not references:
        return []
    source = {'kind': 'redistribute_work', 'exerciseRefs': list(references), 'minimumSessions': 2}
    choices = []
    for objective in _recipe_objectives([source], draft):
        items = [draft['workouts'][references[ref][0]]['exercises'][references[ref][1]]
                 for ref in objective['exerciseRefs']]
        domain = redistribution_destination_count_bounds(items, len(eligible), requirements, definitions)
        for count in range(max(2, domain['minimumDestinations']), domain['maximumDestinations'] + 1):
            for targets in combinations(eligible, count):
                try:
                    expand_redistributions({'exerciseRedistributions': [{
                        'exerciseRefs': objective['exerciseRefs'], 'workoutRefs': list(targets)}]}, draft,
                        requirements=requirements, definitions=definitions)
                except RepairContractError:
                    continue
                choices.append({**objective, 'minimumSessions': count})
                break
    return choices


def bind_redistribution_targets(edits, task, current_draft):
    """Compile assessed intent without accepting manual edits to its source recipes."""
    objectives = assessed_redistributions(task, current_draft)
    if not objectives:
        return copy.deepcopy(edits)
    targets = edits.get('redistributionTargets')
    if not isinstance(targets, dict) or set(targets) != set(objectives):
        _fail('Choose destination sessions for every assessed redistribution using redistributionTargets; '
            'do not calculate counts, clone exercises, move sources or order generated occurrences.',
            'redistribution_intent_required', '/edits/redistributionTargets')
    if edits.get('exerciseRedistributions'):
        _fail('Assessed redistribution source groups are code-owned; submit redistributionTargets only.',
            'redistribution_manual_conflict')
    protected_refs = {ref for objective in objectives.values() for ref in objective['exerciseRefs']}
    workouts, references = _stable_refs(current_draft)
    definitions = {current_draft['workouts'][references[ref][0]]['exercises'][references[ref][1]]['definition_id']
        for ref in protected_refs if ref in references}
    if any(item.get('exercise', {}).get('definition_id') in definitions
            for item in edits.get('exerciseAdditions', [])):
        _fail('Do not manually clone a movement owned by an assessed redistribution; code creates its occurrences.',
            'redistribution_manual_conflict', '/edits/exerciseAdditions')
    if any(ref.startswith('NEW_EXERCISE_REDIST_') for order in edits.get('exerciseOrders', [])
            for ref in order.get('exerciseRefs', [])):
        _fail('Generated redistribution occurrences are placed by code, not explicit exerciseOrders.',
            'redistribution_manual_conflict', '/edits/exerciseOrders')
    expanded = copy.deepcopy(edits)
    expanded.pop('redistributionTargets')
    expanded['exerciseRedistributions'] = []
    for key, objective in objectives.items():
        destinations = targets[key]
        if (not isinstance(destinations, list) or len(destinations) < objective['minimumSessions']
                or any(not isinstance(ref, str) or ref not in workouts for ref in destinations)
                or len(set(destinations)) != len(destinations)):
            _fail('Choose distinct destination sessions satisfying the assessed minimum session spread.',
                'redistribution_invalid_targets', '/edits/redistributionTargets/' + key)
        expanded['exerciseRedistributions'].append({'exerciseRefs': copy.deepcopy(objective['exerciseRefs']),
            'workoutRefs': sorted(destinations, key=workouts.get)})
    return expanded


def expand_redistributions(edits, current_draft, *, requirements=None, definitions=None):
    """Expand supported set redistributions into existing typed repair edits.

    Each item splits a homogeneous recipe group over the listed sessions. Work
    sets (and indexed set targets) are divided evenly, with remainders assigned
    in workoutRefs order. The source recipes and their weekly set total remain
    unchanged.
    """
    expanded = copy.deepcopy(edits)
    groups = expanded.pop('exerciseRedistributions', [])
    if not groups:
        return expanded, []
    current_draft = copy.deepcopy(current_draft)
    workout_refs, exercise_refs = _stable_refs(current_draft)
    selected = {ref for group in groups for ref in group.get('exerciseRefs', [])}
    structure_updates = {}
    for day_index, day in enumerate(current_draft['workouts']):
        touched = {day['exercises'][index].get('superset') for ref, (workout, index) in exercise_refs.items()
                   if ref in selected and workout == day_index} - {None}
        for group in touched:
            members = [item for item in day['exercises'] if item.get('superset') == group]
            recovery = max(max(item.get('restAfterSupersetExerciseSeconds', 0),
                               item.get('restBetweenSetsSeconds', 0)) for item in members)
            for ref, (workout, index) in exercise_refs.items():
                if workout == day_index and day['exercises'][index].get('superset') == group:
                    fields = {'superset': None, 'restBetweenSetsSeconds': recovery,
                              'restAfterSupersetExerciseSeconds': 0}
                    item = day['exercises'][index]
                    item.update(fields)
                    if requirements:
                        from .joint_planning import _rest_options
                        options = list(_rest_options([item], requirements,
                            definitions or {item['definition_id']: {}}, item['numWorkSets']))
                        item.update(options[-1][0])
                        fields = {key: item[key] for key in fields}
                    structure_updates[ref] = fields
    workout_order = expanded.get('workoutOrder') or list(workout_refs)
    if set(workout_order) != set(workout_refs) or len(workout_order) != len(workout_refs):
        _fail('A redistribution workout order must include each source session exactly once.',
              'redistribution_workout_order_invalid', '/edits/workoutOrder')
    ordered_workout_index = {ref: index for index, ref in enumerate(workout_order)}
    updates = expanded.setdefault('exerciseUpdates', [])
    policy_updates = [item for item in updates if item.get('exerciseRef') in selected
        and item.get('setFields') and set(item['setFields']) <= REDISTRIBUTION_UPDATE_FIELDS
        and not item.get('removeOptionalFields')]
    updates[:] = [item for item in updates if item not in policy_updates]
    additions = expanded.setdefault('exerciseAdditions', [])
    removals = expanded.setdefault('exerciseRemovals', [])
    moves = expanded.setdefault('exerciseMoves', [])
    updated_refs = {item.get('exerciseRef') for item in updates}
    removed_refs = set(removals)
    moved_refs = {item.get('exerciseRef') for item in moves}
    manifest = []
    handled_refs = set()

    for group_index, group in enumerate(groups):
        source_refs = group.get('exerciseRefs')
        target_refs = group.get('workoutRefs')
        if (not isinstance(source_refs, list) or not source_refs or len(set(source_refs)) != len(source_refs)
                or not isinstance(target_refs, list) or len(set(target_refs)) != len(target_refs)
                or any(ref not in workout_refs for ref in target_refs)):
            _fail('Redistribution needs unique current exercise references and unique existing target sessions.')
        if any(ref not in exercise_refs for ref in source_refs):
            _fail('Redistribution references an exercise outside the current draft.')
        if set(source_refs) & (updated_refs | removed_refs | moved_refs):
            _fail('A redistributed exercise cannot also have a manual update, move, or removal.')
        if set(source_refs) & handled_refs:
            _fail('An exercise reference cannot appear in more than one redistribution group.')
        handled_refs.update(source_refs)

        policy_fields = {}
        for update in policy_updates:
            if update['exerciseRef'] not in source_refs:
                continue
            for field, value in update['setFields'].items():
                # Counts are solver seeds; redistribution owns the conserved allocation.
                if field == 'numWorkSets':
                    continue
                if field == 'superset' and value is not None or field == 'restAfterSupersetExerciseSeconds' and value != 0:
                    _fail('A redistributed individual recipe must use straight sets.', 'redistribution_manual_conflict')
                if field in policy_fields and policy_fields[field] != value:
                    _fail('A redistributed recipe needs consistent rest choices.',
                          'redistribution_manual_conflict', '/edits/exerciseUpdates')
                policy_fields[field] = copy.deepcopy(value)
        for ref in source_refs:
            day, index = exercise_refs[ref]
            current_draft['workouts'][day]['exercises'][index].update(copy.deepcopy(policy_fields))
            structure_updates.setdefault(ref, {}).update(copy.deepcopy(policy_fields))
        source_items = []
        source_workouts = []
        total_sets = 0
        exact_targets = []
        exact_target_modes = set()
        first_recipe = None
        for ref in source_refs:
            workout_index, exercise_index = exercise_refs[ref]
            workout = current_draft['workouts'][workout_index]
            exercise = copy.deepcopy(workout['exercises'][exercise_index])
            if workout.get('timesCompletedInAWeek', 1) != 1:
                _fail('Redistribution requires each source and target workout to represent one weekly session.',
                      'redistribution_frequency_unsupported')
            recipe = _recipe(exercise)
            if first_recipe is not None and recipe != first_recipe:
                _fail('A redistribution group must contain one exact exercise recipe; split mixed recipes into separate groups.')
            first_recipe = recipe
            count = exercise.get('numWorkSets')
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                _fail(f'{ref} must have a positive integer working-set count.')
            targets = exercise.get('targetSetPrescriptions')
            if targets is not None and (not isinstance(targets, list) or len(targets) != count):
                _fail(f'{ref} exact set targets must contain one entry per working set.')
            exact_target_modes.add(targets is not None)
            source_items.append((ref, exercise))
            source_workouts.append(workout_index)
            total_sets += count
            exact_targets.extend(copy.deepcopy(targets if targets is not None else [None] * count))

        if len(exact_target_modes) > 1:
            _fail('Redistributing mixed exact-per-set and uniform prescriptions is unsupported; preserve the source prescriptions and report the capability gap.',
                  'redistribution_mixed_target_modes_unsupported')
        metadata = {(item.get('name'), item.get('nameOverride'), item.get('setupSeconds'))
                    for _, item in source_items}
        if len(target_refs) < len(source_items) and len(metadata) > 1:
            _fail('Consolidating these source occurrences would discard session-specific cues or setup values; keep enough destinations or repair those fields separately.',
                  'redistribution_source_metadata_conflict')

        if len(source_refs) != len(set(source_refs)) or len(target_refs) < 2 or len(target_refs) > total_sets:
            _fail('A redistribution must span at least two sessions and assign at least one working set to each.')
        if any(current_draft['workouts'][workout_refs[ref]].get('timesCompletedInAWeek', 1) != 1 for ref in target_refs):
            _fail('Redistribution targets must each represent one weekly session.', 'redistribution_frequency_unsupported')
        source_bounds = redistribution_work_set_bounds(
            [item for _, item in source_items], requirements, definitions)
        if source_bounds['minimum'] > source_bounds['maximum']:
            _fail('The source occurrences have no common approved per-session set range.',
                  'redistribution_source_bounds_conflict')
        if total_sets < len(target_refs) * source_bounds['minimum']:
            _fail('The selected destinations would put fewer than the approved minimum work sets in a session. '
                  'Choose fewer destination sessions or preserve this exercise occurrence.',
                  'redistribution_target_below_minimum')
        if total_sets > len(target_refs) * source_bounds['maximum']:
            _fail('The selected destinations would put more than the approved maximum work sets in a session. '
                  'Choose more destination sessions or preserve this exercise occurrence.',
                  'redistribution_target_above_maximum')
        all_same_recipe_refs = [ref for ref, (workout_index, exercise_index) in exercise_refs.items()
            if _recipe(current_draft['workouts'][workout_index]['exercises'][exercise_index]) == first_recipe]
        if set(source_refs) != set(all_same_recipe_refs):
            _fail('A redistribution must name every occurrence of its exact recipe so weekly set conservation is unambiguous.')

        quotient, remainder = divmod(total_sets, len(target_refs))
        counts = [quotient + (index < remainder) for index in range(len(target_refs))]
        if any(not count for count in counts):
            _fail('Every target session must receive at least one working set.')
        assigned_targets = [exact_targets[sum(counts[:index]):sum(counts[:index + 1])]
                            for index in range(len(target_refs))]

        if len(source_workouts) != len(set(source_workouts)):
            _fail('A redistribution group can contain at most one occurrence in each source session.')
        source_by_workout = {workout_index: (ref, item) for (ref, item), workout_index
                             in zip(source_items, source_workouts)}
        unused_sources = {ref: item for ref, item in source_items}
        expected_ref_by_workout = {}
        for target_index, (target_ref, count, set_targets) in enumerate(zip(target_refs, counts, assigned_targets)):
            target_index_value = workout_refs[target_ref]
            kept = source_by_workout.get(target_index_value)
            if kept and kept[0] in unused_sources:
                ref, item = kept
            elif unused_sources:
                ref, item = next(iter(unused_sources.items()))
                if source_workouts[source_refs.index(ref)] != target_index_value:
                    moves.append({'exerciseRef': ref, 'workoutRef': target_ref})
            else:
                ref, item = source_items[0]
                clone = copy.deepcopy(item)
                clone.pop('allocationBounds', None)
                clone['numWorkSets'] = count
                if 'targetSetPrescriptions' in clone:
                    clone['targetSetPrescriptions'] = _indexed_targets(set_targets)
                additions.append({'temporaryId': f'NEW_EXERCISE_REDIST_{group_index}_{target_index}',
                                  'workoutRef': target_ref, 'exercise': clone})
                expected_ref_by_workout[target_ref] = f'NEW_EXERCISE_REDIST_{group_index}_{target_index}'
                continue

            unused_sources.pop(ref)
            fields = {**structure_updates.pop(ref, {}), 'numWorkSets': count}
            if 'targetSetPrescriptions' in item:
                fields['targetSetPrescriptions'] = _indexed_targets(set_targets)
            updates.append({'exerciseRef': ref, 'setFields': fields})
            expected_ref_by_workout[target_ref] = ref

        removals.extend(sorted(unused_sources))
        for order in expanded.get('exerciseOrders', []):
            for ref in order.get('exerciseRefs', []):
                if ref in source_refs and expected_ref_by_workout.get(order.get('workoutRef')) != ref:
                    _fail('A redistribution order must reference the retained occurrence in that target session.',
                          'redistribution_order_reference_conflict', '/edits/exerciseOrders')
        manifest.append({'exerciseRefs': list(source_refs), 'workoutRefs': list(target_refs),
            'expectedRefByWorkout': expected_ref_by_workout, 'recipe': copy.deepcopy(first_recipe),
            'weeklyWorkSets': total_sets, 'minimumSessions': len(target_refs),
            'exactSetTargets': [target_content(target) for target in exact_targets] if any(
                'targetSetPrescriptions' in item for _, item in source_items) else None,
            'targetWorkoutIndexes': [ordered_workout_index[ref] for ref in target_refs],
            'sourcePositions': {ref: list(exercise_refs[ref]) for ref in source_refs}})

    updates_by_ref = {update['exerciseRef']: update for update in updates}
    for ref, fields in structure_updates.items():
        if ref in removals:
            continue
        update = updates_by_ref.get(ref)
        if update is None:
            updates.append({'exerciseRef': ref, 'setFields': fields})
        else:
            # Redistribution detaches its source; the selected menu owns the partner's final grouping.
            update['setFields'] = {**fields, **update.get('setFields', {})}
    return expanded, manifest


def redistribution_solver_constraints(contract):
    return [{key: copy.deepcopy(group[key]) for key in (
        'recipeSignature', 'weeklyWorkSets', 'exactSetTargets', 'targetWorkoutIndexes') if key in group}
        for group in (contract or {}).get('redistributions', [])]


def validated_repair_contract(owner, messages):
    """Rejected proposals are evidence, never authority for conserved doses."""
    authority = ('requirementsId', 'libraryFingerprint', 'historyFingerprint', 'resolvedDecisions')
    calls = {call.get('id') for message in messages for call in message.get('tool_calls', [])
             if call.get('function', {}).get('name') in ('audit_workout_plan', 'accept_workout_alternative')}
    candidates = [owner]
    for message in reversed(messages):
        if message.get('role') != 'tool' or message.get('tool_call_id') not in calls:
            continue
        try:
            candidate = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        if isinstance(candidate, dict) and all(candidate.get(key) == owner.get(key) for key in authority):
            candidates.append(candidate)
    for candidate in candidates:
        audit = candidate.get('audit')
        joint = candidate.get('coordinatedJointPlanning') or {}
        if (isinstance(audit, dict) and not audit.get('errors')
                and joint.get('feasible') is not False and joint.get('status') != 'unproven'
                and isinstance(candidate.get('repairContract'), dict)):
            return copy.deepcopy(candidate['repairContract'])
    return None


def build_repair_contract(objectives, source_draft, approved_requirements, expanded_edits, *, requirements_id=None):
    """Bind typed repair objectives to approved invariants and source recipes."""
    objectives = list(_recipe_objectives(
        [item for item in objectives if item.get('kind') == 'redistribute_work'], source_draft))
    manifest = copy.deepcopy(expanded_edits or [])
    _, source_refs = _stable_refs(source_draft)
    unmatched = list(objectives)
    for group in manifest:
        objective = next((item for item in unmatched
                          if set(item.get('exerciseRefs', [])) == set(group['exerciseRefs'])), None)
        if objective is not None:
            unmatched.remove(objective)
        expected_positions = {ref: list(source_refs[ref]) for ref in group['exerciseRefs'] if ref in source_refs}
        if expected_positions != group.get('sourcePositions'):
            _fail('The redistribution manifest does not belong to the current source draft.', 'stale_redistribution_source')
        source_items = [source_draft['workouts'][day]['exercises'][exercise]
            for day, exercise in expected_positions.values()]
        if (not source_items or any(_recipe(item) != group['recipe'] for item in source_items)
                or sum(item.get('numWorkSets', 0) for item in source_items) != group['weeklyWorkSets']):
            _fail('The redistribution manifest no longer matches its source prescriptions.', 'stale_redistribution_source')
        exact_targets = [target_content(target) for item in source_items
            for target in item.get('targetSetPrescriptions', [])]
        if group.get('exactSetTargets') is not None and sorted(map(_json, exact_targets)) != sorted(
                map(_json, group['exactSetTargets'])):
            _fail('The redistribution manifest no longer matches its exact set targets.', 'stale_redistribution_source')
        minimum_sessions = objective.get('minimumSessions') if objective is not None else None
        if objective is not None and (not isinstance(minimum_sessions, int) or isinstance(minimum_sessions, bool)
                or minimum_sessions < 2 or minimum_sessions > len(group['workoutRefs'])):
            _fail('The proposed redistribution does not satisfy its structured review objective.')
        group['minimumSessions'] = len(group['workoutRefs'])
        group['recipeSignature'] = redistribution_recipe_signature(group['recipe'])
        if (len(group.get('targetWorkoutIndexes', [])) != len(group['workoutRefs'])
                or len(set(group['targetWorkoutIndexes'])) != len(group['targetWorkoutIndexes'])):
            _fail('The redistribution targets do not map to distinct sessions after the declared workout order.')
    if unmatched:
        _fail('A structured redistribution objective has no matching executable edit.')
    return {'requirementsId': requirements_id, 'sessionsPerWeek': approved_requirements.get('sessionsPerWeek'),
        'requiredCoverage': copy.deepcopy(approved_requirements.get('requiredCoverage', [])),
        'redistributions': manifest}


def carry_repair_contract(previous_contract, current_contract, before_draft, after_draft, *,
                          requirements_id, workout_order=None):
    """Carry validated redistributions through unrelated repairs and reindexing."""
    current = copy.deepcopy(current_contract or {})
    supplied_current = current_contract or {}
    current['requirementsId'] = requirements_id
    current = _normalize_contract_groups(current, after_draft)
    if not previous_contract:
        # New outcome violations belong to the caller's structured preflight, not carried-repair lineage.
        return current
    previous = _normalize_contract_groups(previous_contract, before_draft)
    if (not requirements_id or previous.get('requirementsId') != requirements_id
            or current_contract and current_contract.get('requirementsId') not in (None, requirements_id)):
        _fail('A carried repair contract belongs to different or unbound approved requirements; revalidate a fresh candidate first.',
              'repair_contract_requirements_changed')

    # A later repair may add validated repair outcomes, but an omitted contract
    # must not erase the approved weekly schedule or coverage invariants already
    # carried from an earlier candidate. Explicit values must agree exactly.
    for field in ('sessionsPerWeek', 'requiredCoverage'):
        if field in supplied_current:
            if field in previous and supplied_current[field] != previous[field]:
                _fail(f'A carried repair cannot change the approved {field} invariant.',
                      'carried_repair_invariants_changed')
        elif field in previous:
            current[field] = copy.deepcopy(previous[field])

    before_workouts, _ = _stable_refs(before_draft)
    order = workout_order or list(before_workouts)
    if set(order) != set(before_workouts) or len(order) != len(before_workouts):
        _fail('Cannot rebase a carried repair contract through an incomplete workout order.',
              'carried_repair_contract_changed', '/edits/workoutOrder')
    new_workout_index = {reference: index for index, reference in enumerate(order)}
    after_workout_refs, after_exercise_refs = _stable_refs(after_draft)
    if len(after_workout_refs) != len(order):
        _fail('A carried repair contract cannot be rebased after adding or removing sessions.',
              'carried_repair_contract_changed')

    current_groups = current.get('redistributions', [])
    current_by_signature = {group.get('recipeSignature'): group for group in current_groups}
    carried = []
    for old_group in previous.get('redistributions', []):
        replacement = current_by_signature.get(old_group.get('recipeSignature'))
        if replacement is not None:
            if replacement.get('weeklyWorkSets') != old_group.get('weeklyWorkSets'):
                _fail('An explicit redistribution cannot change the previously approved weekly work-set total.',
                      'carried_repair_contract_changed')
            old_targets = old_group.get('exactSetTargets')
            new_targets = replacement.get('exactSetTargets')
            if ((old_targets is None) != (new_targets is None)
                    or old_targets is not None and sorted(map(_json, old_targets)) != sorted(map(_json, new_targets))):
                _fail('An explicit redistribution cannot change the previously approved exact set prescriptions.',
                      'carried_repair_contract_changed')
            if replacement.get('minimumSessions', 0) < old_group.get('minimumSessions', 0):
                _fail('The replacement redistribution weakens the previously validated session spread.',
                      'carried_repair_objective_weakened')
            continue
        rebased = copy.deepcopy(old_group)
        old_targets = rebased.get('targetWorkoutRefs') or rebased.get('workoutRefs')
        if not isinstance(old_targets, list) or any(ref not in new_workout_index for ref in old_targets):
            _fail('A validated redistribution target no longer has stable session identity.',
                  'carried_repair_contract_changed')
        target_indexes = [new_workout_index[reference] for reference in old_targets]
        rebased['targetWorkoutIndexes'] = target_indexes
        rebased['targetWorkoutRefs'] = [f'WORKOUT_{index}' for index in target_indexes]
        rebased['workoutRefs'] = list(rebased['targetWorkoutRefs'])
        signature_recipe = rebased['recipe']
        matching = []
        for reference, (workout_index, exercise_index) in after_exercise_refs.items():
            item = after_draft['workouts'][workout_index]['exercises'][exercise_index]
            if workout_index in target_indexes and _recipe(item) == signature_recipe:
                matching.append((reference, workout_index, exercise_index))
        rebased['exerciseRefs'] = [reference for reference, _, _ in matching]
        rebased['sourcePositions'] = {reference: [workout_index, exercise_index]
            for reference, workout_index, exercise_index in matching}
        rebased['expectedRefByWorkout'] = {}
        for reference, workout_index, _ in matching:
            if workout_index in target_indexes:
                rebased['expectedRefByWorkout'][f'WORKOUT_{workout_index}'] = reference
        if not matching:
            _fail('A later repair changed or removed the protected recipe without a matching explicit redistribution objective.',
                  'carried_repair_contract_changed')
        carried.append(rebased)

    merged = _normalize_contract_groups(
        {**current, 'redistributions': [*current_groups, *carried]}, after_draft)
    errors = repair_contract_errors(merged, after_draft)
    if errors:
        _fail('A later repair changed a protected redistribution. Submit an explicit same-recipe redistribution repair or preserve the validated recipe outcome. '
              + json.dumps(errors, ensure_ascii=False), 'carried_repair_contract_changed')
    return merged


def repair_contract_errors(contract, candidate_draft):
    """Return outcome violations; callers may use this before and after solving."""
    errors = []
    workouts = candidate_draft.get('workouts', [])
    planned_sessions = sum(workout.get('timesCompletedInAWeek', 1) for workout in workouts)
    if (contract.get('sessionsPerWeek') is not None
            and planned_sessions != contract['sessionsPerWeek']):
        errors.append({'code': 'repair_session_count_changed', 'path': '/workouts',
            'message': 'The repair changed the approved number of weekly sessions.'})
    rules = {item['key']: item for item in contract.get('requiredCoverage', [])}
    weekly, per_session = set(), []
    for index, workout in enumerate(workouts):
        covered = {key for exercise in workout.get('exercises', [])
                   for key in exercise.get('satisfiesCoverage', []) if key in rules}
        per_session.append(covered)
        weekly.update(covered)
        for key, rule in rules.items():
            if rule.get('scope') == 'eachSession' and key not in covered:
                errors.append({'code': 'required_coverage_missing', 'path': f'/workouts/{index}/exercises',
                    'coverageKey': key, 'message': f'{key} is missing from WORKOUT_{index}.'})
    for key, rule in rules.items():
        if rule.get('scope') == 'weekly' and key not in weekly:
            errors.append({'code': 'required_coverage_missing', 'path': '/workouts', 'coverageKey': key,
                'message': f'{key} is missing from the weekly plan.'})

    for group in contract.get('redistributions', []):
        signature = _recipe(group['recipe'])
        total, outside_targets = 0, set()
        found_targets = set()
        target_indices = set(group['targetWorkoutIndexes'])
        for workout_index, workout in enumerate(workouts):
            for exercise in workout.get('exercises', []):
                if _recipe(exercise) != signature:
                    continue
                sets = exercise.get('numWorkSets', 0)
                frequency = workout.get('timesCompletedInAWeek', 1)
                total += sets * frequency
                if workout_index in target_indices:
                    if sets > 0:
                        found_targets.add(workout_index)
                else:
                    outside_targets.add(workout_index)
        if outside_targets:
            errors.append({'code': 'redistribution_recipe_outside_targets', 'path': '/workouts',
                'exerciseRefs': group['exerciseRefs'], 'workoutIndexes': sorted(outside_targets),
                'targetWorkoutIndexes': sorted(target_indices),
                'message': 'A redistributed recipe may appear only in its declared target sessions.'})
        if total != group['weeklyWorkSets']:
            errors.append({'code': 'redistribution_weekly_sets_changed', 'path': '/workouts',
                'exerciseRefs': group['exerciseRefs'], 'expected': group['weeklyWorkSets'], 'actual': total,
                'message': 'The redistributed recipe must preserve its exact weekly working-set total.'})
        if len(found_targets) < group['minimumSessions']:
            errors.append({'code': 'redistribution_sessions_not_met', 'path': '/workouts',
                'exerciseRefs': group['exerciseRefs'], 'minimumSessions': group['minimumSessions'],
                'actualSessions': len(found_targets),
                'message': 'The redistributed recipe is not present in enough distinct target sessions.'})
        expected_targets = group.get('exactSetTargets')
        if expected_targets is not None:
            actual_targets = [target for index, workout in enumerate(workouts) if index in target_indices
                for exercise in workout.get('exercises', [])
                if _recipe(exercise) == signature
                for target in (exercise.get('targetSetPrescriptions')
                    if exercise.get('targetSetPrescriptions') is not None
                    else [None] * exercise.get('numWorkSets', 0))]
            actual_content = [target_content(target) for target in actual_targets if target is not None]
            if sorted(map(_json, actual_content)) != sorted(map(_json, expected_targets)):
                errors.append({'code': 'redistribution_set_targets_changed', 'path': '/workouts',
                    'exerciseRefs': group['exerciseRefs'],
                    'message': 'The redistribution must preserve every exact per-set prescription.'})
    return errors
