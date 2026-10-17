"""Build a request-only planning snapshot; the saved transcript remains authoritative."""
import copy
import json
import re

from .planning_tools import library_fingerprint, requirements_approved, latest_draft_submission, requirement_sources, source_message_context, _latest_result
from .training_history import compact_training_evidence, pool_execution_contexts
from .planning_decisions import resolved_decisions, latest_decision_receipt
from .programming_guidelines import GUIDELINE_POLICY

def request_planning_state(messages):
    for message in messages:
        content = message.get('content') or ''
        if message.get('role') == 'system' and content.startswith('Current planning state'):
            return json.loads(content.split('\n', 1)[1])
    return {}


def request_repair_task(messages):
    return request_planning_state(messages).get('repairTask')


def pending_evidence(state, user_input=None):
    """Return missing audit evidence, retrying failed lookups only on a later user turn."""
    if not state.get('requirementsApproved') or state.get('savedDraftReaudit') or state.get('decisionReaudit') or state.get('planningDecisionNeeded'):
        return []
    errors = (state.get('lastAudit') or {}).get('errors') or []
    required = {reference for error in errors if isinstance(error, dict)
                and error.get('code') in ('training_evidence_required', 'training_load_suitability_unresolved')
                for reference in error.get('definition_ids', []) if isinstance(reference, str)}
    draft = state.get('currentDraft') or {}
    if state.get('currentDraftAudited'):
        required.update(state.get('selectedDefinitionReferences', []))
    preparation = (state.get('constructionTask') or {}).get('definition_ids', [])
    required.update(preparation)
    for error in errors:
        if not isinstance(error, dict) or error.get('code') != 'training_load_suitability_unresolved':
            continue
        match = re.match(r'^/workouts/(\d+)/exercises/(\d+)', error.get('path', ''))
        if match:
            day, exercise = map(int, match.groups())
            workouts = draft.get('workouts', [])
            if day < len(workouts) and exercise < len(workouts[day].get('exercises', [])):
                required.add(workouts[day]['exercises'][exercise].get('definition_id'))
    required.discard(None)
    retrieved = (set(state['retrievedEvidenceReferences']) if 'retrievedEvidenceReferences' in state else
                 set(state.get('trainingEvidence', {})) | set(state.get('trainingEvidenceSummary', {})))
    available = required - retrieved
    attempted = set(state.get('attemptedEvidence', []))
    retryable = set(state.get('retryableEvidence', [])) if user_input and user_input.strip() else set()
    return sorted(available - (attempted - retryable))


def _session_blockers(state):
    return [error for error in state.get('currentDraftAuditErrors', [])
            if isinstance(error, dict) and error.get('scope') != 'weekly'
            and (error.get('scope') == 'per_session' or error.get('code') in {
                'duration_exceeded', 'superset_set_count_mismatch', 'empty_superset', 'unbounded_volume',
                'unknown_duration', 'unknown_running_duration', 'missing_training_muscle_roles'}
                 or re.match(r'^/(?:(?:draft|audit)/)?workouts/\d+(?:/|$)', error.get('draftPath', error.get('path', ''))))]


def _session_summary(day, index, candidates):
    summary = {key: day[key] for key in ('name', 'description', 'timesCompletedInAWeek', 'trainingDays') if key in day}
    summary.update(reference=f'WORKOUT_{index}', detailsOmitted=True, exerciseSummary=[])
    for item in day['exercises']:
        exercise = {key: item[key] for key in ('definition_id', 'numWorkSets', 'minReps', 'maxReps', 'superset', 'satisfiesCoverage') if key in item}
        name = candidates.get(item['definition_id'], {}).get('name')
        if name:
            exercise['name'] = name
        summary['exerciseSummary'].append(exercise)
    return summary


def _focus_repair(state, fresh_references, catalog=None, equipment=None, restrictions=None, fresh_evidence=()):
    audit = state.get('lastAudit') or {}
    errors = audit.get('errors') or []
    if (not state['requirementsApproved'] or not state.get('currentDraftId') or state.get('savedDraftReaudit') or state.get('decisionReaudit') or state.get('constructionTask')
            or audit.get('passed') is not False or not errors
            or any(isinstance(error, dict) and error.get('code') in (
                'review_execution_failed', 'requirements_review_failed', 'decision_review_failed', 'tool_execution_failed')
                for error in errors)):
        return
    target = state.get('requirements', {}).get('sessionsPerWeek')
    frequency = sum(day['timesCompletedInAWeek'] for day in state['currentDraft']['workouts'])
    incomplete = target and frequency < target
    blockers = _session_blockers(state) if incomplete else []
    eligible = [i for i, error in enumerate(errors) if not blockers or error in blockers]
    if not eligible:
        return
    primary = errors[eligible[0]]
    numeric = {'duration_exceeded', 'volume_below_target', 'volume_above_target', 'superset_set_count_mismatch'}
    evidence_codes = {'training_evidence_required', 'training_load_suitability_unresolved'}
    code = primary.get('code') if isinstance(primary, dict) else None
    family = numeric if code in numeric else evidence_codes if code in evidence_codes else {code}
    finding_indexes = [i for i in eligible if isinstance(errors[i], dict) and errors[i].get('code') in family] or [eligible[0]]
    relevant_errors = [errors[i] for i in finding_indexes]
    references, affected_days = set(), set()
    draft = copy.deepcopy(state['currentDraft'])
    state['currentDraft'] = draft
    for error in relevant_errors:
        path = error.get('draftPath', error.get('path', '')) if isinstance(error, dict) else ''
        match = re.match(r'^/(?:(?:draft|audit)/)?workouts/(\d+)(?:/|$)', path)
        if match:
            affected_days.add(int(match[1]))
        else:
            affected_days.update(range(len(draft['workouts'])))
    retrieved = state['otherToolResults'].get('get_workout_draft', {})
    if retrieved.get('baseDraftId') == state['currentDraftId']:
        affected_days.update(int(reference.removeprefix('WORKOUT_')) for reference in retrieved.get('workouts', {}))
    for day_index in affected_days:
        if day_index < len(draft['workouts']):
            references.update(item['definition_id'] for item in draft['workouts'][day_index]['exercises'])
    references.update(fresh_references)
    affected_muscles = set()
    for error in relevant_errors:
        if not isinstance(error, dict):
            continue
        references.update(error.get('definition_ids', []))
        muscle = error.get('muscle')
        if muscle:
            affected_muscles.add(muscle)
        if error.get('scope') == 'weekly' and muscle:
            references.update(reference for reference, entry in state['exerciseCandidates'].items()
                              if any(entry.get('creditsPerWorkingSet', {}).get(muscle, {}).get(kind, 0)
                                     for kind in ('direct', 'indirect', 'effective')))
    if isinstance(primary, dict):
        paths = [primary.get('draftPath', primary.get('path', ''))] + primary.get('evidencePaths', [])
        for path in paths:
            references.update(re.findall(r'LIBRARY_[0-9]+', path))
            position = re.match(r'^/(?:draft/)?workouts/(\d+)/exercises/(\d+)(?:/|$)', path)
            if position:
                days = state['currentDraft'].get('workouts', [])
                day = int(position[1])
                if day < len(days):
                    entries = days[day].get('exercises', [])
                    index = int(position[2])
                    if index < len(entries):
                        references.add(entries[index].get('definition_id'))
    selected = {entry.get('definition_id') for day in state['currentDraft'].get('workouts', [])
                for entry in day.get('exercises', [])}
    candidates = state['exerciseCandidates']
    for reference in list(candidates):
        if reference not in references:
            entry = candidates.pop(reference)
            if reference in selected or any(entry.get('creditsPerWorkingSet', {}).get(muscle, {}).get(kind, 0)
                   for muscle in affected_muscles for kind in ('direct', 'indirect', 'effective')):
                state.setdefault('cachedCandidateIndex', {})[reference] = {key: entry[key] for key in (
                    'name', 'exerciseType', 'equipmentName', 'accessoryNames') if key in entry}
    if affected_muscles:
        from .exercise_library_tools import _selection_entry, definition_available
        available = {}
        resolved_restrictions = {key: value for key, value in (restrictions or {}).items()
                                 if key not in ('excludeNameTerms', 'exceptNameTerms')}
        for reference, definition in (catalog or {}).items():
            if reference in selected:
                continue
            try:
                if not definition_available(definition, equipment or {}, resolved_restrictions):
                    continue
            except ValueError:
                continue
            available[reference] = _selection_entry(definition, {}, reference)
        state['cachedCandidateIndex'] = {
            reference: entry for reference, entry in state.get('cachedCandidateIndex', {}).items()
            if reference in available and any(
                available[reference].get('creditsPerWorkingSet', {}).get(muscle, {}).get(kind, 0)
                for muscle in affected_muscles for kind in ('direct', 'indirect', 'effective'))}
        state['availableAlternativeCountByMuscle'] = {
            muscle: sum(any(entry.get('creditsPerWorkingSet', {}).get(muscle, {}).get(kind, 0)
                            for kind in ('direct', 'indirect', 'effective')) for entry in available.values())
            for muscle in sorted(affected_muscles)}
    evidence = state['trainingEvidence']
    detailed = set()
    def include(reference):
        if reference in detailed or reference not in evidence:
            return
        detailed.add(reference)
        for related in evidence[reference].get('relatedMovementHistory', []):
            include(related.get('reference'))
    # Execution/allocation repairs need prescriptions and credits, not unrelated performance records.
    evidence_repair = code in evidence_codes or any(
        error.get('reviewScope') == 'evidence'
        or '/targetSetPrescriptions' in error.get('draftPath', error.get('path', ''))
        for error in relevant_errors)
    history_references = references if evidence_repair else set()
    history_references |= set(fresh_evidence)
    for reference in history_references:
        include(reference)
    state['trainingEvidenceSummary'] = {reference: {key: entry[key] for key in (
        'name', 'status', 'totalSessions', 'daysSinceLatestSession', 'loadHeadroom',
        'loadSuitabilityConcerns', 'relatedHistoryStatus', 'uncertainty') if key in entry}
        for reference, entry in evidence.items() if reference in selected and reference not in detailed}
    state['trainingEvidence'] = {reference: entry for reference, entry in evidence.items() if reference in detailed}
    # Broad repair instructions in older receipts are replaced only in this request.
    audit['instruction'] = 'Use repairTask; remaining findings stay open until the full draft passes.'
    state['repairTask'] = {
        'baseDraftId': state['currentDraftId'], 'findingIndex': finding_indexes[0],
        'findingIndexes': finding_indexes,
        'findingCode': primary.get('code', 'finding') if isinstance(primary, dict) else 'finding',
        'instruction': 'Address lastAudit.errors at findingIndexes together. Make the smallest coordinated patch, including connected changes needed '
                       'to preserve the remaining constraints. Submit promptly; other findings may remain and intermediate audits may fail. '
                       'Do not solve the entire program in one response. Use the audit for calculations. '
                       'If evidence is missing, request only the needed LIBRARY_n references; summaries are not exact performance records. '
                       'Use relevant cachedCandidateIndex entries first. For unlisted alternatives, search the named affected muscles and use returned options; availableAlternativeCountByMuscle reports the remaining library count. '
                       'For coupled weekly numeric findings, supply complete allowed minimum and maximum bounds for every affected slot when calling the allocator; do not leave connected slots fixed by omission. '
                       'Prefer declaring allocationBounds in a patch for flexible counts, then audit: Python attempts allocation automatically. '
                       'Omitted bounds and exact prescriptions stay locked. Do not widen a source-backed limit to hide infeasibility. '
                       'Full history is saved behind get_training_evidence. '
                       'If the latest user asks a question or changes the task, answer it instead of applying an unsolicited repair. '
                       'Ask about genuine ambiguity; never waive requirements. A passing preview and fresh confirmation remain mandatory.'}
    if retrieved.get('baseDraftId') == state['currentDraftId']:
        state['otherToolResults']['get_workout_draft'] = {'baseDraftId': retrieved['baseDraftId'],
            'retrievedWorkoutReferences': list(retrieved['workouts'])}
    if incomplete:
        state['repairTask']['instruction'] = (
            'The week is incomplete. Repair only the existing-session blockers at findingIndexes, then resume appending sessions. '
            'Defer weekly volume and weekly coverage shortages until all requested sessions exist. '
            + state['repairTask']['instruction'])
    state['repairTask']['editableWorkoutReferences'] = [f'WORKOUT_{i}' for i in sorted(affected_days)]
    state['repairTask']['omittedWorkoutReferences'] = [f'WORKOUT_{i}' for i in range(len(draft['workouts'])) if i not in affected_days]
    state['repairTask']['instruction'] += (' Unaffected sessions are summaries with detailsOmitted=true. '
        'Call get_workout_draft for their WORKOUT_n references before changing their contents or order. '
        'All patch paths keep their original indices; the backend always re-audits the complete saved draft.')
    for index, day in enumerate(draft['workouts']):
        if index in affected_days:
            continue
        draft['workouts'][index] = _session_summary(day, index, {**state.get('cachedCandidateIndex', {}), **candidates})
        reports = audit.get('audit', {}).get('workouts', [])
        if index < len(reports):
            reports[index] = {key: value for key, value in reports[index].items() if key != 'contributions'}
    # Keep each finding once; the original complete receipts remain in the saved transcript.
    if audit.get('audit'):
        audit['audit'].pop('errors', None)
        audit['audit'].pop('issues', None)


def _focus_construction(state, new_user_instruction=False):
    if not state['requirementsApproved'] or state.get('savedDraftReaudit') or state.get('decisionReaudit') or state.get('planningDecisionNeeded'):
        return
    draft = state.get('currentDraft')
    if draft and new_user_instruction:
        return
    if draft and not state.get('currentDraftAudited'):
        return
    if draft and _session_blockers(state):
        return
    target = state['requirements'].get('sessionsPerWeek')
    frequency = sum(day['timesCompletedInAWeek'] for day in draft['workouts']) if draft else 0
    if draft and (not target or frequency >= target):
        return
    state['constructionTask'] = {
        'action': 'append_session' if draft else 'create_first_session',
        'baseDraftId': state.get('currentDraftId'),
        'remainingWeeklySessions': max(0, target - frequency) if target else None,
        'instruction': 'When at least two sessions remain, prefer prepare_workout_sessions: select movements and schedule for all remaining sessions together; Python drafts them concurrently against shared targets. Otherwise build only the next workout session and submit it to audit_workout_plan. '
            'For a direct single-session submission, provide name/workouts with exactly one workout initially. For later single sessions append one workout '
            'using a JSON Patch add at /workouts/-. Preserve previously saved sessions until construction is complete. '
            'Include the user-requested movement coverage and effort; use available candidates and current evidence. '
            'Do not solve weekly allocation, calculate totals or prove feasibility in reasoning. Intermediate numerical failures '
            'are expected: Python calculates the whole draft and targeted repair follows after all sessions are present. '
            'Missing history can be retrieved for the selected movements. Never waive requirements or show a partial draft as approved. '
            'Declare allocationBounds for flexible set counts within the source constraints; omit them for locked counts. '
            'Python automatically attempts numerical allocation after construction is complete. Exact prescriptions stay locked. '
            'If the user asks a question or gives a genuine ambiguity, answer or clarify instead of creating unsolicited workouts.'}
    if state.get('lastAudit'):
        state['lastAudit']['instruction'] = 'Follow constructionTask first; numerical findings remain open until all sessions are present.'


def planner_response_profile(state):
    """Bound construction and repair work; high effort remains available for open discussion."""
    if state.get('constructionTask'):
        return {'reasoning_effort': 'low', 'activity': 'Drafting session'}
    if state.get('repairTask') or state.get('savedDraftReaudit'):
        return {'reasoning_effort': 'low', 'activity': 'Repairing draft'}
    return {}


def _past_evidence(item):
    """Retain the latest returned session; full earlier pages remain in saved tool results."""
    item = copy.deepcopy(item)
    sessions = item.get('sessions', [])
    if len(sessions) > 1:
        item['earlierReturnedSessionsOmitted'] = len(sessions) - 1
        item['sessions'] = sessions[:1]
        page_end = item.get('nextOffset') if item.get('nextOffset') is not None else item.get('totalSessions')
        if isinstance(page_end, int):
            item['nextOffset'] = page_end - len(sessions) + 1
            item['hasMore'] = True
    if 'relatedMovementHistory' in item:
        item['relatedMovementHistory'] = [_past_evidence(other) for other in item['relatedMovementHistory']]
    return item


def _focus_discovery(state, batches, epoch):
    """Stop discovery only when a completed batch adds no information to this draft."""
    known, repeated, last_facts = set(), False, set()
    for index, facts in sorted(batches.items()):
        if index <= epoch or not facts:
            continue
        repeated = facts <= known
        known.update(facts)
        last_facts = facts
    if repeated and not state.get('planningDecisionNeeded') and not (state.get('lastAudit') or {}).get('passed'):
        blocked = ['search_exercise_library', 'get_exercise_candidates']
        if any(fact[0] == 'evidence' for fact in last_facts):
            blocked.append('get_training_evidence')
        state['discoveryPaused'] = {
            'baseDraftId': state.get('currentDraftId'),
            'blockedTools': blocked,
            'instruction': 'The last discovery batch returned only information already supplied for this draft. '
                'Reuse completedSearches and cached candidates. Repair the indicated existing-session blockers or append the next '
                'session, then audit. Discovery reopens after a changed draft or a new user instruction; '
                'an unchanged audit does not reopen it. Do not poll already returned history pages. '
                'Ask about a genuine unresolved conflict instead of inventing a substitute.'}


def discovery_tool_failure(name, state):
    paused = state.get('discoveryPaused') or {}
    if name in paused.get('blockedTools', []):
        return {'passed': False, 'errors': [{'code': 'lookup_no_progress', 'message': paused['instruction']}],
                'instruction': paused['instruction']}
    return None


def construction_tool_failure(name, arguments, state):
    task = state.get('constructionTask')
    if not isinstance(arguments, dict):
        try:
            arguments = json.loads(arguments)
        except (ValueError, TypeError):
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    if not task:
        if name not in ('prepare_workout_session', 'prepare_workout_sessions', 'draft_workout_sessions'):
            return None
    else:
        if name == 'get_training_evidence':
            needed = set(pending_evidence(state))
            references = arguments.get('definition_ids')
            if (isinstance(references, list) and references and all(isinstance(ref, str) for ref in references)
                    and set(references) <= needed
                    and arguments.get('session_offset', 0) == 0 and arguments.get('session_limit', 1) == 1):
                return None
        allowed = {'ask_user'}
        if task['stage'] != 'retrieve_evidence':
            allowed.add('audit_workout_plan')
        if task['stage'] in ('discover_movements', 'choose_movements'):
            allowed.update({'prepare_workout_session', 'prepare_workout_sessions'})
        if task['stage'] == 'discover_movements':
            allowed.add('search_exercise_library')
        if task['stage'] == 'draft_sessions':
            allowed.add('draft_workout_sessions')
        if name in allowed:
            return None
    return {'passed': False, 'errors': [{'code': 'construction_stage_required',
        'message': 'Follow the current construction stage; do not start another candidate or history exploration loop.'}],
        'instruction': (task or {}).get('instruction', 'Repair or re-audit the saved draft before preparing another session.')}


def _focus_session_preparation(state, preparation, evidence, history_enabled):
    task = state.get('constructionTask')
    if not task or state.get('planningDecisionNeeded'):
        return
    state.setdefault('cachedCandidateIndex', {}).update({ref: {key: entry[key] for key in (
        'name', 'exerciseType', 'equipmentName', 'accessoryNames') if key in entry}
        for ref, entry in state['exerciseCandidates'].items()})
    parallel = state.get('parallelPreparation')
    if parallel:
        preparation = parallel
    references = set(preparation.get('definition_ids', []))
    task['stage'] = 'choose_movements' if state['exerciseCandidates'] or state.get('cachedCandidateIndex') else 'discover_movements'
    if references:
        task['definition_ids'] = preparation['definition_ids']
        missing = sorted((references | set(state.get('selectedDefinitionReferences', []))) - set(evidence)) if history_enabled else []
        task.update(stage='retrieve_evidence' if missing else 'draft_sessions' if parallel else 'submit_session', missingEvidence=missing)
    task['instruction'] = (
        'Follow stage=' + task['stage'] + '. When two or more sessions remain, prefer prepare_workout_sessions to choose their movements and schedule together. '
        'For a single session choose its exact movements with prepare_workout_session, '
        'or submit the bounded session directly if ready. Preparation returns authoritative metadata and Python retrieves '
        'missing history automatically. Once prepared, submit that session; discovery and evidence polling stay closed until '
        'it is audited. Suitability findings are repaired after submission. Never waive a requirement or claim a preview passed. '
        + task['instruction'])
    detailed = (compact_training_evidence(evidence[reference] for reference in references if reference in evidence)
                if references else state['trainingEvidence'])
    state['trainingEvidenceSummary'] = {reference: {key: item[key] for key in (
        'name', 'status', 'totalSessions', 'daysSinceLatestSession', 'loadHeadroom', 'loadSuitabilityConcerns', 'relatedHistoryStatus') if key in item}
        for reference, item in evidence.items() if reference not in detailed}
    state['trainingEvidence'] = detailed
    if references:
        state['exerciseCandidates'] = {key: value for key, value in state['exerciseCandidates'].items() if key in references}
    # The committed next session is the only editable construction unit.
    if state.get('currentDraft'):
        state['currentDraft'] = copy.deepcopy(state['currentDraft'])
        for index, day in enumerate(state['currentDraft']['workouts']):
            state['currentDraft']['workouts'][index] = _session_summary(day, index, state['cachedCandidateIndex'])
    if references:
        for key in ('completedSearches', 'unresolvedSearches', 'cachedCandidateIndex', 'trainingEvidenceSummary'):
            state.pop(key, None)
    for day in (state.get('lastAudit') or {}).get('audit', {}).get('workouts', []):
        day.pop('contributions', None)


def focus_planner_context(messages, original, equipment=None, history_enabled=False):
    from .exercise_library_tools import _selection_entry, search_catalog
    calls = {call['id']: call['function'] for message in messages for call in message.get('tool_calls', [])}
    call_batches = {call['id']: i for i, message in enumerate(messages) for call in message.get('tool_calls', [])}
    result_batches = {}
    requirements = None
    requirements_feedback = {}
    results = []
    for index, message in enumerate(messages):
        function = calls.get(message.get('tool_call_id'))
        if function is None:
            continue
        try:
            payload = json.loads(message.get('content', ''))
        except (ValueError, TypeError):
            payload = {'executionFailure': message.get('content')}
        if not isinstance(payload, dict) or payload.get('skipped'):
            continue
        results.append((index, function, payload))
        result_batches[index] = call_batches.get(message.get('tool_call_id'), index)
        if function['name'] == 'set_workout_requirements':
            requirements_feedback = payload
            if payload.get('requirements'):
                requirements = payload
                requirements_index = index
    if requirements is None:
        return messages + [{'role': 'system', 'content': 'Requirement discussion state (backend source references and checked choices):\n' + json.dumps({
            'sourceMessages': source_message_context(requirement_sources(original)),
            'resolvedDecisions': resolved_decisions(original)}, separators=(',', ':'), ensure_ascii=False)}]

    last_user = max((i for i, m in enumerate(messages) if m['role'] == 'user'), default=-1)
    last_instruction = max((i for i, m in enumerate(messages) if m['role'] == 'user'
                            and m.get('content', '').strip() not in ('/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE')), default=-1)
    decision_index, _ = latest_decision_receipt(messages)
    state = {'requirementsId': requirements['requirementsId'], 'requirements': requirements['requirements'],
             'programmingGuidelines': GUIDELINE_POLICY,
             'requirementsApproved': requirements_approved(original),
             'sourceMessages': source_message_context(requirement_sources(original)),
             'resolvedDecisions': resolved_decisions(original),
             'currentDraft': None, 'lastAudit': None, 'exerciseCandidates': {}, 'trainingEvidence': {},
             'equipmentLoadOptions': {}, 'otherToolResults': {}}
    if requirements.get('restrictionPolicy'):
        state['restrictionPolicy'] = {key: value for key, value in requirements['restrictionPolicy'].items() if key != 'matches'}
    catalog = {f'LIBRARY_{i}': definition for i, definition in enumerate(sorted(
        (equipment or {}).get('exerciseDefinitions', []), key=lambda d: d['id']))}
    fingerprint = library_fingerprint(equipment) if equipment is not None else None
    gear_names = {g['id']: g.get('name', '') for field in ('equipments', 'accessoryEquipments')
                  for g in (equipment or {}).get(field, [])}
    excluded = set(requirements.get('restrictionPolicy', {}).get('excludedDefinitionIds', []))
    restrictions = {key: value for key, value in requirements.get('restrictionPolicy', {}).items()
                    if key not in ('excludeNameTerms', 'exceptNameTerms')}
    _, search_identity = search_catalog(equipment, restrictions)
    completed_searches, discovery_batches = {}, {}
    latest_search = next((p.get('libraryFingerprint') for _, f, p in reversed(results)
                          if f['name'] == 'search_exercise_library' and p.get('results')), None)
    evidence, stale_history, preparation = {}, set(), {}
    evidence_pages = set()
    preparation_index = -1
    latest_audit_index = max((i for i, f, _ in results if f['name'] == 'audit_workout_plan'), default=-1)
    active_alternatives, fresh_references, new_evidence_references = set(), set(), set()
    for index, function, payload in results:
        name = function['name']
        if name != 'audit_workout_plan' and (payload.get('errors') or payload.get('executionFailure')):
            state['otherToolResults'][name] = payload
        else:
            state['otherToolResults'].pop(name, None)
        if name == 'audit_workout_plan':
            state['lastAudit'] = {key: value for key, value in payload.items()
                                  if key not in ('submittedDraft', 'planIndex', 'preview')}
            followup = payload.get('followupReview')
            if followup and followup.get('readOnly') is not True:
                state['lastAudit'].update(passed=False, errors=[{
                    'code': 'review_execution_failed' if followup.get('failure') else 'review_source_changed',
                    'path': '/', 'message': followup.get('failure', followup.get('reason', 'New user instructions need review.')),
                    'repair': ('Report this execution failure; do not change the workout to hide it. Retry only after an explicit user retry or corrected input.'
                               if followup.get('failure') else
                               'Apply the new user instructions or ask about ambiguity; audit a revised preview and require fresh confirmation. Do not export the old plan.')}])
        elif name == 'search_exercise_library':
            if not catalog and payload.get('libraryFingerprint') != latest_search:
                continue
            for query in payload.get('results', []):
                if query.get('error'):
                    state.setdefault('unresolvedSearches', {})[query.get('query', '')] = query
                else:
                    state.get('unresolvedSearches', {}).pop(query.get('query', ''), None)
                for entry in query.get('exercises', []):
                    reference = entry['id']
                    if index > max(latest_audit_index, last_user):
                        active_alternatives.add(reference)
                    if 'name' not in entry:
                        continue
                    if catalog:
                        definition = catalog.get(reference)
                        if not definition or definition['id'] in excluded or any(
                            entry.get(field) != definition.get(field) for field in (
                                'name', 'exerciseType', 'bodyWeightPercentage', 'muscleGroups', 'secondaryMuscleGroups', 'trainingMuscles', 'exerciseCategory')) or (
                            entry.get('equipmentName') != gear_names.get(definition.get('equipmentId')) or
                            set(entry.get('accessoryNames', [])) != {gear_names.get(key, key) for key in definition.get('requiredAccessoryEquipmentIds', [])}):
                            state['staleLibraryResults'] = True
                            continue
                        entry.update(_selection_entry(definition, gear_names, reference))
                    state['exerciseCandidates'][reference] = entry
                if catalog and payload.get('libraryFingerprint') != search_identity:
                    continue
                references = [entry['id'] for entry in query.get('exercises', [])]
                if any(reference not in state['exerciseCandidates'] for reference in references):
                    continue
                filters = query.get('searchFilters', {})
                key = json.dumps([' '.join(re.findall(r'\w+', query.get('query', '').casefold())), filters], sort_keys=True)
                completed_searches[key] = {field: query[field] for field in (
                    'query', 'matchMethod', 'searchFilters', 'error', 'rerankWarning') if field in query}
                completed_searches[key]['definition_ids'] = references
                if not query.get('error') and not query.get('rerankWarning'):
                    facts = {('candidate', reference) for reference in references}
                    if not references:
                        # An empty filtered catalog cannot be repaired by rephrasing the query.
                        facts.add(('empty', json.dumps(filters, sort_keys=True)) if query.get('matchMethod') == 'no_suitable_matches'
                                  else ('empty_query', key))
                    discovery_batches.setdefault(result_batches[index], set()).update(facts)
        elif name == 'get_exercise_candidates':
            if payload.get('libraryFingerprint') != fingerprint:
                state['staleLibraryResults'] = True
                continue
            for entry in payload.get('exercises', []):
                reference = entry.get('id')
                definition = catalog.get(reference)
                if not definition or definition['id'] in excluded:
                    state['staleLibraryResults'] = True
                    continue
                state['exerciseCandidates'][reference] = _selection_entry(definition, gear_names, reference)
                discovery_batches.setdefault(result_batches[index], set()).update({('candidate', reference), ('details', reference)})
                if index > max(latest_audit_index, last_user):
                    active_alternatives.add(reference)
        elif name == 'prepare_workout_session':
            if not payload.get('errors') and payload.get('libraryFingerprint') == fingerprint:
                preparation = payload
                preparation_index = index
                for entry in payload.get('exercises', []):
                    state['exerciseCandidates'][entry['id']] = entry
        elif name == 'get_training_evidence':
            try:
                requested = json.loads(function.get('arguments', '{}')).get('definition_ids', [])
                state.setdefault('attemptedEvidence', []).extend(requested)
            except (ValueError, TypeError):
                requested = []
            state['retryableEvidence'] = [reference for reference in state.get('retryableEvidence', [])
                                          if reference not in requested]
            if (payload.get('errors') or payload.get('executionFailure')) and not payload.get('exercises'):
                state['otherToolResults'][name] = payload
                failed = set(requested)
                if last_user > index:
                    state.setdefault('retryableEvidence', []).extend(failed)
                continue
            if payload.get('staleHistory') or (fingerprint and payload.get('libraryFingerprint') != fingerprint):
                try:
                    stale_history.update(json.loads(function.get('arguments', '{}')).get('definition_ids', []))
                except (ValueError, TypeError):
                    pass
                if last_user > index:
                    state.setdefault('retryableEvidence', []).extend(requested)
                continue
            returned = {item['reference']: item for item in payload.get('exercises', [])}
            arguments = json.loads(function.get('arguments', '{}'))
            facts = {('evidence', reference, arguments.get('session_offset', 0), arguments.get('session_limit', 1))
                     for reference in returned}
            new_references = {fact[1] for fact in facts - evidence_pages}
            evidence_pages.update(facts)
            discovery_batches.setdefault(result_batches[index], set()).update(facts)
            failed = set(requested) - returned.keys()
            evidence.update({reference: item if index > last_user else _past_evidence(item)
                             for reference, item in returned.items()})
            if index > max(latest_audit_index, last_user):
                active_alternatives.update(item['reference'] for item in payload.get('exercises', []))
                fresh_references.update(returned)
                new_evidence_references.update(new_references)
            stale_history.difference_update(item['reference'] for item in payload.get('exercises', []))
            state['equipmentLoadOptions'].update(payload.get('equipmentLoadOptions', {}))
            if failed and last_user > index:
                state.setdefault('retryableEvidence', []).extend(failed)
            if returned:
                state['retryableEvidence'] = [reference for reference in state.get('retryableEvidence', [])
                                              if reference not in returned]
        elif name == 'get_workout_draft':
            previous = state['otherToolResults'].get(name, {})
            if previous.get('baseDraftId') == payload.get('baseDraftId') and payload.get('workouts'):
                payload = {**payload, 'workouts': {**previous.get('workouts', {}), **payload['workouts']}}
            state['otherToolResults'][name] = payload
        elif name not in ('set_workout_requirements', 'record_planning_decisions'):
            state['otherToolResults'][name] = payload
    draft, revision_id = latest_draft_submission(original, equipment)
    if draft:
        state['currentDraft'], state['currentDraftId'] = draft, revision_id
        # A rejected request is not the receipt for the saved draft.
        state['currentDraftAudited'] = any(payload.get('audit') and payload.get('currentDraftId') == revision_id
            for _, function, payload in reversed(results) if function['name'] == 'audit_workout_plan'
            and payload.get('submittedDraft', draft) == draft)
        current_receipt = next((payload for _, function, payload in reversed(results)
                                if function['name'] == 'audit_workout_plan' and payload.get('audit')
                                and payload.get('currentDraftId') == revision_id
                                and payload.get('submittedDraft', draft) == draft), None)
        if current_receipt:
            state['currentDraftAuditErrors'] = current_receipt.get('errors', [])
        state['draftRequiresReaudit'] = draft.get('requirementsId') != requirements['requirementsId']
        state['lastAuditStale'] = latest_audit_index < requirements_index
        from .plan_review import REVIEW_VERSION
        audit = state['lastAudit'] or {}
        review_stale = audit.get('reviewVersion') not in (None, REVIEW_VERSION)
        review_retry = any(isinstance(error, dict) and error.get('code') == 'review_execution_failed'
                           for error in audit.get('errors', []))
        if state['requirementsApproved'] and (state['draftRequiresReaudit'] or state['lastAuditStale']
                or review_stale or review_retry or (audit.get('passed') and audit.get('reviewVersion') != REVIEW_VERSION)):
            state['savedDraftReaudit'] = {'requirementsId': requirements['requirementsId'], 'baseDraftId': revision_id, 'patch': []}
        if (state['requirementsApproved'] and current_receipt and decision_index >= last_instruction
                and current_receipt.get('resolvedDecisions', {}) != state['resolvedDecisions']):
            state['decisionReaudit'] = {'requirementsId': requirements['requirementsId'], 'baseDraftId': revision_id, 'patch': []}
            state['lastAudit']['errors'] = []
            state['lastAudit'].pop('previousReviewFindings', None)
            state['lastAudit']['instruction'] = 'This review predates the current authorized decisions. Re-audit the unchanged draft once before proposing more decisions or repairs.'
            state['otherToolResults'].pop('record_planning_decisions', None)
        # Consume new evidence before sending the planner an obsolete dependency finding.
        evidence_errors = {'training_evidence_required', 'training_load_suitability_unresolved'}
        if (state['requirementsApproved'] and new_evidence_references and not state.get('savedDraftReaudit')
                and any(error.get('code') in evidence_errors for error in audit.get('errors', [])
                        if isinstance(error, dict))):
            selected_refs = {e.get('definition_id') for day in draft.get('workouts', []) for e in day.get('exercises', [])}
            if selected_refs & new_evidence_references:
                state['evidenceReaudit'] = {'requirementsId': requirements['requirementsId'], 'baseDraftId': revision_id, 'patch': []}
    selected = {e.get('definition_id') for day in (draft or {}).get('workouts', []) for e in day.get('exercises', [])}
    if (preparation.get('baseDraftId') != (revision_id if draft else None)
            or preparation.get('requirementsId') != state['requirementsId']
            or (last_user > preparation_index and messages[last_user].get('content', '').strip()
                not in ('/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE'))):
        preparation = {}
    prepared = set(preparation.get('definition_ids', []))
    state['retrievedEvidenceReferences'] = sorted(evidence)
    state['selectedDefinitionReferences'] = sorted(selected - {None})
    for reference in selected | prepared:
        if reference not in state['exerciseCandidates'] and reference in catalog and catalog[reference]['id'] not in excluded:
            state['exerciseCandidates'][reference] = _selection_entry(catalog[reference], gear_names, reference)
    relevant = selected | prepared if preparation else selected | active_alternatives if draft else set(state['exerciseCandidates'])
    latest_history = next((f for _, f, _ in reversed(results) if f['name'] == 'get_training_evidence'), None)
    if latest_history and not draft:
        try:
            relevant.update(json.loads(latest_history.get('arguments', '{}')).get('definition_ids', []))
        except (ValueError, TypeError):
            pass
    state['trainingEvidence'] = compact_training_evidence(value for key, value in evidence.items() if key in relevant)
    if draft:
        state['cachedCandidateIndex'] = {ref: {key: entry[key] for key in (
            'name', 'exerciseType', 'equipmentName', 'accessoryNames') if key in entry}
            for ref, entry in state['exerciseCandidates'].items() if ref not in relevant}
        state['exerciseCandidates'] = {ref: entry for ref, entry in state['exerciseCandidates'].items() if ref in relevant}
    findings = (state.get('lastAudit') or {}).get('errors', []) + (state.get('lastAudit') or {}).get('previousReviewFindings', [])
    new_instruction = (last_user > max(latest_audit_index, requirements_index, decision_index)
        and messages[last_user].get('content', '').strip() not in ('/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE'))
    state['planningDecisionNeeded'] = (new_instruction
        or any(isinstance(finding, dict) and (finding.get('action') == 'clarify'
                  or 'record_planning_decisions' in finding.get('repair', '')) for finding in findings))
    if completed_searches:
        summaries = {}
        for item in completed_searches.values():
            outcome = {key: value for key, value in item.items() if key != 'query'}
            key = json.dumps(outcome, sort_keys=True)
            summaries.setdefault(key, {**outcome, 'queries': []})['queries'].append(item['query'])
        state['completedSearches'] = list(summaries.values())
    revision_start = min((index for index, function, payload in results
                          if function['name'] == 'audit_workout_plan' and payload.get('currentDraftId') == revision_id
                          and payload.get('audit')), default=requirements_index) if draft else requirements_index
    _focus_discovery(state, discovery_batches, max(last_user, revision_start, preparation_index if preparation else -1))
    state['historyWindow'] = ('Reused evidence retains the latest returned session, not a strength maximum. '
        'earlierReturnedSessionsOmitted counts saved sessions omitted from this request. '
        'Fresh lookups retain the requested page in full; retrieve older exact sessions only when needed.')
    for reference, entry in state['exerciseCandidates'].items():
        if reference in state['trainingEvidence']:
            entry.pop('trainingEvidence', None)
    state['staleHistory'] = sorted(stale_history & relevant)
    if state.get('attemptedEvidence'):
        state['attemptedEvidence'] = sorted(set(state['attemptedEvidence']))
    if state.get('retryableEvidence'):
        state['retryableEvidence'] = sorted(set(state['retryableEvidence']))
    parallel_index, parallel = _latest_result(original, 'prepare_workout_sessions')
    if (parallel.get('requirementsId') == state['requirementsId']
            and parallel.get('baseDraftId') == state.get('currentDraftId')
            and parallel.get('libraryFingerprint') == fingerprint
            and parallel.get('sourceMessages') == state['sourceMessages']
            and parallel_index > latest_audit_index and not parallel.get('errors')):
        state['parallelPreparation'] = {key: value for key, value in parallel.items() if key not in ('sourceMessages', 'candidates')}
        state['exerciseCandidates'].update(parallel['candidates'])
        _, proposal = _latest_result(original, 'draft_workout_sessions')
        if (proposal.get('preparationId') == parallel['preparationId']
                and proposal.get('baseDraftId') == state.get('currentDraftId')
                and proposal.get('proposedSubmission')):
            state['parallelSubmission'] = proposal['proposedSubmission']
            state['parallelSubmissionHistoryFingerprint'] = proposal.get('historyFingerprint')
    state['otherToolResults'].pop('prepare_workout_sessions', None)
    state['otherToolResults'].pop('draft_workout_sessions', None)
    _focus_construction(state, new_instruction)
    _focus_repair(state, fresh_references, catalog, equipment, requirements.get('restrictionPolicy', {}), new_evidence_references)
    _focus_session_preparation(state, preparation, evidence, history_enabled)
    state['otherToolResults'].pop('prepare_workout_session', None)
    state['trainingEvidence'], contexts = pool_execution_contexts(state['trainingEvidence'])
    if contexts:
        state['historyExecutionContexts'] = contexts
    # Used to decide whether construction can append another session; lastAudit already carries these findings.
    state.pop('currentDraftAuditErrors', None)
    if not state['requirementsApproved']:
        state = {key: value for key, value in state.items() if key in (
            'requirementsId', 'requirements', 'requirementsApproved', 'sourceMessages', 'resolvedDecisions', 'restrictionPolicy', 'otherToolResults')}
        state['requirementsFeedback'] = {key: requirements_feedback[key] for key in ('passed', 'errors', 'instruction') if key in requirements_feedback}
        state['otherToolResults'] = {name: payload for name, payload in state['otherToolResults'].items()
                                    if name == 'record_planning_decisions'}
        state['savedDraftAvailable'] = bool(draft)
    if draft and state['requirementsApproved']:
        from .allocation import allocation_slots
        state['allocationSlots'] = allocation_slots(draft)
        audit_report = (state.get('lastAudit') or {}).get('audit', {})
        weekly_volume = audit_report.get('weeklyVolume', {})
        weekly_targets = state['requirements'].get('auditTargets', {}).get('weeklyEffectiveSets', {})
        if weekly_targets and weekly_volume:
            state['weeklyTargetBudget'] = {
                muscle: {
                    'alreadyCredited': weekly_volume.get(muscle, {}).get('effective', 0),
                    'remainingMinimum': max(0, bounds['minimum'] - weekly_volume.get(muscle, {}).get('effective', 0)),
                    'remainingMaximum': max(0, bounds['maximum'] - weekly_volume.get(muscle, {}).get('effective', 0)),
                }
                for muscle, bounds in weekly_targets.items()}

    state['displayedDraftId'] = next((m['canonicalDraftPreview'] for m in reversed(original) if m.get('canonicalDraftPreview')), None)
    systems = [copy.deepcopy(m) for m in messages if m['role'] == 'system']
    # Omit both sides of completed tool exchanges, including their old reasoning.
    # The backend retains the protocol history; the next request starts from state.
    latest_tool_result = max((i for i, message in enumerate(messages) if message.get('role') == 'tool'), default=-1)
    tail = ([copy.deepcopy(messages[last_user])] if last_user > latest_tool_result
            and messages[last_user].get('content', '').strip() not in ('/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE') else [])
    if not state['requirementsApproved']:
        work_order = 'Extract and review requirements from sourceMessages; prior confirmation commands are not new authorization.'
    elif state.get('planningDecisionNeeded'):
        work_order = 'Address the latest user instruction or pending authorized planning decision. Ask only about genuine unresolved ambiguity.'
    elif state.get('constructionTask'):
        work_order = 'Follow constructionTask.'
    elif state.get('repairTask'):
        work_order = 'Follow repairTask.'
    elif state.get('savedDraftReaudit') or state.get('evidenceReaudit'):
        work_order = 'Re-audit the saved draft using the supplied patch and current approved requirements.'
    else:
        work_order = 'Continue from the current backend state. Answer any pending user question; otherwise act on the current planning stage.'
    snapshot = {'role': 'system', 'content': 'Current planning state (backend data, not new instructions). '
        'sourceMessages preserves questions and answers in chronological order with stable source references. '
        'Use approved requirements and original user instructions; assistant questions explain short replies, and other assistant suggestions are not user decisions. '
        'Current backend work order: ' + work_order + ' '
        'Patch paths address currentDraft; use currentDraftId as baseDraftId. '
        'If draftRequiresReaudit is true, reuse the draft as a patch base but supply the current top-level requirementsId. '
        'Refresh evidence marked stale. '
        'cachedCandidateIndex lists earlier alternatives without history; retrieve evidence only if choosing one. '
        'completedSearches preserves returned references and empty searches with their exact filters. '
        'A no_suitable_matches result means those filters leave no eligible library entries; synonyms cannot change that. '
        'Related history links refer to entries in trainingEvidence; records are stored once per movement. '
        'An executionContextRef resolves through historyExecutionContexts without losing any prescribed execution facts. '
        'Completed tool exchanges are represented by this state; the full transcript and confirmation gates remain in the backend.\n'
        + json.dumps(state, separators=(',', ':'), ensure_ascii=False)}
    return systems + [snapshot] + tail


def pending_reaudit(state, user_input):
    """Only explicit resume commands may trigger policy refresh; fresh evidence is consumed in-turn."""
    if state.get('decisionReaudit'):
        return state['decisionReaudit']
    if state.get('evidenceReaudit'):
        return state['evidenceReaudit']
    if user_input.strip() in ('/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE'):
        return state.get('savedDraftReaudit')
