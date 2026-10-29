"""Targeted, version-aware historical evidence for workout planning."""
import copy
import hashlib
import json
import math
import threading
from collections import defaultdict
from datetime import date

from jsonschema import validate
from workout_history_mcp.loader import WorkoutHistoryStore, load_backup, _is_active_set, _sort_number
from .domain_ops import get_selectable_weights_for_exercise
from .planning_tools import library_fingerprint
from .cancellation import check_cancelled

RELATED_LOAD_TRANSFER_CAUTION = 'Do not convert or transfer loads automatically. Execution, laterality, reps, effort and equipment affect comparability.'
LOAD_CEILING_CONCERNS = {'recorded_load_exceeds_current_capacity', 'related_history_ceiling_requires_reassessment'}
PRESCRIPTION_EVIDENCE_INSTRUCTION = (
    'Use history to choose provisional prescriptions. Python renders working-set effort criteria. The app owns native load calibration. '
    'Do not duplicate structured work-set counts, rep targets, default RIR, rests, exercise order or superset assignments there; the renderer owns those facts. '
    'Do not restate or embellish historical performances; structured evidence already preserves them. '
    'A prescribed RIR is a target, never an observed historical effort when effort data is absent. ')
EVIDENCE_FORMAT = {
    'candidateContext': 'Loaded current configuration, not a fresh measurement. Effective bodyweight is derived from configured body mass and the selected library percentage.',
    'sessions': 'Recorded sessions comparable to the selected movement and recorded setup; records are observations, not strength maxima.',
    'otherSetupSessions': 'Same stored movement identity with changed or uncertain setup/definition. Read comparisonLimitations; do not transfer loads automatically.',
    'executionSequence': 'Recorded execution order across the session; preferred over the per-exercise set order when available.',
    'loadKg': 'External load only. For BODY_WEIGHT this is added load, not total resistance. Dumbbell-pair loads are combined across both implements.',
    'recordedRelativeBodyWeightKg': 'Recorded effective bodyweight contribution, not necessarily the athlete\'s full body mass.',
    'recordedTotalResistanceKg': 'Recorded effective bodyweight plus added load; never compare this total to an added-load equipment ceiling.',
    'bodyWeightPercentage': 'Application resistance-accounting factor, not a measured cross-variant strength scale. Differing percentages do not establish that one variant is heavier, easier, or impossible by comparing derived totals alone.',
    'comparisonLimitations': 'Restrictions on permissible inference, not evidence of incapacity. Missing comparable history or changed accounting cannot alone prove that a movement is infeasible. When supported, the app handles an unknown starting load through its built-in load-calibration mode; do not prescribe separate trial sets or rests.',
    'loadHeadroom': 'latestSessionHeaviestLoadKg describes only the latest comparable session. highestObservedComparableLoad summarizes positive-rep work sets across all comparable sessions, not just the returned page; it is an observation with a date, not a strength maximum or current capacity.',
    'equipmentContext': 'Set-time snapshots take precedence. workout_occurrence_fallback is inferred historical context, not a recorded snapshot.',
    'requiredAccessoryNames': 'Inferred from the saved occurrence or definition, not set-time accessory snapshots. Migrated identities alone do not prove setup equivalence.',
    'timing': 'Duration is seconds. COUNTDOWN=startTimer-endTimer; COUNTUP=endTimer. Running duration/distance come from the recorded RunningResult; GPS routes are omitted.',
    'configuredDurationSeconds': 'Recorded timer configuration, not measured effort. A count-up timer without auto-stop has no enforced duration target.',
}

GET_TRAINING_EVIDENCE_TOOL = {'type': 'function', 'function': {
    'name': 'get_training_evidence',
    'description': 'Retrieve exact working-set history, semantically related movement history, and equipment progression headroom for candidate LIBRARY_n exercises. Batch candidates. Defaults to the latest comparable session; request more or page older sessions only for a specific evidence gap. Related loads are separate evidence, never strength conversions.',
    'parameters': {'type': 'object', 'properties': {
        'definition_ids': {'type': 'array', 'items': {'type': 'string', 'pattern': '^LIBRARY_[0-9]+$'}, 'minItems': 1, 'maxItems': 100},
        'session_offset': {'type': 'integer', 'minimum': 0},
        'session_limit': {'type': 'integer', 'minimum': 1, 'maximum': 10},
    }, 'required': ['definition_ids'], 'additionalProperties': False},
}}

HISTORY_PLANNING_INSTRUCTION = (
    'Training history is available through get_training_evidence. Search results include compact trainingEvidence summaries. '
    'Retrieve comparable records for the selected exercises before setting starting loads or submitting a draft; reuse current retrieved evidence. '
    'Use actual recorded reps and loads, dates, setup and available increments. A recorded load is NOT a measured strength maximum. '
    'Missing effort/RIR means proximity to failure is unknown. autoRegulationRIR is recorded working-set effort; '
    'calibrationRIR is calibration evidence, not interchangeable with working-set effort. '
    'History age, rest, unilateral execution and workout order affect comparability. '
    'executionContext distinguishes straight sets from supersets. For supersets, prescribedRestSeconds is empty: member rest is a transition, '
    'and recovery between that movement\'s own sets also includes other members\' work and rests. The schedule is prescribed, not measured recovery. '
    'equipmentContextRef and executionContextRef resolve through historyExecutionContexts; shared context is not omitted evidence. '
    'When the equipment ceiling is already used, consider progression within the agreed rep range or an appropriate available variant; '
    'do not silently add sets, change volume/time targets, or invent a strength conversion between related movements. '
    'Use workSetTemplate for a uniform target and targetSetPrescriptions for distinct per-set reps or loads. '
    'When comparable usable load history exists, use it to justify a starting load; when it does not, omit the load from every target and let Python enable the app built-in load-calibration mode for WEIGHT and equipped BODY_WEIGHT exercises. Never invent a starting load or mix fixed and omitted loads in one exercise. Do not add separate calibration trials, trial counts, or recovery periods; the app owns calibration execution. Fixed BODY_WEIGHT and timed exercises do not support this load-calibration mode. '
    'Compare relatedMovementHistory with the candidate equipment ceiling before choosing an unrecorded variant. '
    'Related movement loads are not directly interchangeable: inspect equipment, execution and load conventions. '
    'relatedHistoryStatus=checked_local_unconfirmed means weak local matches could not be adjudicated; no related records were accepted. Do not treat that as strength or suitability evidence. '
    'HISTORY_n references identify evidence-only historical movements; only LIBRARY_n references are selectable exercises. '
    'If related performance suggests a candidate may be too lightly loaded at the requested reps/RIR, justify its use or choose a supported alternative; related performance does not establish candidate-specific capacity. '
    'Resolve loadSuitabilityConcerns before submitting a draft. Prefer an available loadable variant. If suitability remains uncertain, '
    'do not invent a separate trial procedure or remove prescribed work merely to represent load calibration; the app mode handles supported starting-load uncertainty. '
    'Extra sets or slower tempo do not by themselves resolve an equipment-capacity concern. '
    'Keep capability conclusions scoped to the supplied movement and setup. Consider supported alternatives for a demonstrated suitability gap before requesting changed targets. '
    'An empty loadSuitabilityConcerns list only means these deterministic checks found no flag; it does not verify current RIR, '
    'prescribed reps, or performance with shorter rests. Treat history-based loads as provisional starting points. '
    'Dumbbell-pair loads are app totals across both implements; bodyweight additional load is separate from recorded relative bodyweight. '
    'Read candidateContext and each performance equipmentContext/bodyWeightPercentageSource. Snapshots describe the recorded setup; fallback context is less certain. '
    'otherSetupSessions are historical observations with comparisonLimitations, not equivalent sessions for choosing exact loads. '
    'Loaded timed work retains external load separately from duration; running records retain duration, distance and recorded pace/heart rate without routes. '
    'Use only established movement identities; unresolved identity requires clarification before prescription. '
    'An equipment limit is not evidence that an exercise is ineffective or that the athlete cannot progress.'
)


def compact_training_evidence(items):
    """Store each movement's records once; keep comparison details on related links."""
    catalog = {}
    comparison_fields = ('differences', 'loadTransfer', 'matchType', 'relevanceScore')

    def collect(item, related=False):
        reference = item.get('reference')
        if not reference:
            return
        links = []
        for other in item.get('relatedMovementHistory', []):
            collect(other, related=True)
            links.append({key: copy.deepcopy(other[key]) for key in ('reference',) + comparison_fields if key in other})
        entry = {key: copy.deepcopy(value) for key, value in item.items()
                 if key != 'relatedMovementHistory' and not (related and key in comparison_fields)}
        entry.pop('definitionId', None)  # LIBRARY_n/HISTORY_n is the model-facing identity.
        if 'relatedMovementHistory' in item:
            entry['relatedMovementHistory'] = links
        for session in entry.get('sessions', []) + entry.get('otherSetupSessions', []):
            for field in ('sessionId', 'workoutId', 'time'):
                session.pop(field, None)
            for performance in session.get('performances', []):
                for field in ('exerciseId', 'equipmentId', 'requiredAccessoryEquipmentIds', 'startTime'):
                    performance.pop(field, None)
                performance.get('record', {}).pop('setHistoryId', None)
        if (not related or reference not in catalog
                or (catalog[reference].get('historyDetailsOmitted') and not entry.get('historyDetailsOmitted'))):
            catalog[reference] = entry

    for item in items:
        collect(item)
    return catalog


def pool_execution_contexts(catalog, existing_contexts=None):
    """Factor repeated bulky execution contexts without dropping any performance facts."""
    catalog = copy.deepcopy(catalog)
    groups, contexts = {}, {}
    for entry in catalog.values():
        for session in entry.get('sessions', []) + entry.get('otherSetupSessions', []):
            for performance in session.get('performances', []):
                for field in ('executionContext', 'equipmentContext'):
                    reference_field = field + 'Ref'
                    if reference_field in performance:
                        reference = performance[reference_field]
                        if reference not in (existing_contexts or {}):
                            raise ValueError(f'Historical context reference {reference} has no supplied context.')
                        performance[field] = copy.deepcopy(existing_contexts[reference])
                        performance.pop(reference_field)
                    context = performance.get(field)
                    if isinstance(context, dict):
                        key = (field, json.dumps(context, sort_keys=True, separators=(',', ':')))
                        groups.setdefault(key, []).append(performance)
    for (field, _), performances in groups.items():
        reference = f'CONTEXT_{len(contexts)}'
        replacement = {field + 'Ref': reference}
        new_size = len(json.dumps({reference: performances[0][field]})) + len(performances) * len(json.dumps(replacement))
        old_size = len(performances) * len(json.dumps({field: performances[0][field]}))
        if new_size >= old_size:
            continue
        contexts[reference] = performances[0][field]
        for performance in performances:
            performance.pop(field)
            performance.update(replacement)
    return catalog, contexts


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def has_usable_comparable_load_history(evidence):
    """True only when exact comparable records include a usable loaded work set."""
    if not isinstance(evidence, dict) or evidence.get('status') != 'comparable_records':
        return False
    return any(
        isinstance(performance, dict)
        and isinstance(performance.get('record'), dict)
        and performance['record'].get('setType') in ('WeightSetData', 'BodyWeightSetData')
        and number(performance['record'].get('actualReps'))
        and performance['record']['actualReps'] > 0
        and number(performance['record'].get('loadKg'))
        and performance['record']['loadKg'] >= 0
        for session in evidence.get('sessions', []) if isinstance(session, dict)
        for performance in session.get('performances', [])
    )


def _recorded_added_load_setup_concern(evidence):
    """Report a recorded setup difference without judging a proposed prescription."""
    context = (evidence or {}).get('candidateContext', {})
    if (context.get('exerciseType') != 'BODY_WEIGHT' or context.get('equipmentId') is not None
            or not evidence):
        return None
    sessions = evidence.get('sessions', []) + evidence.get('otherSetupSessions', [])
    if not sessions:
        return None
    latest = max(sessions, key=lambda session: (session.get('date') or '', session.get('time') or ''))
    records = []
    for performance in latest.get('performances', []):
        record = performance.get('record', {})
        # A different movement, accessory setup, or inferred implement cannot
        # establish this concern. Accounting differences never convert loads.
        limitations = set(performance.get('comparisonLimitations', []))
        if (limitations - {'recorded_equipment_differs_or_is_unresolved', 'bodyweight_percentage_changed'}
                or performance.get('equipmentContext', {}).get('source') != 'set_snapshot'
                or not performance.get('equipmentId')
                or record.get('setType') != 'BodyWeightSetData'
                or record.get('loadMeaning') != 'additional_bodyweight_load'
                or not number(record.get('loadKg')) or record['loadKg'] <= 0
                or not number(record.get('actualReps')) or record['actualReps'] <= 0):
            continue
        records.append({'sessionDate': latest.get('date'), 'sessionEndReason': latest.get('endReason'),
            'equipmentId': performance['equipmentId'], 'loadKg': record['loadKg'],
            'actualReps': record['actualReps'],
            'equipmentSnapshotSource': performance['equipmentContext']['source'],
            'equipmentContext': copy.deepcopy(performance['equipmentContext'])})
    if records:
        return {'code': 'recorded_loaded_setup_requires_reassessment',
            'date': latest.get('date'), 'records': records,
            'message': 'The latest same-movement session includes recorded added-load work in the shown equipment setup. '
                'This is a historical setup fact, not evidence that fixed-bodyweight work is unsuitable at any proposed '
                'reps or effort. Prefer a currently available configuration matching the recorded setup, or ask the '
                'user to resolve the choice. Do not transfer the historical load as a prescription.'}
    return None


def apply_native_load_calibration_policy(plan, messages, equipment, history_fingerprint=None, *,
                                         allow_educated_load_guesses=True):
    """Bind native app load calibration to each plan before its preview is reviewed."""
    from .recipe_contracts import recorded_evidence

    evidence = recorded_evidence(messages, library_fingerprint(equipment or {}), history_fingerprint)
    for exercise in plan.get('exercises', []):
        exercise_type = exercise.get('exerciseType')
        supported = exercise_type == 'WEIGHT' or (
            exercise_type == 'BODY_WEIGHT' and exercise.get('equipmentId') is not None
        )
        if not supported:
            exercise['requiresLoadCalibration'] = False
            continue
        prior = evidence.get(exercise.get('libraryDefinitionId'))
        rir = plan.get('workingSetRIR', {}).get('maximum')
        recorded_rep_conflict = False
        if prior and exercise.get('maxReps') and number(rir):
            over_ceiling = [performance['record'] for session in prior.get('sessions', [])[:1]
                for performance in session.get('performances', [])
                if isinstance(performance, dict) and isinstance(performance.get('record'), dict)
                and performance['record'].get('actualReps', 0) > exercise['maxReps'] + rir]
            loads = [prescription.get('weight', prescription.get('additionalWeight'))
                for prescription in exercise.get('targetSetPrescriptions', [])]
            recorded_rep_conflict = bool(over_ceiling and (not loads or any(
                number(load) and load <= record.get('loadKg', float('inf'))
                for load in loads for record in over_ceiling)))
        exercise['requiresLoadCalibration'] = (
            exercise.get('requiresLoadCalibration') is True
            or not allow_educated_load_guesses
            or bool((prior or {}).get('loadSuitabilityConcerns'))
            or recorded_rep_conflict
            or not has_usable_comparable_load_history(prior)
        )
    return plan


class TrainingHistory:
    def __init__(self, backup):
        store = WorkoutHistoryStore(backup)
        if not isinstance(backup.get('WorkoutStore'), dict) or not isinstance(backup.get('SetHistories'), list):
            raise ValueError('Expected an AppBackup with WorkoutStore and SetHistories')
        # Invalidate saved tool results when evidence interpretation changes.
        self.fingerprint = hashlib.sha256(json.dumps({'evidenceVersion': 8, 'backup': backup}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.definitions = {d['id']: d for d in store.workout_store.get('exerciseDefinitions', [])}
        occurrences, execution_contexts = {}, {}
        for workout in store.workouts:
            for component in workout.get('workoutComponents', []):
                items = component.get('exercises', []) if component.get('type') == 'Superset' else [component]
                for member_index, exercise in enumerate(items):
                    if exercise.get('type') == 'Exercise':
                        key = (workout['id'], exercise['id'])
                        if key in occurrences and occurrences[key] != exercise:
                            raise ValueError('Conflicting exercise occurrences in one workout version')
                        occurrences[key] = exercise
                        if component.get('type') == 'Superset':
                            members = component.get('exercises', [])
                            execution_contexts[key] = {'type': 'superset', 'memberIndex': member_index,
                                'members': [{'name': member.get('name'), 'enabled': member.get('enabled', True),
                                    'restAfterSeconds': component.get('restSecondsByExercise', {}).get(member['id']),
                                    'exerciseRestSetsSeconds': self._rest_seconds(member)} for member in members],
                                **{field: component[field] for field in ('roundDurationSeconds', 'timeCapSeconds', 'amrap') if field in component}}
                        else:
                            execution_contexts[key] = {'type': 'straightSets'}
        sessions = {s['id']: s for s in store.completed_sessions()}
        historical_gear = {item['id']: item for item in store.workout_store.get('equipments', [])}
        historical_accessories = {item['id']: item for item in store.workout_store.get('accessoryEquipments', [])}
        grouped = defaultdict(dict)
        self.unresolved_records = 0
        self.unreadable_records = defaultdict(int)
        running_seen = set()
        for record in store.set_histories:
            session = sessions.get(record.get('workoutHistoryId'))
            data = record.get('setData', {})
            running = data.get('type') == 'RunningSetData'
            if not session or not (_is_active_set(record) or running) or record.get('skipped'):
                continue
            if data.get('hasBeenExecuted') is False:
                continue
            exercise = occurrences.get((session.get('workoutId'), record.get('exerciseId')))
            if exercise is None or exercise.get('exerciseDefinitionId') not in self.definitions:
                self.unresolved_records += 1
                continue
            item = self._running_record(record, session) if running else self._set_record(record)
            if item is None:
                self.unreadable_records[data.get('type', 'unknown')] += 1
                continue
            if running:
                key = (session['id'], exercise['id'])
                if key in running_seen:
                    continue  # RunningResult describes the occurrence, not each repeated set-history row.
                running_seen.add(key)
            definition_id = exercise['exerciseDefinitionId']
            execution_context = execution_contexts[(session['workoutId'], exercise['id'])]
            group = grouped[definition_id].setdefault(session['id'], {
                'sessionId': session['id'], 'date': session.get('date'), 'time': session.get('time'),
                'workoutId': session['workoutId'], 'endReason': session.get('endReason'), 'performances': [],
            })
            # Retain occurrence context: one movement can appear twice in a session.
            has_snapshot = any(record.get(field) is not None for field in
                               ('equipmentIdSnapshot', 'equipmentNameSnapshot', 'equipmentTypeSnapshot'))
            equipment_id = record.get('equipmentIdSnapshot') if has_snapshot else exercise.get('equipmentId')
            gear = historical_gear.get(equipment_id, {})
            equipment_type = record.get('equipmentTypeSnapshot') if has_snapshot else gear.get('type')
            percentage = data.get('bodyWeightPercentageSnapshot')
            percentage_source = 'set_snapshot' if number(percentage) else 'workout_occurrence_fallback'
            if not number(percentage):
                percentage = exercise.get('bodyWeightPercentage')
                if not number(percentage):
                    percentage = self.definitions[definition_id].get('bodyWeightPercentage')
                    percentage_source = 'definition_fallback' if number(percentage) else 'unknown'
            accessory_ids = exercise.get('requiredAccessoryEquipmentIds')
            accessory_source = 'workout_occurrence_fallback' if isinstance(accessory_ids, list) else 'definition_fallback'
            if not isinstance(accessory_ids, list):
                accessory_ids = self.definitions[definition_id].get('requiredAccessoryEquipmentIds') or []
            group['performances'].append({
                'exerciseId': exercise['id'], 'equipmentId': equipment_id,
                'equipmentContext': {'name': record.get('equipmentNameSnapshot') if has_snapshot else gear.get('name'),
                    'type': equipment_type, 'source': 'set_snapshot' if has_snapshot else 'workout_occurrence_fallback',
                    'loadConvention': 'pair_total' if equipment_type == 'DUMBBELLS' else 'app_total' if equipment_type else 'unknown'},
                'requiredAccessoryNames': [historical_accessories.get(key, {}).get('name') for key in accessory_ids],
                'requiredAccessoryEquipmentIds': accessory_ids,
                'accessoryContextSource': accessory_source,
                'bodyWeightPercentage': percentage, 'bodyWeightPercentageSource': percentage_source,
                'exerciseType': exercise.get('exerciseType'), 'order': record.get('order'),
                'executionSequence': record.get('executionSequence'),
                'startTime': record.get('startTime'),
                'prescribedRestSeconds': self._rest_seconds(exercise) if execution_context['type'] == 'straightSets' else [],
                'executionContext': execution_context,
                'intraSetRestInSeconds': exercise.get('intraSetRestInSeconds'), 'record': item,
            })
        self.sessions = {key: sorted(values.values(), key=lambda s: (s.get('date') or '', s.get('time') or ''), reverse=True)
                         for key, values in grouped.items()}
        for values in self.sessions.values():
            for session in values:
                session['performances'].sort(key=lambda item: (
                    item.get('executionSequence') is None, _sort_number(item.get('executionSequence')),
                    _sort_number(item.get('order')), item.get('startTime') or ''))
        self._loads = {}
        self._cache = {}
        self._related_cache = {}
        self._related_lock = threading.RLock()
        self._related_matching_lock = threading.Lock()
        self._related_status_cache = {}
        self._history_equipment = store.workout_store

    @classmethod
    def from_file(cls, path):
        return cls(load_backup(path))

    @staticmethod
    def _rest_seconds(exercise):
        return sorted({s['timeInSeconds'] for s in exercise.get('sets', []) if s.get('type') == 'RestSet' and number(s.get('timeInSeconds'))})

    @staticmethod
    def _set_record(record):
        data = record['setData']
        kind = data.get('type')
        result = {'setHistoryId': record['id'], 'setType': kind}
        if kind in ('WeightSetData', 'BodyWeightSetData'):
            reps = data.get('actualReps')
            load_key = 'actualWeight' if kind == 'WeightSetData' else 'additionalWeight'
            load = data.get(load_key)
            if not number(reps) or reps <= 0 or not number(load) or load < 0:
                return None
            result.update({'actualReps': reps, 'loadKg': load, 'loadMeaning': 'app_total_external_load' if kind == 'WeightSetData' else 'additional_bodyweight_load'})
            if number(data.get('relativeBodyWeightInKg')):
                result['recordedRelativeBodyWeightKg'] = data['relativeBodyWeightInKg']
                if kind == 'BodyWeightSetData':
                    result['recordedTotalResistanceKg'] = data['relativeBodyWeightInKg'] + load
            if kind == 'BodyWeightSetData' and number(data.get('bodyWeightPercentageSnapshot')):
                result['bodyWeightPercentageSnapshot'] = data['bodyWeightPercentageSnapshot']
        elif kind in ('TimedDurationSetData', 'EnduranceSetData'):
            start, end = data.get('startTimer'), data.get('endTimer')
            if not number(end) or (kind == 'TimedDurationSetData' and not number(start)):
                return None
            elapsed = end if kind == 'EnduranceSetData' else start - end
            if elapsed <= 0:
                return None
            result['actualDurationSeconds'] = elapsed / 1000
            if number(start) and start >= 0:
                result['configuredDurationSeconds'] = start / 1000
            if isinstance(data.get('autoStop'), bool):
                result['timerAutoStop'] = data['autoStop']
            if number(data.get('actualWeight')) and data['actualWeight'] >= 0:
                result.update(loadKg=data['actualWeight'], loadMeaning='app_total_external_load')
        else:
            return None
        for field in ('autoRegulationRIR', 'calibrationRIR', 'rir', 'rpe'):
            if number(data.get(field)):
                result[field] = data[field]
        return result

    @staticmethod
    def _running_record(record, session):
        results = [item for item in session.get('runningResults', [])
                   if item.get('exerciseId') == record.get('exerciseId')]
        if len(results) != 1 or not number(results[0].get('elapsedTimeMillis')) or results[0]['elapsedTimeMillis'] <= 0:
            return None
        source = results[0]
        result = {'setHistoryId': record['id'], 'setType': 'RunningSetData',
                  'actualDurationSeconds': source['elapsedTimeMillis'] / 1000,
                  'measurementSource': 'workout_running_result'}
        for field in ('distanceMeters', 'averagePaceSecondsPerKilometer', 'averageHeartRateBpm', 'minHeartRateBpm', 'maxHeartRateBpm'):
            if number(source.get(field)) and source[field] >= 0:
                result[field] = source[field]
        return result

    def context(self):
        dates = [s['date'] for values in self.sessions.values() for s in values if s.get('date')]
        return {'historyFingerprint': self.fingerprint, 'definitionsWithEvidence': len(self.sessions),
                'latestRecordedDate': max(dates) if dates else None, 'unresolvedRecordsExcluded': self.unresolved_records,
                'unreadableRecordsBySetType': dict(self.unreadable_records), 'evidenceFormat': EVIDENCE_FORMAT}

    def evidence(self, arguments, equipment, client=None):
        result = self._exact_evidence(arguments, equipment)
        if client is not None:
            # Serialize related matching without holding the cache lock needed by new turns.
            while not self._related_matching_lock.acquire(timeout=0.1):
                check_cancelled()
            try:
                check_cancelled()
                self._add_related_history(result, equipment, client)
            finally:
                self._related_matching_lock.release()
        self._add_reviewed_family_history(result, equipment)
        if arguments.get('session_offset', 0):
            latest = self._exact_evidence({'definition_ids': [item['reference'] for item in result['exercises']]}, equipment)
            latest_by_definition = {item['definitionId']: item for item in latest['exercises']}
        else:
            latest_by_definition = {item['definitionId']: item for item in result['exercises']}
        for item in result['exercises']:
            current = dict(latest_by_definition[item['definitionId']])
            current['relatedMovementHistory'] = item.get('relatedMovementHistory', [])
            current['relatedHistoryStatus'] = item.get('relatedHistoryStatus')
            item['loadSuitabilityConcerns'] = self._load_concerns(current)
        return result

    def _add_reviewed_family_history(self, result, equipment):
        """Reviewed family identity supplies related evidence, never a strength conversion."""
        from .recipe_contracts import reviewed_exercise_family_evidence
        families = reviewed_exercise_family_evidence(equipment)
        definitions = sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id'])
        historical = {f'LIBRARY_{index}': families['familyByReference'].get(f'LIBRARY_{index}')
            for index, definition in enumerate(definitions) if self.sessions.get(definition['id'])}
        for item in result.get('exercises', []):
            family = families['familyByReference'].get(item['reference'])
            if not family or item.get('totalSessions') or item.get('candidateContext', {}).get('exerciseType') != 'WEIGHT':
                continue
            refs = [ref for ref, value in historical.items() if value == family and ref != item['reference']]
            related = item.setdefault('relatedMovementHistory', [])
            for start in range(0, len(refs), 100):
                for evidence in self._exact_evidence({'definition_ids': refs[start:start + 100], 'session_limit': 1}, equipment)['exercises']:
                    if evidence['totalSessions'] and evidence['candidateContext']['exerciseType'] == 'WEIGHT':
                        related[:] = [entry for entry in related if entry.get('reference') != evidence['reference']]
                        related.append({**evidence, 'matchType': 'reviewed_family_not_equivalent',
                            'familyEvidence': {'candidate': families['sourcesByReference'][item['reference']],
                                'historical': families['sourcesByReference'][evidence['reference']]},
                            'loadTransfer': RELATED_LOAD_TRANSFER_CAUTION})

    def refresh_evidence_metadata(self, payload, equipment):
        """Add current derived summaries to retained evidence without changing its session pages."""
        if (payload.get('historyFingerprint') != self.fingerprint
                or payload.get('libraryFingerprint') != library_fingerprint(equipment)):
            return payload
        result = copy.deepcopy(payload)
        def entries(items):
            for item in items:
                yield item
                yield from entries(item.get('relatedMovementHistory', []))
        retained = [item for item in entries(result.get('exercises', []))
                    if isinstance(item.get('reference'), str) and item['reference'].startswith('LIBRARY_')]
        references = list(dict.fromkeys(item['reference'] for item in retained))
        current_by_reference = {}
        for start in range(0,len(references),12):
            fresh = self._exact_evidence({'definition_ids':references[start:start+12]},equipment)
            current_by_reference.update((item['reference'], item) for item in fresh['exercises'])
        for item in retained:
            current = current_by_reference[item['reference']]
            context = item.get('candidateContext')
            item['candidateContext'] = {**(context if isinstance(context, dict) else {}),
                                        **current['candidateContext']}
            concerns = item.get('loadSuitabilityConcerns')
            concerns = concerns if isinstance(concerns, list) else []
            concerns = [concern for concern in concerns if not isinstance(concern, dict)
                        or concern.get('code') != 'recorded_loaded_setup_requires_reassessment']
            setup_concern = _recorded_added_load_setup_concern(current)
            item['loadSuitabilityConcerns'] = concerns + ([setup_concern] if setup_concern else [])
            headroom = item.setdefault('loadHeadroom', {})
            if 'highestObservedComparableLoad' not in headroom:
                headroom['highestObservedComparableLoad'] = current['loadHeadroom']['highestObservedComparableLoad']
        self._add_reviewed_family_history(result, equipment)
        for item in result.get('exercises', []):
            concerns = [entry for entry in item.get('loadSuitabilityConcerns', [])
                if entry.get('code') != 'related_history_ceiling_requires_reassessment']
            item['loadSuitabilityConcerns'] = concerns + [entry for entry in self._load_concerns(item)
                if entry['code'] == 'related_history_ceiling_requires_reassessment']
        result['evidenceFormat'] = EVIDENCE_FORMAT
        return result

    def begin_turn(self):
        """Allow failed related matching to retry; successful evidence stays cached."""
        with self._related_lock:
            for key, status in list(self._related_status_cache.items()):
                if status == 'checked_local_unconfirmed':
                    self._related_cache.pop(key, None)
                    self._related_status_cache.pop(key, None)

    @staticmethod
    def _load_concerns(item):
        concerns = []
        headroom = item['loadHeadroom']
        maximum, observed = headroom['maximumSelectableLoadKg'], headroom['latestSessionHeaviestLoadKg']
        if number(maximum) and number(observed) and observed > maximum + .001:
            concerns.append({'code': 'recorded_load_exceeds_current_capacity',
                'recordedLoadKg': observed, 'maximumSelectableLoadKg': maximum,
                'message': 'Exact exercise history used more resistance than is currently selectable. This flags uncertainty, not current strength.'})
        if not item['totalSessions'] and any(e.get('sessions') or e.get('otherSetupSessions') for e in item.get('relatedMovementHistory', [])):
            concerns.append({'code': 'related_history_only',
                'message': 'Only related movement performance is available. Verify the candidate resistance/effort; do not transfer loads or infer suitability from another implement ceiling.'})
        related_ceiling = [e for e in item.get('relatedMovementHistory', [])
            if e.get('matchType') == 'reviewed_family_not_equivalent'
            and number(e.get('loadHeadroom', {}).get('latestSessionHeaviestLoadKg'))
            and number(maximum) and e['loadHeadroom']['latestSessionHeaviestLoadKg'] > maximum + .001]
        if not item['totalSessions'] and related_ceiling:
            concerns.append({'code': 'related_history_ceiling_requires_reassessment',
                'maximumSelectableLoadKg': maximum,
                'relatedEvidence': [{key: e[key] for key in ('reference', 'definitionId', 'loadHeadroom', 'familyEvidence')}
                    for e in related_ceiling],
                'message': 'Reviewed related-movement history used more external load than this configuration offers. '
                    'Reassess this choice or ask the user. This is uncertainty, not a strength conversion or proof of inadequate stimulus; '
                    'changing proposed reps or enabling native calibration does not establish sufficient available resistance.'})
        if not item['totalSessions'] and item.get('relatedHistoryStatus') == 'checked_local_unconfirmed':
            concerns.append({'code': 'related_history_unconfirmed',
                'message': 'No exact exercise sessions are recorded, and related-history matching could not be confirmed. Calibrate effort before treating this movement as load-suitable; do not infer a match or transfer loads.'})
        if not item['totalSessions'] and item.get('otherSetupSessionCount'):
            concerns.append({'code': 'historical_setup_not_comparable',
                'message': 'Recorded performances use a different or unresolved setup. Read otherSetupSessions and candidateContext; do not transfer their load as an exact current prescription.'})
        setup_concern = _recorded_added_load_setup_concern(item)
        if setup_concern:
            concerns.append(setup_concern)
        return concerns

    def load_suitability_errors(self, plan, messages, equipment):
        return self.load_suitability_validator(messages, equipment)(plan)

    def load_suitability_validator(self, messages, equipment):
        """Resolve evidence once for a bounded batch of candidate prescriptions."""
        from .recipe_contracts import recorded_evidence
        evidence = recorded_evidence(messages, library_fingerprint(equipment), self.fingerprint)
        if evidence:
            evidence = self.refresh_evidence_metadata({
                'historyFingerprint': self.fingerprint,
                'libraryFingerprint': library_fingerprint(equipment),
                'exercises': list(evidence.values()),
            }, equipment)
            evidence = {item['definitionId']: item for item in evidence['exercises']
                        if item.get('definitionId')}
        def validate_plan(plan):
            definitions = sorted(equipment.get('exerciseDefinitions', []), key=lambda item: item['id'])
            by_id = {item['id']: f'LIBRARY_{index}' for index, item in enumerate(definitions)}
            missing = list(dict.fromkeys(by_id[item['libraryDefinitionId']]
                for item in plan.get('exercises', [])
                if item.get('libraryDefinitionId') in by_id and item['libraryDefinitionId'] not in evidence))
            for start in range(0, len(missing), 100):
                fresh = self.evidence({'definition_ids': missing[start:start + 100]}, equipment)
                evidence.update((item['definitionId'], item) for item in fresh['exercises'])
            errors = []
            positions = {key: f'/workouts/{day}/exercises/{index}' for day, workout in enumerate(plan.get('workouts', []))
                         for index, key in enumerate(workout.get('exerciseIds', []))}
            for exercise in plan.get('exercises', []):
                item = evidence.get(exercise.get('libraryDefinitionId'))
                concerns = copy.deepcopy((item['loadSuitabilityConcerns'] if 'loadSuitabilityConcerns' in item
                                          else self._load_concerns(item)) if item else [])
                maximum_rir = plan.get('workingSetRIR', {}).get('maximum')
                if item and exercise.get('maxReps') and number(maximum_rir):
                    records = [p['record'] for session in item.get('sessions', [])[:1] for p in session.get('performances', [])
                               if p.get('record', {}).get('actualReps', 0) > exercise['maxReps'] + maximum_rir]
                    loads = [p.get('weight', p.get('additionalWeight')) for p in exercise.get('targetSetPrescriptions', [])]
                    if records and (not loads or any(number(load) and load <= record['loadKg']
                            for load in loads for record in records)):
                        concerns.append({'code': 'historical_reps_exceed_prescription',
                            'message': 'The latest exact-movement history exceeded the prescribed rep ceiling at an equal/higher load, or no starting load is declared. This is an effort-calibration concern, not proof of current strength. Verify effort instead of silently counting easier sets as hard work.'})
                supports_load_calibration = exercise.get('exerciseType') == 'WEIGHT' or (
                    exercise.get('exerciseType') == 'BODY_WEIGHT' and exercise.get('equipmentId') is not None
                )
                # Setup observations are fixed evidence facts, independent of
                # the prescription. Historical headroom is not current capacity.
                suitability_concerns = [concern for concern in concerns
                    if concern.get('code') in ('historical_reps_exceed_prescription',
                                               'recorded_loaded_setup_requires_reassessment')
                    or concern.get('code') in LOAD_CEILING_CONCERNS]
                if not suitability_concerns:
                    continue
                ceiling_concern = any(concern.get('code') in LOAD_CEILING_CONCERNS for concern in suitability_concerns)
                if supports_load_calibration and exercise.get('requiresLoadCalibration') is True and not ceiling_concern:
                    continue
                if suitability_concerns:
                    errors.append({'code': 'training_load_suitability_unresolved', 'path': positions.get(exercise['id'], '/exercises'),
                        'exerciseId': exercise['id'], 'exercise': exercise.get('name', exercise['id']), 'concerns': suitability_concerns,
                        **({'repairStage': 'candidate_reassessment'} if ceiling_concern or not supports_load_calibration else {}),
                        'repair': ('Reassess the available loading configuration or ask the user; native calibration cannot expand its load ceiling.'
                            if ceiling_concern else 'For WEIGHT or equipped BODY_WEIGHT, enable app native load calibration. Otherwise choose a supported configuration or ask the user.')})
            return errors
        return validate_plan

    def _add_related_history(self, result, equipment, client):
        from .exercise_library_tools import _semantic_matches, _selection_entry
        fingerprint = library_fingerprint(equipment)
        definitions = {d['id']: d for d in equipment.get('exerciseDefinitions', [])}
        historical = sorted((self.definitions[key] for key in self.sessions), key=lambda d: d['id'])
        gear = {item['id']: item.get('name') for source in (self._history_equipment, equipment)
                for field in ('equipments', 'accessoryEquipments') for item in source.get(field, [])}
        with self._related_lock:
            check_cancelled()
            for item in result['exercises']:
                if not any(d['id'] != item['definitionId'] for d in historical):
                    self._related_cache[fingerprint, item['definitionId']] = []
                    self._related_status_cache[fingerprint, item['definitionId']] = 'checked'
            pending = [item for item in result['exercises'] if (fingerprint, item['definitionId']) not in self._related_cache]
            cached = {item['definitionId']: (list(self._related_cache[fingerprint, item['definitionId']]),
                self._related_status_cache.get((fingerprint, item['definitionId']), 'checked'))
                for item in result['exercises'] if (fingerprint, item['definitionId']) in self._related_cache}
        updates = {}
        if pending:
            entries = [_selection_entry(d, gear, f'HISTORY_{i}') for i, d in enumerate(historical)]
            queries = [json.dumps({'candidate': _selection_entry(definitions[item['definitionId']], gear, item['reference']),
                'purpose': 'Find related historical movement patterns across equipment variants, including bilateral/unilateral differences. '
                           'Do not restrict to the same implement or muscle overlap alone. Generic Test labels establish no movement identity.'})
                       for item in pending]
            matches = _semantic_matches(client, queries, entries) if historical else [{} for _ in pending]
            check_cancelled()
            rerank_failures = getattr(matches, 'rerank_failures', {})
            for query_index, (item, candidates) in enumerate(zip(pending, matches)):
                cache_key = (fingerprint, item['definitionId'])
                if query_index in rerank_failures:
                    updates[cache_key] = ([], 'checked_local_unconfirmed')
                    continue
                ranked = sorted(candidates, key=lambda index: (-candidates[index], historical[index]['id']))
                updates[cache_key] = ([
                    (index, candidates[index]) for index in ranked
                    if historical[index]['id'] != item['definitionId'] and candidates[index] >= 0.45][:3], 'checked')
        with self._related_lock:
            check_cancelled()
            for cache_key, (candidates, status) in updates.items():
                self._related_cache[cache_key] = candidates
                self._related_status_cache[cache_key] = status
                cached[cache_key[1]] = (list(candidates), status)
        history_equipment = {**equipment, 'exerciseDefinitions': historical}
        current_refs = {d['id']: f'LIBRARY_{i}' for i, d in enumerate(sorted(definitions.values(), key=lambda d: d['id']))}
        for item in result['exercises']:
            item['relatedMovementHistory'] = []
            candidates, item['relatedHistoryStatus'] = cached[item['definitionId']]
            if item['relatedHistoryStatus'] == 'checked_local_unconfirmed':
                item['relatedHistoryWarning'] = 'Semantic relevance was weak and model adjudication failed; no related history was accepted.'
            candidate = definitions[item['definitionId']]
            for index, score in candidates:
                related = historical[index]
                evidence = self._exact_evidence({'definition_ids': [f'LIBRARY_{index}'], 'session_limit': 1}, history_equipment)['exercises'][0]
                differences = {field: {'candidate': candidate.get(field), 'historical': related.get(field)}
                               for field in ('name', 'exerciseType', 'equipmentId', 'bodyWeightPercentage', 'requiredAccessoryEquipmentIds')
                               if candidate.get(field) != related.get(field)}
                item['relatedMovementHistory'].append({**evidence, 'reference': current_refs.get(related['id'], f'HISTORY_{index}'),
                    'matchType': 'related_not_equivalent', 'relevanceScore': score, 'differences': differences,
                    'equipmentName': gear.get(related.get('equipmentId')),
                    'loadTransfer': RELATED_LOAD_TRANSFER_CAUTION})

    def _exact_evidence(self, arguments, equipment):
        validate(arguments, GET_TRAINING_EVIDENCE_TOOL['function']['parameters'])
        cache_key = (json.dumps(arguments, sort_keys=True), library_fingerprint(equipment))
        if cache_key in self._cache:
            return copy.deepcopy(self._cache[cache_key])
        definitions = sorted(equipment.get('exerciseDefinitions', []), key=lambda d: d['id'])
        by_ref = {f'LIBRARY_{i}': definition for i, definition in enumerate(definitions)}
        unknown = set(arguments['definition_ids']) - by_ref.keys()
        if unknown:
            raise ValueError(f'Unknown exercise library references: {sorted(unknown)}')
        gear = {item['id']: item for item in equipment.get('equipments', [])}
        accessories = {item['id']: item for item in equipment.get('accessoryEquipments', [])}
        result = {'historyFingerprint': self.fingerprint, 'libraryFingerprint': cache_key[1], 'exercises': [], 'equipmentLoadOptions': {},
                  'evidenceFormat': EVIDENCE_FORMAT}
        for reference in dict.fromkeys(arguments['definition_ids']):
            definition = by_ref[reference]
            saved_definition = self.definitions.get(definition['id'], {})
            identity_matches = all(saved_definition.get(field) == definition.get(field)
                                   for field in ('name', 'exerciseType', 'equipmentId', 'bodyWeightPercentage', 'requiredAccessoryEquipmentIds', 'movementRef'))
            sessions = self.sessions.get(definition['id'], [])
            selected_gear = gear.get(definition.get('equipmentId'))
            comparable, other_setups = [], []
            for session in sessions:
                performances, different = [], []
                for performance in session['performances']:
                    limitations = []
                    if not identity_matches:
                        limitations.append('exercise_definition_changed')
                    if performance['equipmentId'] != definition.get('equipmentId'):
                        limitations.append('recorded_equipment_differs_or_is_unresolved')
                    historical_type = performance.get('equipmentContext', {}).get('type')
                    if historical_type and selected_gear and historical_type != selected_gear.get('type'):
                        limitations.append('recorded_equipment_type_changed')
                    if performance['exerciseType'] != definition.get('exerciseType'):
                        limitations.append('exercise_type_changed')
                    if set(performance['requiredAccessoryEquipmentIds']) != set(definition.get('requiredAccessoryEquipmentIds') or []):
                        limitations.append('required_accessories_changed')
                    percentage = performance.get('bodyWeightPercentage')
                    if (definition.get('exerciseType') == 'BODY_WEIGHT' and number(percentage)
                            and percentage != definition.get('bodyWeightPercentage')):
                        limitations.append('bodyweight_percentage_changed')
                    if limitations:
                        different.append({**performance, 'comparisonLimitations': limitations})
                    else:
                        performances.append(performance)
                if performances:
                    comparable.append({**session, 'performances': performances})
                if different:
                    other_setups.append({**session, 'performances': different})
            latest = comparable[0] if comparable else None
            loads = [p['record']['loadKg'] for p in latest['performances'] if 'loadKg' in p['record']] if latest else []
            reference_load = max(loads) if loads else None
            observations = [(p['record']['loadKg'],session.get('date'),p['record']['actualReps'],session.get('endReason'))
                for session in comparable for p in session['performances']
                if number(p['record'].get('loadKg')) and number(p['record'].get('actualReps')) and p['record']['actualReps']>0]
            highest = max(observations,key=lambda item:item[0]) if observations else None
            equipment_id = definition.get('equipmentId')
            selected_gear = gear.get(equipment_id)
            load_key = json.dumps([definition.get('exerciseType'), selected_gear], sort_keys=True)
            if load_key not in self._loads:
                self._loads[load_key] = (sorted(get_selectable_weights_for_exercise(definition['exerciseType'], selected_gear)) if selected_gear
                                        else [0.0] if definition['exerciseType'] == 'BODY_WEIGHT' else [])
            options = self._loads[load_key]
            if equipment_id:
                result['equipmentLoadOptions'][equipment_id] = {'name': (selected_gear or {}).get('name'), 'selectableLoadsKg': options,
                    'loadConvention': 'pair_total' if (selected_gear or {}).get('type') == 'DUMBBELLS' else 'app_total'}
            higher = [load for load in options if reference_load is not None and load > reference_load + 0.001]
            maximum = max(options) if options else None
            headroom = {'latestSessionHeaviestLoadKg': reference_load, 'maximumSelectableLoadKg': maximum,
                        'highestObservedComparableLoad':dict(zip(('loadKg','date','reps','endReason'),highest)) if highest else None,
                        'nextHigherSelectableLoadKg': higher[0] if higher else None, 'higherLoadOptionCount': len(higher),
                        'observedAtCurrentEquipmentMaximum': reference_load is not None and maximum is not None and abs(reference_load - maximum) < 0.001,
                        'latestObservedLoadsNotSelectableNow': [load for load in sorted(set(loads)) if not any(abs(load - option) < 0.001 for option in options)]}
            offset, limit = arguments.get('session_offset', 0), arguments.get('session_limit', 1)
            page = comparable[offset:offset + limit]
            other_page = other_setups[offset:offset + limit]
            page_count = max(len(comparable), len(other_setups))
            days = None
            if latest and latest.get('date'):
                try:
                    days = (date.today() - date.fromisoformat(latest['date'])).days
                except ValueError:
                    pass
            result['exercises'].append({'reference': reference, 'definitionId': definition['id'], 'name': definition['name'],
                'status': 'comparable_records' if comparable else 'no_comparable_records', 'totalSessions': len(comparable),
                'daysSinceLatestSession': days, 'sessions': page,
                'otherSetupSessions': other_page, 'otherSetupSessionCount': len(other_setups),
                'sessionOffset': offset, 'hasMore': offset + limit < page_count,
                'nextOffset': offset + limit if offset + limit < page_count else None, 'loadHeadroom': headroom,
                'uncertainty': 'Effort is unknown unless recorded per set. Historical performance is not a measured maximum or guaranteed current capability.'})
            current_context = {'exerciseType': definition['exerciseType'],
                'equipmentId': definition.get('equipmentId'),
                'requiredAccessoryNames': [accessories.get(key, {}).get('name')
                    for key in definition.get('requiredAccessoryEquipmentIds') or []],
                'equipment': {'name': (selected_gear or {}).get('name'), 'type': (selected_gear or {}).get('type'),
                              'source': 'current_configuration'},
                'loadMeaning': ('additional_bodyweight_load' if definition['exerciseType'] == 'BODY_WEIGHT'
                                else 'not_applicable' if definition['exerciseType'] == 'RUNNING' else 'app_total_external_load')}
            if definition['exerciseType'] == 'BODY_WEIGHT':
                current_context['bodyWeightPercentage'] = definition.get('bodyWeightPercentage')
                if number(equipment.get('weightKg')) and number(definition.get('bodyWeightPercentage')):
                    current_context.update(configuredBodyMassKg=equipment['weightKg'],
                        effectiveBodyweightKg=equipment['weightKg'] * definition['bodyWeightPercentage'] / 100)
            result['exercises'][-1]['candidateContext'] = current_context
            result['exercises'][-1]['loadHeadroom']['loadMeaning'] = current_context['loadMeaning']
        self._cache[cache_key] = copy.deepcopy(result)
        return result

    def annotate_search(self, payload, equipment):
        references = list(dict.fromkeys(entry['id'] for query in payload.get('results', []) for entry in query.get('exercises', [])))
        by_ref = {}
        for start in range(0, len(references), 12):
            evidence = self.evidence({'definition_ids': references[start:start + 12], 'session_limit': 1}, equipment)
            for item in evidence['exercises']:
                by_ref[item['reference']] = {key: item[key] for key in ('status', 'totalSessions', 'daysSinceLatestSession', 'loadHeadroom', 'candidateContext', 'otherSetupSessionCount')}
        for query in payload.get('results', []):
            for entry in query.get('exercises', []):
                entry['trainingEvidence'] = by_ref[entry['id']]
        payload['historyFingerprint'] = self.fingerprint
        return payload

    def unreviewed(self, plan, messages, equipment):
        definitions = sorted(equipment.get('exerciseDefinitions', []), key=lambda d: d['id'])
        references = {d['id']: f'LIBRARY_{i}' for i, d in enumerate(definitions)}
        selected = [references[e['libraryDefinitionId']] for e in plan.get('exercises', []) if e.get('libraryDefinitionId') in references]
        required = set(selected) if self.sessions else set()
        calls = {call['id']: call['function']['name'] for message in messages for call in message.get('tool_calls', [])}
        for message in messages:
            if calls.get(message.get('tool_call_id')) != 'get_training_evidence':
                continue
            try:
                result = json.loads(message.get('content', ''))
            except (TypeError, ValueError):
                continue
            if isinstance(result, dict) and result.get('historyFingerprint') == self.fingerprint and result.get('libraryFingerprint') == library_fingerprint(equipment):
                required.difference_update(item['reference'] for item in result.get('exercises', [])
                                           if item.get('sessions') or item.get('relatedHistoryStatus') in ('checked', 'checked_local_unconfirmed'))
        return sorted(required)
