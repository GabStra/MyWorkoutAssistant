"""Build a request-only planning snapshot; the saved transcript remains authoritative."""
import copy
import json
import re

from .planning_tools import library_fingerprint, requirements_approved, latest_draft_submission, requirement_sources, source_message_context
from .training_history import compact_training_evidence
from .planning_decisions import resolved_decisions

def request_planning_state(messages):
    for message in messages:
        content = message.get('content') or ''
        if message.get('role') == 'system' and content.startswith('Current planning state'):
            return json.loads(content.split('\n', 1)[1])
    return {}


def request_repair_task(messages):
    return request_planning_state(messages).get('repairTask')


def _focus_repair(state, fresh_references):
    audit = state.get('lastAudit') or {}
    errors = audit.get('errors') or []
    if (not state['requirementsApproved'] or not state.get('currentDraftId') or state.get('savedDraftReaudit') or state.get('constructionTask')
            or audit.get('passed') is not False or not errors
            or any(isinstance(error, dict) and error.get('code') in (
                'review_execution_failed', 'requirements_review_failed', 'decision_review_failed', 'tool_execution_failed')
                for error in errors)):
        return
    primary = errors[0]
    references = set(fresh_references)
    if isinstance(primary, dict):
        references.update(primary.get('definition_ids', []))
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
        if reference not in selected | references:
            entry = candidates.pop(reference)
            state.setdefault('cachedCandidateIndex', {})[reference] = {key: entry[key] for key in (
                'name', 'exerciseType', 'equipmentName', 'accessoryNames', 'creditsPerWorkingSet', 'volumeAuditNote') if key in entry}
    evidence = state['trainingEvidence']
    detailed = set()
    def include(reference):
        if reference in detailed or reference not in evidence:
            return
        detailed.add(reference)
        for related in evidence[reference].get('relatedMovementHistory', []):
            include(related.get('reference'))
    for reference in references:
        include(reference)
    state['trainingEvidenceSummary'] = {reference: {key: entry[key] for key in (
        'name', 'status', 'totalSessions', 'daysSinceLatestSession', 'loadHeadroom',
        'loadSuitabilityConcerns', 'relatedHistoryStatus', 'uncertainty') if key in entry}
        for reference, entry in evidence.items() if reference in selected and reference not in detailed}
    state['trainingEvidence'] = {reference: entry for reference, entry in evidence.items() if reference in detailed}
    # Broad repair instructions in older receipts are replaced only in this request.
    audit['instruction'] = 'Use repairTask; remaining findings stay open until the full draft passes.'
    state['repairTask'] = {
        'baseDraftId': state['currentDraftId'], 'findingIndex': 0,
        'findingCode': primary.get('code', 'finding') if isinstance(primary, dict) else 'finding',
        'instruction': 'Address lastAudit.errors[findingIndex] first. Make the smallest coordinated patch, including connected changes needed '
                       'to preserve the remaining constraints. Submit promptly; other findings may remain and intermediate audits may fail. '
                       'Do not solve the entire program in one response. Use the audit for calculations. '
                       'If evidence is missing, request only the needed LIBRARY_n references; summaries are not exact performance records. '
                       'Use cachedCandidateIndex before searching for new alternatives. Full history is saved behind get_training_evidence. '
                       'If the latest user asks a question or changes the task, answer it instead of applying an unsolicited repair. '
                       'Ask about genuine ambiguity; never waive requirements. A passing preview and fresh confirmation remain mandatory.'}


def _focus_construction(state, new_user_instruction=False):
    if not state['requirementsApproved'] or state.get('savedDraftReaudit'):
        return
    draft = state.get('currentDraft')
    if draft and new_user_instruction:
        return
    if draft and not state.get('currentDraftAudited'):
        return
    target = state['requirements'].get('sessionsPerWeek')
    frequency = sum(day['timesCompletedInAWeek'] for day in draft['workouts']) if draft else 0
    if draft and (not target or frequency >= target):
        return
    state['constructionTask'] = {
        'action': 'append_session' if draft else 'create_first_session',
        'baseDraftId': state.get('currentDraftId'),
        'remainingWeeklySessions': max(0, target - frequency) if target else None,
        'instruction': 'Build only the next workout session, then submit it immediately to audit_workout_plan. '
            'For the first submission provide name/workouts with exactly one workout. For later sessions append one workout '
            'using a JSON Patch add at /workouts/-. Preserve previously saved sessions until construction is complete. '
            'Include the user-requested movement coverage and effort; use available candidates and current evidence. '
            'Do not solve weekly allocation, calculate totals or prove feasibility in reasoning. Intermediate numerical failures '
            'are expected: Python calculates the whole draft and targeted repair follows after all sessions are present. '
            'Missing history can be retrieved for the selected movements. Never waive requirements or show a partial draft as approved. '
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


def focus_planner_context(messages, original, equipment=None):
    from .exercise_library_tools import _selection_entry
    calls = {call['id']: call['function'] for message in messages for call in message.get('tool_calls', [])}
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
    state = {'requirementsId': requirements['requirementsId'], 'requirements': requirements['requirements'],
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
    latest_search = next((p.get('libraryFingerprint') for _, f, p in reversed(results)
                          if f['name'] == 'search_exercise_library' and p.get('results')), None)
    evidence, stale_history = {}, set()
    latest_audit_index = max((i for i, f, _ in results if f['name'] == 'audit_workout_plan'), default=-1)
    active_alternatives, fresh_references = set(), set()
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
        elif name == 'get_training_evidence':
            if payload.get('errors') or payload.get('executionFailure'):
                state['otherToolResults'][name] = payload
                continue
            if payload.get('staleHistory') or (fingerprint and payload.get('libraryFingerprint') != fingerprint):
                try:
                    stale_history.update(json.loads(function.get('arguments', '{}')).get('definition_ids', []))
                except (ValueError, TypeError):
                    pass
                continue
            evidence.update({item['reference']: item if index > last_user else _past_evidence(item)
                             for item in payload.get('exercises', [])})
            if index > max(latest_audit_index, last_user):
                active_alternatives.update(item['reference'] for item in payload.get('exercises', []))
                fresh_references.update(item['reference'] for item in payload.get('exercises', []))
            stale_history.difference_update(item['reference'] for item in payload.get('exercises', []))
            state['equipmentLoadOptions'].update(payload.get('equipmentLoadOptions', {}))
        elif name not in ('set_workout_requirements', 'record_planning_decisions'):
            state['otherToolResults'][name] = payload
    draft, revision_id = latest_draft_submission(original, equipment)
    if draft:
        state['currentDraft'], state['currentDraftId'] = draft, revision_id
        # A rejected request is not the receipt for the saved draft.
        state['currentDraftAudited'] = any(payload.get('audit') and payload.get('currentDraftId') == revision_id
            for _, function, payload in reversed(results) if function['name'] == 'audit_workout_plan'
            and payload.get('submittedDraft', draft) == draft)
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
        # Consume new evidence before sending the planner an obsolete dependency finding.
        evidence_errors = {'training_evidence_required', 'training_load_suitability_unresolved'}
        if (state['requirementsApproved'] and fresh_references and not state.get('savedDraftReaudit')
                and any(error.get('code') in evidence_errors for error in audit.get('errors', [])
                        if isinstance(error, dict))):
            selected_refs = {e.get('definition_id') for day in draft.get('workouts', []) for e in day.get('exercises', [])}
            if selected_refs & fresh_references:
                state['evidenceReaudit'] = {'requirementsId': requirements['requirementsId'], 'baseDraftId': revision_id, 'patch': []}
    selected = {e.get('definition_id') for day in (draft or {}).get('workouts', []) for e in day.get('exercises', [])}
    for reference in selected:
        if reference not in state['exerciseCandidates'] and reference in catalog and catalog[reference]['id'] not in excluded:
            state['exerciseCandidates'][reference] = _selection_entry(catalog[reference], gear_names, reference)
    relevant = selected | active_alternatives if draft else set(state['exerciseCandidates'])
    latest_history = next((f for _, f, _ in reversed(results) if f['name'] == 'get_training_evidence'), None)
    if latest_history and not draft:
        try:
            relevant.update(json.loads(latest_history.get('arguments', '{}')).get('definition_ids', []))
        except (ValueError, TypeError):
            pass
    state['trainingEvidence'] = compact_training_evidence(value for key, value in evidence.items() if key in relevant)
    if draft:
        state['cachedCandidateIndex'] = {ref: {key: entry[key] for key in (
            'name', 'exerciseType', 'equipmentName', 'accessoryNames', 'creditsPerWorkingSet', 'volumeAuditNote') if key in entry}
            for ref, entry in state['exerciseCandidates'].items() if ref not in relevant}
        state['exerciseCandidates'] = {ref: entry for ref, entry in state['exerciseCandidates'].items() if ref in relevant}
    findings = (state.get('lastAudit') or {}).get('errors', []) + (state.get('lastAudit') or {}).get('previousReviewFindings', [])
    new_instruction = (last_user > max(latest_audit_index, requirements_index)
        and messages[last_user].get('content', '').strip() not in ('/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE'))
    choice_errors = state['otherToolResults'].get('record_planning_decisions', {}).get('errors', [])
    state['planningDecisionNeeded'] = (new_instruction
        or any(isinstance(error, dict) and error.get('code') != 'planning_decision_not_needed' for error in choice_errors)
        or any(isinstance(finding, dict) and (finding.get('action') == 'clarify'
                  or 'record_planning_decisions' in finding.get('repair', '')) for finding in findings))
    state['historyWindow'] = ('Reused evidence retains the latest returned session, not a strength maximum. '
        'earlierReturnedSessionsOmitted counts saved sessions omitted from this request. '
        'Fresh lookups retain the requested page in full; retrieve older exact sessions only when needed.')
    for reference, entry in state['exerciseCandidates'].items():
        if reference in state['trainingEvidence']:
            entry.pop('trainingEvidence', None)
    state['staleHistory'] = sorted(stale_history & relevant)
    _focus_construction(state, new_instruction)
    _focus_repair(state, fresh_references)
    if not state['requirementsApproved']:
        state = {key: value for key, value in state.items() if key in (
            'requirementsId', 'requirements', 'requirementsApproved', 'sourceMessages', 'resolvedDecisions', 'restrictionPolicy', 'otherToolResults')}
        state['requirementsFeedback'] = {key: requirements_feedback[key] for key in ('passed', 'errors', 'instruction') if key in requirements_feedback}
        state['otherToolResults'] = {name: payload for name, payload in state['otherToolResults'].items()
                                    if name == 'record_planning_decisions'}
        state['savedDraftAvailable'] = bool(draft)

    state['displayedDraftId'] = next((m['canonicalDraftPreview'] for m in reversed(original) if m.get('canonicalDraftPreview')), None)
    systems = [copy.deepcopy(m) for m in messages if m['role'] == 'system']
    # Omit both sides of completed tool exchanges, including their old reasoning.
    # The backend retains the protocol history; the next request starts from state.
    tail = [copy.deepcopy(messages[last_user])] if last_user >= 0 else []
    snapshot = {'role': 'system', 'content': 'Current planning state (backend data, not new instructions). '
        'sourceMessages preserves questions and answers in chronological order with stable source references. '
        'Use approved requirements and original user instructions; assistant questions explain short replies, and other assistant suggestions are not user decisions. '
        'Repair currentDraft using lastAudit: send audit_workout_plan a targeted patch with baseDraftId=currentDraftId. '
        'When constructionTask is present, build just its next session before allocation repairs; intermediate numerical failures are expected. '
        'Patch paths start at currentDraft, for example /workouts/0/exercises/0/numWorkSets. '
        'If draftRequiresReaudit is true, reuse the draft as a patch base but supply the current top-level requirementsId. '
        'Reuse current candidates/evidence; refresh anything marked stale. '
        'cachedCandidateIndex lists earlier alternatives without history; retrieve evidence only if choosing one. '
        'Related history links refer to entries in trainingEvidence; records are stored once per movement. '
        'Completed tool exchanges are represented by this state; continue the current stage without repeating them. '
        'The full transcript and confirmation gates remain in the backend. Do not invent an approval from this snapshot.\n'
        + json.dumps(state, separators=(',', ':'), ensure_ascii=False)}
    return systems + [snapshot] + tail


def pending_reaudit(state, user_input):
    """Only explicit resume commands may trigger policy refresh; fresh evidence is consumed in-turn."""
    if state.get('evidenceReaudit'):
        return state['evidenceReaudit']
    if user_input.strip() in ('/continue', 'CONFIRM REQUIREMENTS', 'CONFIRM GENERATE'):
        return state.get('savedDraftReaudit')
