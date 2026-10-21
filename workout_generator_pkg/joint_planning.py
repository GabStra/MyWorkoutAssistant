"""Choose an executable week from finite, validated prescription recipes."""

import copy
import hashlib
import itertools
import json
import math
import time
from collections import Counter

from jsonschema import Draft7Validator, ValidationError

from .allocation import _audit_raw, _milp_solve
from .generation_audit import ASSUMPTIONS
from .planning_tools import _DRAFT_SCHEMA
from .programming_guidelines import (
    approved_work_set_bounds, audit_execution_details, audit_execution_rules,
)
from .recipe_contracts import progression_capability, progression_margin, recorded_evidence

SELECTION_POLICY_VERSION = 10
RECORDED_EVIDENCE_POLICY_VERSION = 1
JOINT_REPAIRABLE_AUDIT_ERRORS = frozenset({
    'volume_below_target', 'volume_above_target', 'duration_exceeded',
    'required_coverage_missing', 'superset_set_count_mismatch',
})


def prescription_fingerprint(sessions):
    return hashlib.sha256(json.dumps([{key: value for key, value in day.items() if key not in ('name', 'description')}
        | {'exercises': [{key: value for key, value in item.items() if key not in ('placementNotes', 'satisfiesCoverage')} for item in day['exercises']]}
        for day in sessions], sort_keys=True).encode()).hexdigest()


def candidate_menu_fingerprint(workouts):
    """Identify substantive movement choices, placements, and pairings only.

    Numeric allocation, labels, local coaching notes, and other metadata do not
    expand the candidate menu. The source order and superset membership do,
    because they change executable placement and setup choices.
    """
    canonical = []
    for day in workouts or []:
        blocks, index = [], 0
        exercises = day.get('exercises', [])
        while index < len(exercises):
            item = exercises[index]
            group = item.get('superset')
            members = [item.get('definition_id')]
            index += 1
            if group is not None:
                while index < len(exercises) and exercises[index].get('superset') == group:
                    members.append(exercises[index].get('definition_id'))
                    index += 1
            blocks.append({'members': members, 'paired': len(members) > 1})
        canonical.append({'timesCompletedInAWeek': day.get('timesCompletedInAWeek'), 'blocks': blocks})
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()


def joint_problem_fingerprint(sessions, requirements, equipment, history=None, messages=None,
                              *, restriction_policy=None, existing=None,
                              allow_educated_load_guesses=True,
                              preserve_source_selection=False):
    from .planning_tools import AUDIT_VERSION, library_fingerprint

    current_history = getattr(history, 'fingerprint', None)
    library_hash = library_fingerprint(equipment)
    full_workouts = [*(existing or {}).get('workouts', []), *sessions]
    payload = {'requirements': requirements,
        'inputWorkouts': [{key: value for key, value in day.items() if key not in ('name', 'description')}
                          for day in full_workouts],
        'prescriptionFingerprint': prescription_fingerprint(full_workouts),
        'libraryFingerprint': library_hash, 'historyFingerprint': current_history,
        'recordedEvidencePolicyVersion': RECORDED_EVIDENCE_POLICY_VERSION,
        'recordedEvidence': recorded_evidence(messages or [], library_hash, current_history),
        'selectionPolicyVersion': SELECTION_POLICY_VERSION, 'auditVersion': AUDIT_VERSION,
        'preserveSourceSelection': bool(preserve_source_selection),
        'restrictionPolicy': restriction_policy,
        'allowEducatedLoadGuesses': allow_educated_load_guesses}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _joint_model_domain_fingerprint(variables, features, *, library_hash, history_fingerprint,
                                    evidence, restriction_policy, allow_educated_load_guesses,
                                    preserve_source_selection):
    """Hash the actual finite-domain rows, variable bounds and source identities.

    Objective coefficients and current count seeds are intentionally omitted. The
    option identities carry generated counts, muscle credits and timing; matrix
    rows bind those alternatives to every hard feasibility constraint.
    """
    def finite_value(value):
        if isinstance(value, float) and math.isinf(value):
            return 'Infinity' if value > 0 else '-Infinity'
        return value

    feasibility_indexes = [index for index, variable in enumerate(variables)
        if not (isinstance(variable.get('domainIdentity'), dict)
            and variable['domainIdentity'].get('kind') == 'coverage_balance_deviation')]
    index_map = {old: new for new, old in enumerate(feasibility_indexes)}
    variable_domain = [{
        'lower': finite_value(variable['lower']),
        'upper': finite_value(variable['upper']),
        'integer': True,
        'identity': variable.get('domainIdentity'),
    } for index, variable in enumerate(variables) if index in index_map]
    rows = []
    for label, lower, upper, intercept, coefficients in features:
        # Coverage-balance deviations are optional objective slack. They can never
        # turn an otherwise infeasible plan into a feasible one, so they are not
        # part of the hard feasibility domain identity.
        if isinstance(label, tuple) and label and label[0] == 'coverage_balance':
            continue
        coefficient_items = (coefficients.items() if isinstance(coefficients, dict)
                             else enumerate(coefficients))
        rows.append({
            'label': label,
            'lower': finite_value(lower),
            'upper': finite_value(upper),
            'intercept': finite_value(intercept),
            'coefficients': [[index_map[index], value] for index, value in sorted(coefficient_items)
                             if value and index in index_map],
        })
    payload = {
        'modelDomainVersion': 2,
        'variables': variable_domain,
        'constraints': rows,
        'libraryFingerprint': library_hash,
        'historyFingerprint': history_fingerprint,
        'recordedEvidencePolicyVersion': RECORDED_EVIDENCE_POLICY_VERSION,
        'recordedEvidence': evidence,
        'restrictionPolicy': restriction_policy,
        'allowEducatedLoadGuesses': bool(allow_educated_load_guesses),
        'preserveSourceSelection': bool(preserve_source_selection),
        'selectionPolicyVersion': SELECTION_POLICY_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def _repair_candidate_binding(messages, candidate_id):
    calls = {call.get('id'): call.get('function', {})
             for message in messages or [] for call in message.get('tool_calls', [])}
    diagnosed = []
    for index, message in enumerate(messages or []):
        if calls.get(message.get('tool_call_id'), {}).get('name') != 'propose_workout_alternatives':
            continue
        try:
            payload = json.loads(message.get('content', ''))
        except (TypeError, ValueError):
            continue
        for candidate in payload.get('alternativeRepairCandidates', []):
            if candidate.get('repairCandidateId') == candidate_id:
                return candidate
            diagnosed.append((index, candidate))
    # A failed independent review creates a new materialized revision ID. Resolve
    # it through the same validated lineage authority used by planner resumption.
    from .alternative_repair import _latest_materialized_reviewed_candidate
    for index, candidate in reversed(diagnosed):
        materialized = _latest_materialized_reviewed_candidate(messages, candidate, after_index=index)
        if materialized and materialized.get('repairCandidateId') == candidate_id:
            return materialized
    return None


def _current_repair_identity(messages):
    for message in reversed(messages or []):
        if message.get('role') != 'assistant':
            continue
        for call in reversed(message.get('tool_calls', [])):
            function = call.get('function', {})
            if function.get('name') != 'repair_workout_alternative':
                continue
            try:
                arguments = json.loads(function.get('arguments', '{}'))
            except (TypeError, ValueError):
                continue
            candidate_id = arguments.get('repairCandidateId')
            source_candidate = _repair_candidate_binding(messages, candidate_id)
            if not source_candidate:
                continue
            expected_original = arguments.get('originalRequirementsId')
            if expected_original != source_candidate.get('originalRequirementsId'):
                continue
            return source_candidate
    return None


def _known_infeasible_repair_domain(messages, domain_fingerprint,
                                    library_hash, history_fingerprint):
    """Find a proven prior repair-domain failure for this exact candidate authority."""
    source_candidate = _current_repair_identity(messages)
    if not source_candidate:
        return None
    calls = {call.get('id'): call.get('function', {})
             for message in messages or [] for call in message.get('tool_calls', [])}
    for index in reversed(range(len(messages or []))):
        message = messages[index]
        if calls.get(message.get('tool_call_id'), {}).get('name') != 'repair_workout_alternative':
            continue
        try:
            result = json.loads(message.get('content', ''))
        except (TypeError, ValueError):
            continue
        receipt = result.get('jointSolve') if isinstance(result, dict) else None
        snapshot = result.get('candidateSnapshot') if isinstance(result, dict) else None
        if (not isinstance(receipt, dict) or receipt.get('status') != 'infeasible'
                or result.get('attemptStatus') != 'repair_menu_infeasible'
                or receipt.get('rejectedOptions')
                or not isinstance(snapshot, dict)):
            continue
        bound_keys = ('repairCandidateId', 'originalRequirementsId', 'originalRequirementsHash',
                      'requirementsId', 'sourceDraftId', 'sourceMenuFingerprint',
                      'libraryFingerprint', 'trainingHistoryFingerprint')
        if any(snapshot.get(key, snapshot.get('baseDraftId') if key == 'sourceDraftId' else None)
               != source_candidate.get(key, source_candidate.get('baseDraftId') if key == 'sourceDraftId' else None)
               for key in bound_keys):
            continue
        if (result.get('repairCandidateId') != source_candidate.get('repairCandidateId')
                or result.get('originalRequirementsId') != source_candidate.get('originalRequirementsId')
                or result.get('requirementsId') != source_candidate.get('requirementsId')
                or result.get('libraryFingerprint') != library_hash
                or result.get('trainingHistoryFingerprint') != history_fingerprint):
            continue
        prior_domain = receipt.get('feasibilityDomainFingerprint')
        prior_policy = receipt.get('selectionPolicyVersion')
        if (prior_domain and prior_domain == domain_fingerprint
                and prior_policy == SELECTION_POLICY_VERSION
                and receipt.get('preserveSourceSelection') is True):
            return {'receipt': copy.deepcopy(receipt), 'sourceResultIndex': index,
                    'match': 'generated_model_domain'}
    return None


def joint_objective_input_fingerprint(sessions, requirements, equipment, history=None, messages=None,
                                      *, restriction_policy=None, allow_educated_load_guesses=True,
                                      preserve_source_selection=False):
    """Bind reusable solver work to the prescription/objective, ignoring only within-session order and display metadata."""
    from .planning_tools import AUDIT_VERSION, library_fingerprint

    library_hash = library_fingerprint(equipment)
    canonical_sessions = []
    for day in sessions:
        blocks = [block for block in _blocks([day])]
        blocks.sort(key=lambda block: json.dumps(block, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        # Setup time depends on the first block. Preserve it in the identity even
        # though the rest of the submitted order is irrelevant to these objectives.
        first_block = (next(_blocks([day]), [])
            if requirements.get('auditTargets', {}).get('maximumSessionSeconds') is not None else None)
        canonical_sessions.append({'timesCompletedInAWeek': day['timesCompletedInAWeek'],
            'firstBlock': first_block,
            'blocks': blocks})
    payload = {'requirements': requirements, 'objectiveInput': canonical_sessions,
        'libraryFingerprint': library_hash, 'historyFingerprint': getattr(history, 'fingerprint', None),
        'recordedEvidencePolicyVersion': RECORDED_EVIDENCE_POLICY_VERSION,
        'recordedEvidence': recorded_evidence(messages or [], library_hash, getattr(history, 'fingerprint', None)),
        'selectionPolicyVersion': SELECTION_POLICY_VERSION, 'auditVersion': AUDIT_VERSION,
        'preserveSourceSelection': bool(preserve_source_selection),
        'restrictionPolicy': restriction_policy,
        'allowEducatedLoadGuesses': allow_educated_load_guesses}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

_DRAFT_VALIDATOR = Draft7Validator(_DRAFT_SCHEMA)


def _blocks(sessions, standalone=False):
    for block, _ in _blocks_with_source_positions(sessions, standalone=standalone):
        yield block


def _blocks_with_source_positions(sessions, standalone=False):
    seen = {}
    for workout_index, day in enumerate(sessions):
        occurrences = {}
        for _, members in itertools.groupby(enumerate(day['exercises']),
                lambda entry: ('group', entry[1]['superset']) if entry[1]['superset'] is not None
                    else ('single', entry[0])):
            entries = list(members)
            positions = [(workout_index, index) for index, _ in entries]
            block = copy.deepcopy([item for _, item in entries])
            for item in block:
                item['superset'] = 'RECIPE' if len(block) > 1 else None
            key = json.dumps(block, sort_keys=True)
            occurrences[key] = occurrences.get(key, 0) + 1
            if occurrences[key] <= seen.get(key, 0):
                continue
            seen[key] = occurrences[key]
            yield block, positions
            if standalone and len(block) > 1:
                # Proposed pairing is optional; retain round recovery before applying approved straight-set ranges.
                recovery = sum(item['restAfterSupersetExerciseSeconds'] for item in block)
                for item, position in zip(block, positions):
                    single = copy.deepcopy(item)
                    single.update(superset=None, restBetweenSetsSeconds=recovery,
                                  restAfterSupersetExerciseSeconds=0)
                    yield [single], [position]


def prescription_patch(before, after, occurrence_lineage=None):
    """Create a patch that reproduces the solver result."""
    if occurrence_lineage is not None:
        return _lineage_prescription_patch(before, after, occurrence_lineage)
    patch = []
    for day_index, (old, new) in enumerate(zip(before, after)):
        for field in ('name', 'description'):
            if old.get(field) != new.get(field):
                patch.append({'op': 'replace', 'path': f'/workouts/{day_index}/{field}', 'value': new[field]})
        path = f'/workouts/{day_index}/exercises'
        if [e['definition_id'] for e in old['exercises']] != [e['definition_id'] for e in new['exercises']]:
            patch.extend({'op': 'remove', 'path': f'{path}/{i}'} for i in reversed(range(len(old['exercises']))))
            patch.extend({'op': 'add', 'path': path + '/-', 'value': copy.deepcopy(item)} for item in new['exercises'])
            continue
        for index, (a, b) in enumerate(zip(old['exercises'], new['exercises'])):
            for key in sorted(a.keys() | b.keys()):
                field = f'{path}/{index}/{key}'
                if key not in b:
                    patch.append({'op': 'remove', 'path': field})
                elif key not in a or a[key] != b[key]:
                    patch.append({'op': 'replace' if key in a else 'add', 'path': field, 'value': copy.deepcopy(b[key])})
    return patch


def _lineage_prescription_patch(before, after, occurrence_lineage):
    if len(after) != len(before) or len(occurrence_lineage) != len(after):
        raise ValueError('Solver occurrence lineage does not match the submitted workout schedule.')
    source_tokens = {(workout, exercise) for workout, day in enumerate(before)
                     for exercise in range(len(day['exercises']))}
    retained, patch = set(), []
    for workout, (day, solved, lineage) in enumerate(zip(before, after, occurrence_lineage)):
        if len(solved['exercises']) != len(lineage):
            raise ValueError('Solver occurrence lineage does not match the solved exercise list.')
        for solved_index, source in enumerate(lineage):
            if source is None:
                continue
            token = tuple(source)
            if token not in source_tokens or token in retained:
                raise ValueError('Solver occurrence lineage contains a missing or repeated source occurrence.')
            retained.add(token)
            source_workout, source_index = token
            original = before[source_workout]['exercises'][source_index]
            solved_item = solved['exercises'][solved_index]
            if original['definition_id'] != solved_item['definition_id']:
                raise ValueError('Solver occurrence lineage changes an exercise definition.')
            for key in sorted(original.keys() | solved_item.keys()):
                field = f'/workouts/{source_workout}/exercises/{source_index}/{key}'
                if key not in solved_item:
                    patch.append({'op': 'remove', 'path': field})
                elif key not in original or original[key] != solved_item[key]:
                    patch.append({'op': 'replace' if key in original else 'add', 'path': field,
                                  'value': copy.deepcopy(solved_item[key])})
        for field in ('name', 'description', 'trainingDays', 'timesCompletedInAWeek'):
            if day.get(field) != solved.get(field):
                patch.append({'op': 'replace', 'path': f'/workouts/{workout}/{field}',
                              'value': copy.deepcopy(solved.get(field))})

    tokens_by_workout = [[(workout, index) for index in range(len(day['exercises']))]
                         for workout, day in enumerate(before)]
    for workout in range(len(tokens_by_workout)):
        for index in reversed(range(len(tokens_by_workout[workout]))):
            if tokens_by_workout[workout][index] not in retained:
                patch.append({'op': 'remove', 'path': f'/workouts/{workout}/exercises/{index}'})
                tokens_by_workout[workout].pop(index)

    for workout, (solved, lineage) in enumerate(zip(after, occurrence_lineage)):
        for index, source in enumerate(lineage):
            if source is None:
                patch.append({'op': 'add', 'path': f'/workouts/{workout}/exercises/{index}',
                              'value': copy.deepcopy(solved['exercises'][index])})
                tokens_by_workout[workout].insert(index, None)
                continue
            token = tuple(source)
            source_workout = next((i for i, tokens in enumerate(tokens_by_workout) if token in tokens), None)
            if source_workout is None:
                raise ValueError('Solver occurrence lineage lost a retained source occurrence.')
            source_index = tokens_by_workout[source_workout].index(token)
            if source_workout != workout or source_index != index:
                patch.append({'op': 'move', 'from': f'/workouts/{source_workout}/exercises/{source_index}',
                              'path': f'/workouts/{workout}/exercises/{index}'})
                tokens_by_workout[source_workout].pop(source_index)
                tokens_by_workout[workout].insert(index, token)
    return patch


def _rest_options(block, requirements, definitions, work_set_count):
    """Only explicit approved ranges authorize automatic rest changes."""
    yield block
    minimum = copy.deepcopy(block)
    for index, item in enumerate(minimum):
        context = 'straightSets' if len(block) == 1 else (
            'supersetRound' if index == len(block) - 1 else 'supersetTransition')
        rules = [rule for rule in requirements.get('executionRules', []) if rule['kind'] == 'rest'
            and rule['context'] == context
            and (context == 'supersetTransition' or work_set_count > 1)
            and (rule['coverageKey'] is None or rule['coverageKey'] in item.get('satisfiesCoverage', []))
            and (not rule.get('exerciseCategory')
                 or rule['exerciseCategory'] == definitions[item['definition_id']].get('exerciseCategory'))]
        if rules:
            lower = max(rule['minimumSeconds'] for rule in rules)
            upper = min(rule['maximumSeconds'] for rule in rules)
            if lower > upper:
                return
            field = 'restBetweenSetsSeconds' if len(block) == 1 else 'restAfterSupersetExerciseSeconds'
            item[field] = lower
    if minimum != block:
        yield minimum


def _recipe_signature(block):
    return json.dumps([{key: value for key, value in item.items() if key not in ('numWorkSets', 'allocationBounds')}
                       for item in block], sort_keys=True)


def _execution_order(blocks, chosen, requirements):
    selected = {index for index, block in enumerate(blocks) if any(chosen[option] for option in block['options'])}
    dependencies = {index: set() for index in selected}
    for before in selected:
        for after in selected - {before}:
            if any(rule['kind'] == 'order'
                   and rule['before'] in blocks[before]['recipe']['roles']
                   and rule['after'] in blocks[after]['recipe']['roles']
                   for rule in requirements.get('executionRules', [])):
                dependencies[after].add(before)
    ordered = []
    while dependencies:
        ready = [index for index, predecessors in dependencies.items() if not predecessors]
        if not ready:
            raise ValueError('Selected recipe ordering is cyclic.')
        index = min(ready, key=lambda index: (blocks[index]['sourceRank'], index))
        ordered.append(index)
        del dependencies[index]
        for predecessors in dependencies.values():
            predecessors.discard(index)
    return ordered


def solve_prescribed_week(sessions, requirements, equipment, restriction_policy=None, existing=None,
                          allow_educated_load_guesses=True, *, training_history=None, messages=None, balance=False,
                          preserve_source_selection=False):
    """Solve selection, placement, counts, grouping, allowed rests and ordering together.

    Options keep supported loads/reps, tempo, calibration and warm-ups intact. All
    timing coefficients come from the production audit, not a second time model.
    """
    started = time.monotonic()
    try:
        _DRAFT_VALIDATOR.validate({'requirementsId': 'recipes', 'name': 'Recipes', 'workouts': sessions})
    except ValidationError as error:
        return {'feasible': False, 'status': 'invalid_options', 'instruction': error.message}
    proof = {'problemFingerprint': joint_problem_fingerprint(sessions, requirements, equipment,
        training_history, messages, restriction_policy=restriction_policy, existing=existing,
        allow_educated_load_guesses=allow_educated_load_guesses,
        preserve_source_selection=preserve_source_selection)}
    frequency = sum(day['timesCompletedInAWeek'] for day in [*(existing or {}).get('workouts', []), *sessions])
    if requirements.get('sessionsPerWeek') is not None and frequency != requirements['sessionsPerWeek']:
        return {**proof, 'feasible': False, 'status': 'invalid_schedule',
                'instruction': 'The recipe schedule does not match the approved weekly frequency. Correct the schedule; do not relax requirements.'}
    definitions = {f'LIBRARY_{index}': value for index, value in enumerate(
        sorted(equipment['exerciseDefinitions'], key=lambda item: item['id']))}
    unknown = {item['definition_id'] for day in sessions for item in day['exercises']} - definitions.keys()
    if unknown:
        return {**proof, 'feasible': False, 'status': 'invalid_options',
                'instruction': f'Unknown prescription library references: {sorted(unknown)}.'}
    variables, constraints, recipes, rejected = [], [], [], []
    from .planning_tools import library_fingerprint
    from .training_history import apply_native_load_calibration_policy
    evidence = recorded_evidence(messages or [], library_fingerprint(equipment), getattr(training_history, 'fingerprint', None))
    capabilities = {ref: progression_capability(definition, equipment, evidence.get(definition['id']))
                    for ref, definition in definitions.items() if any(
                        item['definition_id'] == ref for day in sessions for item in day['exercises'])}
    source_ranks_by_identity = []
    source_blocks_by_identity = []
    source_blocks = []
    source_recipe_positions = []
    for workout_index, day in enumerate(sessions):
        occurrence_by_signature = Counter()
        indexed = {}
        for block, positions in _blocks_with_source_positions([day]):
            signature = _recipe_signature(block)
            occurrence = occurrence_by_signature[signature]
            occurrence_by_signature[signature] += 1
            indexed[(signature, occurrence)] = (block,
                [(workout_index, index) for _, index in positions])
        source_blocks.append(indexed)
    for workout_index, day in enumerate(sessions):
        occurrence_by_signature = Counter()
        indexed = {}
        for block, positions in _blocks_with_source_positions([day], standalone=True):
            signature = _recipe_signature(block)
            occurrence = occurrence_by_signature[signature]
            occurrence_by_signature[signature] += 1
            indexed[(signature, occurrence)] = [(workout_index, index) for _, index in positions]
        source_recipe_positions.append(indexed)
    source_block_edit_offset = sum(block[0]['numWorkSets'] * len(block)
        for day in source_blocks for block, _ in day.values())
    for day in sessions:
        ranks, blocks, counts = {}, [], {}
        for rank, block in enumerate(_blocks([day])):
            identity = tuple(item['definition_id'] for item in block)
            occurrence = counts.get(identity, 0)
            counts[identity] = occurrence + 1
            ranks.setdefault(identity, []).append(rank)
            blocks.append(identity)
        source_ranks_by_identity.append(ranks)
        source_blocks_by_identity.append(blocks)
    recipe_occurrences = [{} for _ in sessions]
    validate_loads = None
    if training_history:
        validate_loads = (training_history.load_suitability_validator(messages, equipment)
            if hasattr(training_history, 'load_suitability_validator') else
            lambda plan: training_history.load_suitability_errors(plan, messages, equipment))

    def variable(upper=1, cost=0, domain_identity=None):
        index = len(variables)
        variables.append({'lower': 0, 'upper': upper, 'current': [], 'members': [],
                          'objectiveCost': cost, 'domainIdentity': domain_identity})
        return index

    def constraint(label, lower, upper, coefficients, intercept=0):
        constraints.append((label, lower, upper, intercept, coefficients))

    numeric_errors = JOINT_REPAIRABLE_AUDIT_ERRORS
    # Audit one recipe once per count; those contributions are reusable in every session.
    for block, source_positions in _blocks_with_source_positions(sessions, standalone=True):
        workout_index = source_positions[0][0]
        recipe_identity = tuple(item['definition_id'] for item in block)
        signature = _recipe_signature(block)
        source_key = next((key for key, positions in source_recipe_positions[workout_index].items()
            if key[0] == signature and positions == source_positions), None)
        if source_key is None:
            return {**proof, 'feasible': False, 'status': 'invalid_options',
                'errors': [{'code': 'recipe_source_identity_missing', 'workoutIndex': workout_index,
                    'sourcePositions': copy.deepcopy(source_positions)}],
                'instruction': ('A submitted movement recipe could not be bound to its exact source occurrence. '
                    'Preserve the input; no infeasibility was established.')}
        source_signature_occurrence = source_key[1]
        recipe_occurrence = recipe_occurrences[workout_index].get(recipe_identity, 0)
        recipe_occurrences[workout_index][recipe_identity] = recipe_occurrence + 1
        bounds = [approved_work_set_bounds(item, definitions[item['definition_id']], requirements) for item in block]
        lower, upper = max(b['minimum'] for b in bounds), min(b['maximum'] for b in bounds)
        exact = {item['numWorkSets'] for item in block if item.get('targetSetPrescriptions')}
        if exact:
            if len(exact) != 1:
                rejected.append({'code': 'incompatible_exact_group_counts'})
                continue
            lower, upper = max(lower, next(iter(exact))), min(upper, next(iter(exact)))
        options = []
        for count in range(lower, upper + 1):
            for variant in _rest_options(block, requirements, definitions, count):
                items = copy.deepcopy(variant)
                for item, bound in zip(items, bounds):
                    item.update(numWorkSets=count, allocationBounds=bound)
                day = {'name': 'Recipe', 'description': 'Prescription option', 'timesCompletedInAWeek': 1,
                       'exercises': items}
                draft = {'requirementsId': 'recipe', 'name': 'Recipe', 'workouts': [day]}
                try:
                    _DRAFT_VALIDATOR.validate(draft)
                    plan, report = _audit_raw(draft, equipment, requirements, restriction_policy, allow_educated_load_guesses)
                    audit_execution_rules(draft, requirements, report, plan)
                    details = {'issues': [], 'errors': []}
                    audit_execution_details(draft, requirements, details)
                    report['errors'].extend(e for e in details['errors'] if not e['code'].startswith('schedule_'))
                except (ValueError, ValidationError) as error:
                    rejected.append({'code': 'invalid_recipe', 'message': getattr(error, 'message', str(error))})
                    continue
                blockers = [error for error in report['errors'] if error['code'] not in numeric_errors]
                # Missing weekly coverage is expected for a single recipe, never an execution exemption.
                if blockers:
                    rejected.extend(blockers)
                    continue
                apply_native_load_calibration_policy(plan, messages or [], equipment,
                    getattr(training_history, 'fingerprint', None),
                    allow_educated_load_guesses=allow_educated_load_guesses)
                if validate_loads and validate_loads(plan):
                    continue
                workout = report['workouts'][0]
                setup = items[0].get('setupSeconds', ASSUMPTIONS['transitionSeconds'])
                options.append({'items': items, 'count': count, 'volume': workout['volume'],
                    'coverage': workout.get('coverageSets', {}),
                    'preferenceCost': 0 if variant == block else .1,
                    'seconds': workout['estimatedSeconds'] - ASSUMPTIONS['generalWarmupSeconds'] + setup})
        if options:
            recipes.append({'options': options,
                'setup': options[0]['items'][0].get('setupSeconds', ASSUMPTIONS['transitionSeconds']),
                'signature': signature, 'sourceSignatureOccurrence': source_signature_occurrence,
                'sourcePositions': source_positions,
                'identity': recipe_identity, 'occurrence': recipe_occurrence,
                'roles': set().union(*(set(item.get('satisfiesCoverage', [])) for item in block)),
                'definitions': {item['definition_id'] for item in block}})
    if not recipes:
        return {**proof, 'feasible': False, 'status': 'invalid_options', 'rejectedOptions': rejected[:20],
                'instruction': 'No executable prescription options remain. Correct the supplied recipes; preserve approved requirements.'}

    day_blocks, option_variables = [], []
    progression_penalties = {}
    concentration_costs = {}
    preservation_costs = {}
    for day_index, day in enumerate(sessions):
        blocks, blocks_by_source = [], {}
        for recipe_index, recipe in enumerate(recipes):
            indices = []
            for option in recipe['options']:
                # Keep preservation, distribution and progression as separate approved objectives.
                original = source_blocks[day_index].get(
                    (recipe['signature'], recipe['sourceSignatureOccurrence']))
                if original:
                    source_sets = original[0][0]['numWorkSets'] * len(original[0])
                    # The constant omission cost is added once below. This relative
                    # coefficient makes retaining a source occurrence worth its
                    # true set-count edit distance, including when it is omitted.
                    edits = (abs(option['count'] - original[0][0]['numWorkSets'])
                             * len(option['items']) - source_sets)
                else:
                    edits = option['count'] * len(option['items'])
                index = variable(domain_identity={
                    'kind': 'recipe_option', 'workoutIndex': day_index,
                    'sourcePositions': recipe['sourcePositions'],
                    'definitionIds': list(recipe['identity']),
                    'workSetCount': option['count'], 'volume': option['volume'],
                    'coverage': option['coverage'], 'seconds': option['seconds'],
                })
                preservation_costs[index] = edits + option['preferenceCost']
                progression_penalties[index] = sum(
                    progression_margin(item, capabilities[item['definition_id']])['penalty']
                    for item in option['items'])
                concentration_costs[index] = option['count'] ** 2 * len(option['items'])
                indices.append(index)
                option_variables.append((index, day_index, recipe_index, option))
            constraint(('recipe_choice', day_index, recipe_index), 0, 1, dict.fromkeys(indices, 1))
            source_key = (recipe['signature'], recipe['sourceSignatureOccurrence'])
            block = blocks_by_source.get(source_key)
            if block is None:
                identity_ranks = source_ranks_by_identity[day_index].get(recipe['identity'], [])
                source_rank = (identity_ranks[recipe['occurrence']] if recipe['occurrence'] < len(identity_ranks)
                               else identity_ranks[-1] if identity_ranks
                               else len(recipes) + recipe_index)
                block = {'options': [], 'recipeIndexes': [], 'recipe': recipe,
                         'sourceRank': source_rank, 'setup': recipe['setup'], 'first': variable(
                             domain_identity={'kind': 'first_block', 'workoutIndex': day_index,
                                 'sourcePositions': recipe['sourcePositions'],
                                 'definitionIds': list(recipe['identity']),
                                 'setupSeconds': recipe['setup'],
                                 'coverageRoles': sorted(recipe['roles'])})}
                blocks_by_source[source_key] = block
                blocks.append(block)
            elif (block['recipe']['identity'] != recipe['identity'] or block['setup'] != recipe['setup']
                  or block['recipe']['roles'] != recipe['roles']
                  or block['recipe']['definitions'] != recipe['definitions']):
                return {**proof, 'feasible': False, 'status': 'invalid_options',
                    'instruction': 'A physical source-block key merged incompatible movement, setup or role data. Preserve the input; no infeasibility was established.'}
            block['options'].extend(indices)
            block['recipeIndexes'].append(recipe_index)
            # Repeated count/rest alternatives share a single presence and first-use variable.
            block['optionsByRecipe'] = block.get('optionsByRecipe', {})
            block['optionsByRecipe'][recipe_index] = indices
            block['optionValues'] = block.get('optionValues', {})
            block['optionValues'].update(zip(indices, recipe['options']))
            if requirements['auditTargets'].get('maximumSessionSeconds') and 'setupSeconds' not in recipe['options'][0]['items'][0]:
                constraint(('missing_setup_only_first', day_index, recipe_index), -math.inf, 0,
                           {block['first']: -1, **dict.fromkeys(indices, 1)})
        missing_source_keys = set(source_blocks[day_index]) - set(blocks_by_source)
        if preserve_source_selection and missing_source_keys:
            missing = [{'workoutIndex': day_index,
                'sourcePositions': copy.deepcopy(source_blocks[day_index][key][1])}
                for key in sorted(missing_source_keys)]
            return {**proof, 'feasible': False, 'status': 'invalid_options',
                'errors': [{'code': 'submitted_block_without_executable_options', **entry} for entry in missing],
                'instruction': ('At least one submitted movement block has no executable prescription option. '
                    'The preserved-selection solve did not omit or replace it; correct that block or request an explicit structural alternative.')}
        for block_index, block in enumerate(blocks):
            choice = {index: 1 for index in block['options']}
            source_key = (block['recipe']['signature'], block['recipe']['sourceSignatureOccurrence'])
            source_block = source_key in source_blocks[day_index]
            if preserve_source_selection:
                selected_bounds = (1, 1) if source_block else (0, 0)
            else:
                selected_bounds = (0, 1)
            constraint(('physical_block_choice', day_index, block_index), *selected_bounds, choice)
            constraint(('first_selected', day_index, block_index), -math.inf, 0,
                       {block['first']: 1, **{index: -1 for index in block['options']}})
        day_blocks.append(blocks)
        constraint(('first_block', day_index), 1, 1, {b['first']: 1 for b in blocks})
        for reference in set().union(*(r['definitions'] for r in recipes)):
            inventory = max(sum(item['definition_id'] == reference for item in source['exercises']) for source in sessions)
            constraint(('movement_inventory', day_index, reference), 0, inventory,
                {i: 1 for b in blocks if reference in b['recipe']['definitions'] for i in b['options']})
        # The selected first block must match the deterministic stable topological
        # order used to build the candidate: approved order edges first, submitted
        # source order among currently-ready blocks. This keeps setup arithmetic
        # exact without spending another MILP pass to choose an order.
        selected_coefficients = [{option: 1 for option in block['options']} for block in blocks]
        predecessors = {index: set() for index in range(len(blocks))}
        for before_index, before in enumerate(blocks):
            for after_index, after in enumerate(blocks):
                if before_index == after_index:
                    continue
                if any(rule['kind'] == 'order'
                       and rule['before'] in before['recipe']['roles']
                       and rule['after'] in after['recipe']['roles']
                       for rule in requirements.get('executionRules', [])):
                    predecessors[after_index].add(before_index)
                    # A block with any selected approved predecessor is not ready.
                    constraint(('first_after_approved_predecessor', day_index, before_index, after_index),
                               -math.inf, 1,
                               {after['first']: 1, **selected_coefficients[before_index]})
        for first_index, first_block in enumerate(blocks):
            first_key = (first_block['sourceRank'], first_index)
            for earlier_index, earlier in enumerate(blocks):
                if (earlier['sourceRank'], earlier_index) >= first_key:
                    continue
                # If an earlier submitted block is selected and has no selected
                # approved predecessor, stable topological ordering makes it ready
                # before this block, so this block cannot receive first-use setup.
                coefficients = {first_block['first']: 1, **selected_coefficients[earlier_index]}
                for predecessor_index in predecessors[earlier_index]:
                    for option_index in blocks[predecessor_index]['options']:
                        coefficients[option_index] = coefficients.get(option_index, 0) - 1
                constraint(('first_respects_source_order', day_index, earlier_index, first_index),
                           -math.inf, 1, coefficients)

    base_report = None
    if existing:
        _, base_report = _audit_raw(existing, equipment, requirements, restriction_policy, allow_educated_load_guesses)
    targets = requirements['auditTargets']
    for scope, key in (('weekly', 'weeklyEffectiveSets'), ('session', 'perSessionEffectiveSets')):
        for muscle, bounds in targets.get(key, {}).items():
            for day_index in ([None] if scope == 'weekly' else range(len(sessions))):
                coefficients = {i: option['volume'][muscle]['effective'] * (
                    sessions[d]['timesCompletedInAWeek'] if day_index is None else 1)
                    for i, d, _, option in option_variables if day_index is None or d == day_index}
                intercept = base_report['weeklyVolume'][muscle]['effective'] if base_report and day_index is None else 0
                constraint((scope, day_index, muscle), bounds['minimum'], bounds['maximum'], coefficients, intercept)
    for rule in requirements.get('requiredCoverage', []):
        for day_index in ([None] if rule['scope'] == 'weekly' else range(len(sessions))):
            coefficients = {i: option['coverage'].get(rule['key'], 0) * (
                sessions[d]['timesCompletedInAWeek'] if day_index is None else 1)
                for i, d, _, option in option_variables if day_index is None or d == day_index}
            intercept = (base_report.get('weeklyCoverageSets', {}).get(rule['key'], 0)
                         if base_report and day_index is None else 0)
            constraint(('coverage', day_index, rule['key']), 1, math.inf, coefficients, intercept)
    if targets.get('maximumSessionSeconds') is not None:
        for day_index, blocks in enumerate(day_blocks):
            coefficients = {i: option['seconds'] for i, d, _, option in option_variables if d == day_index}
            coefficients.update({b['first']: -b['setup'] for b in blocks})
            constraint(('duration', day_index), -math.inf, targets['maximumSessionSeconds'], coefficients,
                       ASSUMPTIONS['generalWarmupSeconds'])
    preferences = preservation_costs
    balance_rules = [rule for rule in requirements.get('executionRules', []) if rule['kind'] == 'coverageBalance']
    balance_costs = {}
    for rule_index, rule in enumerate(balance_rules):
        for day_index in ([None] if rule['scope'] == 'weekly' else range(len(sessions))):
            coefficients = {i: (option['coverage'].get(rule['first'], 0) - option['coverage'].get(rule['second'], 0))
                * (sessions[d]['timesCompletedInAWeek'] if day_index is None else 1)
                for i, d, _, option in option_variables if day_index is None or d == day_index}
            intercept = ((base_report.get('weeklyCoverageSets', {}).get(rule['first'], 0)
                          - base_report.get('weeklyCoverageSets', {}).get(rule['second'], 0))
                         if base_report and day_index is None else 0)
            maximum = sum(abs(v) for v in coefficients.values()) + abs(intercept)
            deviation = variable(upper=maximum, domain_identity={'kind': 'coverage_balance_deviation',
                'ruleIndex': rule_index, 'scope': rule['scope'], 'workoutIndex': day_index,
                'first': rule['first'], 'second': rule['second']})
            balance_costs[deviation] = 1
            for sign in (-1, 1):
                constraint(('coverage_balance', rule_index, day_index, sign), -math.inf, 0,
                           {**{i: sign * value for i, value in coefficients.items()}, deviation: -1}, sign * intercept)
    features = constraints
    from .planning_tools import library_fingerprint
    library_hash = library_fingerprint(equipment)
    history_fingerprint = getattr(training_history, 'fingerprint', None)
    feasibility_domain_fingerprint = _joint_model_domain_fingerprint(
        variables, features, library_hash=library_hash, history_fingerprint=history_fingerprint,
        evidence=evidence, restriction_policy=restriction_policy,
        allow_educated_load_guesses=allow_educated_load_guesses,
        preserve_source_selection=preserve_source_selection)
    proof.update(feasibilityDomainFingerprint=feasibility_domain_fingerprint)
    known_infeasible = (None if rejected else _known_infeasible_repair_domain(
        messages, feasibility_domain_fingerprint, library_hash, history_fingerprint))
    if known_infeasible:
        previous = known_infeasible['receipt']
        return {**proof, 'feasible': False, 'status': 'infeasible',
            'knownPriorInfeasibility': True,
            'knownInfeasibleDomainMatch': known_infeasible['match'],
            'recipeCount': sum(len(recipe['options']) for recipe in recipes),
            'optionCount': len(option_variables),
            'consideredConstraints': copy.deepcopy(previous.get('consideredConstraints', [])),
            'objectiveProgress': copy.deepcopy(previous.get('objectiveProgress', [])),
            'preserveSourceSelection': bool(preserve_source_selection),
            'selectionPolicyVersion': SELECTION_POLICY_VERSION,
            'instruction': ('This exact exercise-prescription feasibility domain was already proven infeasible for this saved alternative. '
                'Changing non-fixed numWorkSets seeds, labels or coaching text does not change the domain. Make a structural or '
                'prescription-domain change that alters the executable options, or use the explicit validated trade-off route; '
                'do not submit another count-only repair or claim the approved requirements are globally impossible.')}
    objective_costs = {'source_balance': balance_costs, 'distribution': concentration_costs,
                       'progression': progression_penalties, 'preservation': preferences}
    approved_order = requirements.get('objectiveOrder')
    objective_order = list(approved_order) if approved_order is not None else ['preservation']
    goals = [(name, objective_costs[name]) for name in objective_order
             if name in objective_costs and any(objective_costs[name].values())]
    preservation_is_approved = approved_order is None or 'preservation' in objective_order
    if approved_order is not None and not preservation_is_approved:
        goals.append(('neutral_preservation', preferences))
    chosen, stages, status = None, [], 'unproven'
    # Exercise order is a construction constraint, not an optimization goal.
    # Stable topological ordering above applies approved order rules and otherwise
    # preserves the submitted sequence, so no separate order MILP is needed.
    order_policy = {'policy': 'submitted_order_with_approved_order_rules',
                    'mode': 'stable_topological', 'reviewRequired': False}
    if not goals:
        current = [{**variable, 'objectiveCost': 0} for variable in variables]
        stage_status, chosen = _milp_solve(current, features, timeout_seconds=None,
                                           preserve_current=False)
        if chosen is None:
            status = stage_status
        else:
            status = 'optimal' if stage_status == 'optimal' else 'feasible'
    for position, (name, costs) in enumerate(goals):
        current = [{**variable, 'objectiveCost': costs.get(index, 0)} for index, variable in enumerate(variables)]
        preservation_stage = name in ('preservation', 'neutral_preservation')
        zero_preservation_incumbent = (preservation_stage and chosen is not None
            and sum(cost * chosen[index] for index, cost in costs.items()) + source_block_edit_offset <= 1e-7)
        if zero_preservation_incumbent:
            stage_status, candidate = 'optimal_zero_lower_bound', chosen
        else:
            stage_status, candidate = _milp_solve(current, features, timeout_seconds=None,
                                                  preserve_current=preservation_stage)
        stages.append({'goal': name, 'status': stage_status})
        if candidate is None:
            if chosen is None:
                status = stage_status
            break
        chosen = candidate
        score = sum(cost * chosen[index] for index, cost in costs.items())
        stages[-1]['value'] = (score + source_block_edit_offset
                               if preservation_stage else score)
        # Lock the attained higher-priority score without huge numerical objective weights.
        features.append((('objective', name), -math.inf, score + 1e-7, 0, costs))
    if chosen is not None and goals:
        status = ('optimal' if len(stages) == len(goals)
                  and all(stage['status'] == 'optimal' for stage in stages) else 'feasible')
    receipt = {**proof, 'feasible': chosen is not None, 'status': status,
               'recipeCount': sum(len(recipe['options']) for recipe in recipes),
               'optionCount': len(option_variables), 'rejectedOptions': rejected[:20],
               'physicalBlockCount': sum(len(blocks) for blocks in day_blocks),
               'firstVariableCount': sum(len(blocks) for blocks in day_blocks),
               'sourceOrderConstraintCount': sum(label[0] == 'first_respects_source_order'
                   for label, _, _, _, _ in features),
               'objectiveProgress': stages,
               'objectiveOrderUsed': (list(approved_order) if approved_order is not None
                                      else ['preservation']),
               'neutralTieBreak': ('preservation' if approved_order is not None
                                   and not preservation_is_approved else None),
               'approvedObjectiveOrder': approved_order,
               'preserveSourceSelection': bool(preserve_source_selection),
               'objectiveInputFingerprint': joint_objective_input_fingerprint(sessions, requirements, equipment,
                   training_history, messages, restriction_policy=restriction_policy,
                   allow_educated_load_guesses=allow_educated_load_guesses,
                   preserve_source_selection=preserve_source_selection),
               'candidateOrderPolicy': order_policy,
               'objectivePolicy': 'approved' if approved_order is not None else 'preserve_candidate_only',
               'legacyBalanceHintApplied': False, 'selectionPolicyVersion': SELECTION_POLICY_VERSION}
    if chosen is None:
        # Diagnose approved constraints together; never spend unbounded time minimizing a conflict.
        receipt['consideredConstraints'] = [str(label) for label, _, _, _, _ in features
            if label[0] in ('weekly', 'session', 'coverage', 'duration', 'approved_order')]
        receipt['instruction'] = ('No combination in the supplied prescription menu satisfies the joint model.'
            if status == 'infeasible' else 'The bounded joint solve did not prove feasibility or infeasibility.') + (
            ' Preserve all approved targets. Add or correct substantive prescription/movement options; '
            'do not repeat count-only allocation or claim every possible workout is infeasible.')
        return receipt
    result = copy.deepcopy(sessions)
    occurrence_lineage = [[] for _ in sessions]
    lineage_claims = []
    candidate_order_changes = []
    for day_index, blocks in enumerate(day_blocks):
        items = []
        execution_order = _execution_order(blocks, chosen, requirements)
        submitted_blocks = source_blocks_by_identity[day_index]
        solved_blocks = [blocks[index]['recipe']['identity'] for index in execution_order]
        submitted_counts, solved_counts = Counter(submitted_blocks), Counter(solved_blocks)
        removed_blocks = submitted_counts - solved_counts
        added_blocks = solved_counts - submitted_counts
        submitted_occurrences, solved_occurrences = {}, {}
        submitted_tokens, solved_tokens = [], []
        for identity in submitted_blocks:
            occurrence = submitted_occurrences.get(identity, 0)
            submitted_occurrences[identity] = occurrence + 1
            submitted_tokens.append((identity, occurrence))
        for identity in solved_blocks:
            occurrence = solved_occurrences.get(identity, 0)
            solved_occurrences[identity] = occurrence + 1
            solved_tokens.append((identity, occurrence))
        common_tokens = set(submitted_tokens) & set(solved_tokens)
        retained_submitted = [token for token in submitted_tokens if token in common_tokens]
        retained_solved = [token for token in solved_tokens if token in common_tokens]
        reordered = retained_submitted != retained_solved
        if removed_blocks or added_blocks or reordered:
            reasons = []
            if reordered:
                reasons.append('reordered retained blocks')
            if removed_blocks or added_blocks:
                reasons.append('changed session block selection or placement')
            candidate_order_changes.append({
                'workoutIndex': day_index,
                'submittedOrder': [list(identity) for identity in submitted_blocks],
                'solvedOrder': [list(identity) for identity in solved_blocks],
                'removedBlocks': [list(identity) for identity, count in removed_blocks.items() for _ in range(count)],
                'addedBlocks': [list(identity) for identity, count in added_blocks.items() for _ in range(count)],
                'retainedOrderChanged': reordered,
                'reason': 'The solver ' + ' and '.join(reasons)
                          + '; independent session review should reassess the candidate arrangement.',
            })
        for block_index in execution_order:
            block = blocks[block_index]
            selected = [block['optionValues'][index] for index in block['options'] if chosen[index]]
            if selected:
                lineage_start = len(items)
                for item in copy.deepcopy(selected[0]['items']):
                    item['superset'] = f'JOINT_{day_index}_{block_index}' if item['superset'] is not None else None
                    items.append(item)
                    occurrence_lineage[day_index].append(None)
                source_key = (block['recipe']['signature'], block['recipe']['sourceSignatureOccurrence'])
                local_positions = source_recipe_positions[day_index].get(source_key)
                lineage_claims.append((source_key, day_index, lineage_start,
                    copy.deepcopy(local_positions), copy.deepcopy(block['recipe']['sourcePositions'])))
        result[day_index]['exercises'] = items
    assigned_source_positions = set()
    pending_claims = []
    for claim in lineage_claims:
        _, workout, start, local_positions, origin_positions = claim
        if local_positions is None:
            pending_claims.append(claim)
            continue
        positions = local_positions
        if start + len(positions) > len(result[workout]['exercises']):
            return {**receipt, 'feasible': False, 'status': 'unverified',
                'errors': [{'code': 'invalid_occurrence_lineage', 'workoutIndex': workout}],
                'instruction': 'The solver recipe lost its source occurrence mapping; preserve the candidate and report the lineage validation failure.'}
        mapped_positions = []
        for position in positions:
            token = tuple(position)
            if token in assigned_source_positions:
                return {**receipt, 'feasible': False, 'status': 'unverified',
                    'errors': [{'code': 'duplicate_source_lineage', 'sourceOccurrence': list(token)}],
                    'instruction': 'A submitted occurrence was assigned to multiple solved movements; preserve the candidate and report the lineage validation failure.'}
            mapped_positions.append(list(position))
            assigned_source_positions.add(token)
        occurrence_lineage[workout][start:start + len(positions)] = mapped_positions
    for _, workout, start, local_positions, origin_positions in pending_claims:
        if start + len(origin_positions) > len(result[workout]['exercises']):
            return {**receipt, 'feasible': False, 'status': 'unverified',
                'errors': [{'code': 'invalid_occurrence_lineage', 'workoutIndex': workout}],
                'instruction': 'The solver recipe lost its source occurrence mapping; preserve the candidate and report the lineage validation failure.'}
        mapped_positions = []
        for position in origin_positions:
            token = tuple(position)
            mapped_positions.append(list(position) if token not in assigned_source_positions else None)
            assigned_source_positions.add(token)
        occurrence_lineage[workout][start:start + len(origin_positions)] = mapped_positions
    draft = {'name': 'Joint week', 'workouts': copy.deepcopy((existing or {}).get('workouts', [])) + result}
    plan, report = _audit_raw(draft, equipment, requirements, restriction_policy, allow_educated_load_guesses)
    audit_execution_rules(draft, requirements, report, plan)
    audit_execution_details(draft, requirements, report)
    apply_native_load_calibration_policy(plan, messages or [], equipment,
        getattr(training_history, 'fingerprint', None),
        allow_educated_load_guesses=allow_educated_load_guesses)
    if validate_loads:
        report['errors'].extend(validate_loads(plan))
    if report['errors']:
        return {**receipt, 'feasible': False, 'status': 'unverified', 'errors': report['errors'],
                'instruction': 'The assembled week failed the production audit. Preserve recipes and report this joint-planning validation failure; do not export or enter count-only repair.'}
    return {**receipt, 'objectiveInputFingerprint': joint_objective_input_fingerprint(result, requirements, equipment,
                training_history, messages, restriction_policy=restriction_policy,
                allow_educated_load_guesses=allow_educated_load_guesses,
                preserve_source_selection=preserve_source_selection),
            'candidateOrderPolicy': {**order_policy,
                'reviewRequired': bool(candidate_order_changes)},
            'sessions': result, 'occurrenceLineage': occurrence_lineage,
            'audit': report, 'elapsedSeconds': time.monotonic() - started,
            'candidateOrderChanges': candidate_order_changes,
            'candidateOrderReviewRequired': bool(candidate_order_changes),
            'solvedPrescriptionHash': prescription_fingerprint(draft['workouts']),
            'progressionMargins': [{'definition_id': item['definition_id'],
                **progression_margin(item, capabilities[item['definition_id']])} for day in result for item in day['exercises']],
            'coverageBalance': [{'first': rule['first'], 'second': rule['second'], 'scope': rule['scope'],
                'authority': 'Source-approved qualitative goal; no hard numerical tolerance was invented.'}
                for rule in balance_rules]}
