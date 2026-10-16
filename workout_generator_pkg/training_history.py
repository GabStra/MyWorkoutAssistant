"""Targeted, version-aware historical evidence for workout planning."""
import copy
import hashlib
import json
import math
from collections import defaultdict
from datetime import date

from jsonschema import validate
from workout_history_mcp.loader import WorkoutHistoryStore, load_backup, _is_active_set
from .domain_ops import get_selectable_weights_for_exercise
from .planning_tools import library_fingerprint

RELATED_LOAD_TRANSFER_CAUTION = 'Do not convert or transfer loads automatically. Execution, laterality, reps, effort and equipment affect comparability.'

GET_TRAINING_EVIDENCE_TOOL = {'type': 'function', 'function': {
    'name': 'get_training_evidence',
    'description': 'Retrieve exact working-set history, semantically related movement history, and equipment progression headroom for candidate LIBRARY_n exercises. Batch candidates. Defaults to the latest comparable session; request more or page older sessions only for a specific evidence gap. Related loads are separate evidence, never strength conversions.',
    'parameters': {'type': 'object', 'properties': {
        'definition_ids': {'type': 'array', 'items': {'type': 'string', 'pattern': '^LIBRARY_[0-9]+$'}, 'minItems': 1, 'maxItems': 12},
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
    'When the equipment ceiling is already used, consider progression within the agreed rep range or an appropriate available variant; '
    'do not silently add sets, change volume/time targets, or invent a strength conversion between related movements. '
    'Use targetSetPrescriptions only for justified achievable starting loads or explicit user-provided loads. '
    'When history does not justify a load, leave exact prescriptions unset so load calibration is required. '
    'Compare relatedMovementHistory with the candidate equipment ceiling before choosing an unrecorded variant. '
    'Related movement loads are not directly interchangeable: inspect equipment, execution and load conventions. '
    'HISTORY_n references identify evidence-only historical movements; only LIBRARY_n references are selectable exercises. '
    'If related performance suggests a candidate may be too lightly loaded at the requested reps/RIR, justify its use, '
    'choose a supported alternative, or ask for calibration; do not count it as a hard set merely to fill a volume gap. '
    'Resolve loadSuitabilityConcerns before submitting a draft. Prefer an available loadable variant. If suitability remains uncertain, '
    'set requiresEffortCalibration=true for that occurrence and omit targetSetPrescriptions; the preview must show conditional volume. '
    'Extra sets or slower tempo do not by themselves resolve an equipment-capacity concern. '
    'A zero added-load ceiling applies to that library entry, not to all variants of the movement. Before declaring a movement unloadable '
    'or requesting changed targets, use available candidate results or search for a loadable variant for this specific gap. '
    'An empty loadSuitabilityConcerns list only means these deterministic checks found no flag; it does not verify current RIR, '
    'prescribed reps, or performance with shorter rests. Treat history-based loads as provisional starting points. '
    'Dumbbell-pair loads are app totals across both implements; bodyweight additional load is separate from recorded relative bodyweight. '
    'Generic legacy labels such as Test do not establish a movement identity; do not prescribe them without clarification. '
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
        if 'relatedMovementHistory' in item:
            entry['relatedMovementHistory'] = links
        for session in entry.get('sessions', []):
            for field in ('sessionId', 'workoutId', 'time'):
                session.pop(field, None)
            for performance in session.get('performances', []):
                for field in ('exerciseId', 'startTime'):
                    performance.pop(field, None)
                performance.get('record', {}).pop('setHistoryId', None)
        if (not related or reference not in catalog
                or (catalog[reference].get('historyDetailsOmitted') and not entry.get('historyDetailsOmitted'))):
            catalog[reference] = entry

    for item in items:
        collect(item)
    return catalog


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class TrainingHistory:
    def __init__(self, backup):
        store = WorkoutHistoryStore(backup)
        if not isinstance(backup.get('WorkoutStore'), dict) or not isinstance(backup.get('SetHistories'), list):
            raise ValueError('Expected an AppBackup with WorkoutStore and SetHistories')
        # Invalidate saved tool results when evidence interpretation changes.
        self.fingerprint = hashlib.sha256(json.dumps({'evidenceVersion': 6, 'backup': backup}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
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
        grouped = defaultdict(dict)
        self.unresolved_records = 0
        for record in store.set_histories:
            session = sessions.get(record.get('workoutHistoryId'))
            if not session or not _is_active_set(record) or record.get('skipped'):
                continue
            data = record.get('setData', {})
            if data.get('hasBeenExecuted') is False:
                continue
            exercise = occurrences.get((session.get('workoutId'), record.get('exerciseId')))
            if exercise is None or exercise.get('exerciseDefinitionId') not in self.definitions:
                self.unresolved_records += 1
                continue
            item = self._set_record(record)
            if item is None:
                continue
            definition_id = exercise['exerciseDefinitionId']
            execution_context = execution_contexts[(session['workoutId'], exercise['id'])]
            group = grouped[definition_id].setdefault(session['id'], {
                'sessionId': session['id'], 'date': session.get('date'), 'time': session.get('time'),
                'workoutId': session['workoutId'], 'endReason': session.get('endReason'), 'performances': [],
            })
            # Retain occurrence context: one movement can appear twice in a session.
            group['performances'].append({
                'exerciseId': exercise['id'], 'equipmentId': exercise.get('equipmentId'),
                'exerciseType': exercise.get('exerciseType'), 'order': record.get('order'),
                'startTime': record.get('startTime'),
                'prescribedRestSeconds': self._rest_seconds(exercise) if execution_context['type'] == 'straightSets' else [],
                'executionContext': execution_context,
                'intraSetRestInSeconds': exercise.get('intraSetRestInSeconds'), 'record': item,
            })
        self.sessions = {key: sorted(values.values(), key=lambda s: (s.get('date') or '', s.get('time') or ''), reverse=True)
                         for key, values in grouped.items()}
        for values in self.sessions.values():
            for session in values:
                session['performances'].sort(key=lambda item: (item.get('startTime') or '', str(item.get('order', ''))))
        self._loads = {}
        self._cache = {}
        self._related_cache = {}
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
        elif kind in ('TimedDurationSetData', 'EnduranceSetData'):
            start, end = data.get('startTimer'), data.get('endTimer')
            if not number(end) or (kind == 'TimedDurationSetData' and not number(start)):
                return None
            elapsed = end if kind == 'EnduranceSetData' else start - end
            if elapsed <= 0:
                return None
            result['actualDurationSeconds'] = elapsed / 1000
        else:
            return None
        for field in ('autoRegulationRIR', 'calibrationRIR', 'rir', 'rpe'):
            if number(data.get(field)):
                result[field] = data[field]
        return result

    def context(self):
        dates = [s['date'] for values in self.sessions.values() for s in values if s.get('date')]
        return {'historyFingerprint': self.fingerprint, 'definitionsWithEvidence': len(self.sessions),
                'latestRecordedDate': max(dates) if dates else None, 'unresolvedRecordsExcluded': self.unresolved_records}

    def evidence(self, arguments, equipment, client=None):
        result = self._exact_evidence(arguments, equipment)
        if client is not None:
            self._add_related_history(result, equipment, client)
        for item in result['exercises']:
            item['loadSuitabilityConcerns'] = self._load_concerns(item)
        return result

    @staticmethod
    def _load_concerns(item):
        concerns = []
        headroom = item['loadHeadroom']
        maximum, observed = headroom['maximumSelectableLoadKg'], headroom['latestSessionHeaviestLoadKg']
        if number(maximum) and number(observed) and observed > maximum + .001:
            concerns.append({'code': 'recorded_load_exceeds_current_capacity',
                'recordedLoadKg': observed, 'maximumSelectableLoadKg': maximum,
                'message': 'Exact exercise history used more resistance than is currently selectable. This flags uncertainty, not current strength.'})
        if not item['totalSessions'] and any(e.get('sessions') for e in item.get('relatedMovementHistory', [])):
            concerns.append({'code': 'related_history_only',
                'message': 'Only related movement performance is available. Verify the candidate resistance/effort; do not transfer loads or infer suitability from another implement ceiling.'})
        return concerns

    def load_suitability_errors(self, plan, messages, equipment):
        calls = {call['id']: call['function']['name'] for message in messages for call in message.get('tool_calls', [])}
        evidence = {}
        fingerprint = library_fingerprint(equipment)
        for message in messages:
            if calls.get(message.get('tool_call_id')) != 'get_training_evidence':
                continue
            try:
                result = json.loads(message.get('content', ''))
            except (TypeError, ValueError):
                continue
            if isinstance(result, dict) and result.get('historyFingerprint') == self.fingerprint and result.get('libraryFingerprint') == fingerprint:
                evidence.update({e['definitionId']: e for e in result.get('exercises', [])})
        errors = []
        positions = {key: f'/workouts/{day}/exercises/{index}' for day, workout in enumerate(plan.get('workouts', []))
                     for index, key in enumerate(workout.get('exerciseIds', []))}
        for exercise in plan.get('exercises', []):
            item = evidence.get(exercise.get('libraryDefinitionId'))
            concerns = self._load_concerns(item) if item else []
            if concerns and not exercise.get('requiresEffortCalibration'):
                errors.append({'code': 'training_load_suitability_unresolved', 'path': positions.get(exercise['id'], '/exercises'),
                    'exerciseId': exercise['id'], 'exercise': exercise['name'], 'concerns': concerns,
                    'repair': 'Compare available loadable variants using search_exercise_library and get_training_evidence. '
                              'Choose a supported alternative, or explicitly set requiresEffortCalibration=true and remove targetSetPrescriptions. '
                              'Volume must remain conditional on verifying prescribed effort; extra sets or tempo alone do not resolve this concern. Re-audit.'})
        return errors

    def _add_related_history(self, result, equipment, client):
        from .exercise_library_tools import _semantic_matches, _selection_entry
        fingerprint = library_fingerprint(equipment)
        definitions = {d['id']: d for d in equipment.get('exerciseDefinitions', [])}
        historical = sorted((self.definitions[key] for key in self.sessions), key=lambda d: d['id'])
        gear = {item['id']: item.get('name') for source in (self._history_equipment, equipment)
                for field in ('equipments', 'accessoryEquipments') for item in source.get(field, [])}
        for item in result['exercises']:
            if not any(d['id'] != item['definitionId'] for d in historical):
                self._related_cache[fingerprint, item['definitionId']] = []
        pending = [item for item in result['exercises'] if (fingerprint, item['definitionId']) not in self._related_cache]
        if pending:
            entries = [_selection_entry(d, gear, f'HISTORY_{i}') for i, d in enumerate(historical)]
            queries = [json.dumps({'candidate': _selection_entry(definitions[item['definitionId']], gear, item['reference']),
                'purpose': 'Find related historical movement patterns across equipment variants, including bilateral/unilateral differences. '
                           'Do not restrict to the same implement or muscle overlap alone. Generic Test labels establish no movement identity.'})
                       for item in pending]
            matches = _semantic_matches(client, queries, entries) if historical else [{} for _ in pending]
            for item, candidates in zip(pending, matches):
                ranked = sorted(candidates, key=lambda index: (-candidates[index], historical[index]['id']))
                self._related_cache[fingerprint, item['definitionId']] = [
                    (index, candidates[index]) for index in ranked
                    if historical[index]['id'] != item['definitionId'] and candidates[index] > 0][:3]
        history_equipment = {**equipment, 'exerciseDefinitions': historical}
        current_refs = {d['id']: f'LIBRARY_{i}' for i, d in enumerate(sorted(definitions.values(), key=lambda d: d['id']))}
        for item in result['exercises']:
            item['relatedMovementHistory'] = []
            item['relatedHistoryStatus'] = 'checked'
            candidate = definitions[item['definitionId']]
            for index, score in self._related_cache[fingerprint, item['definitionId']]:
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
        result = {'historyFingerprint': self.fingerprint, 'libraryFingerprint': cache_key[1], 'exercises': [], 'equipmentLoadOptions': {}}
        for reference in dict.fromkeys(arguments['definition_ids']):
            definition = by_ref[reference]
            saved_definition = self.definitions.get(definition['id'], {})
            identity_matches = all(saved_definition.get(field) == definition.get(field)
                                   for field in ('name', 'exerciseType', 'equipmentId', 'bodyWeightPercentage', 'requiredAccessoryEquipmentIds', 'movementRef'))
            sessions = self.sessions.get(definition['id'], []) if identity_matches else []
            comparable = []
            for session in sessions:
                performances = [p for p in session['performances'] if p['equipmentId'] == definition.get('equipmentId') and p['exerciseType'] == definition.get('exerciseType')]
                if performances:
                    comparable.append({**session, 'performances': performances})
            latest = comparable[0] if comparable else None
            loads = [p['record']['loadKg'] for p in latest['performances'] if 'loadKg' in p['record']] if latest else []
            reference_load = max(loads) if loads else None
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
                        'nextHigherSelectableLoadKg': higher[0] if higher else None, 'higherLoadOptionCount': len(higher),
                        'observedAtCurrentEquipmentMaximum': reference_load is not None and maximum is not None and abs(reference_load - maximum) < 0.001,
                        'latestObservedLoadsNotSelectableNow': [load for load in sorted(set(loads)) if not any(abs(load - option) < 0.001 for option in options)]}
            offset, limit = arguments.get('session_offset', 0), arguments.get('session_limit', 1)
            page = comparable[offset:offset + limit]
            days = None
            if latest and latest.get('date'):
                try:
                    days = (date.today() - date.fromisoformat(latest['date'])).days
                except ValueError:
                    pass
            result['exercises'].append({'reference': reference, 'definitionId': definition['id'], 'name': definition['name'],
                'status': 'comparable_records' if comparable else 'no_comparable_records', 'totalSessions': len(comparable),
                'daysSinceLatestSession': days, 'sessions': page, 'hasMore': offset + len(page) < len(comparable),
                'nextOffset': offset + len(page) if offset + len(page) < len(comparable) else None, 'loadHeadroom': headroom,
                'uncertainty': 'Effort is unknown unless recorded per set. Historical performance is not a measured maximum or guaranteed current capability.'})
        self._cache[cache_key] = copy.deepcopy(result)
        return result

    def annotate_search(self, payload, equipment):
        references = list(dict.fromkeys(entry['id'] for query in payload.get('results', []) for entry in query.get('exercises', [])))
        by_ref = {}
        for start in range(0, len(references), 12):
            evidence = self.evidence({'definition_ids': references[start:start + 12], 'session_limit': 1}, equipment)
            for item in evidence['exercises']:
                by_ref[item['reference']] = {key: item[key] for key in ('status', 'totalSessions', 'daysSinceLatestSession', 'loadHeadroom')}
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
                                           if item.get('sessions') or item.get('relatedHistoryStatus') == 'checked')
        return sorted(required)
