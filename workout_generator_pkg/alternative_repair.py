"""One bounded repair pass for a saved, unapproved numerical alternative."""

import copy
import json
import re
import threading

from jsonschema import ValidationError

from .planning_tools import (
    _audit_coverage,
    _fingerprint,
    _latest_result,
    PlanningInputError,
    _validate_draft_schema,
    audit_execution_details,
    audit_execution_rules,
    build_draft_plan,
    compile_coordinated_repair,
    draft_coverage_assignments,
    normalize_work_set_bounds,
    validate_repair_scope,
)
from .generation_audit import audit_workout_package, plan_audit_package
from .restriction_policy import effective_restrictions


def _joint_repair_summary(receipt):
    summary = {key: copy.deepcopy(receipt[key]) for key in (
        'feasible', 'status', 'problemFingerprint', 'recipeCount', 'optionCount',
        'consideredConstraints', 'objectiveProgress', 'elapsedSeconds', 'instruction',
        'preserveSourceSelection', 'selectionPolicyVersion',
        'feasibilityDomainFingerprint',
        'knownPriorInfeasibility', 'knownInfeasibleDomainMatch')
        if key in receipt}
    seen = set()
    examples = []
    for option in receipt.get('rejectedOptions', []):
        identity = (option.get('code'), option.get('message'))
        if identity not in seen:
            seen.add(identity)
            examples.append(copy.deepcopy(option))
            if len(examples) == 3:
                break
    if examples:
        summary['rejectedOptionExamples'] = examples
    return summary


def _alternative_compiler_task(candidate):
    task = copy.deepcopy(candidate)
    task['requirementsId'] = candidate.get('requirementsId', candidate.get('originalRequirementsId'))
    task['baseDraftId'] = candidate['repairCandidateId']
    if isinstance(task.get('rejectedCoordinatedRepair'), dict):
        return task
    previous = task.get('submissionCorrectionEdits')
    if not isinstance(previous, dict):
        return task
    assessment = task.get('findingsAssessment') or {}
    findings = task.get('reviewFindings')
    receipt = {
        'status': 'rejected_before_materialization',
        'requirementsId': candidate['requirementsId'],
        'baseDraftId': candidate['repairCandidateId'],
        'currentDraftId': candidate['repairCandidateId'],
        'assessmentInputHash': assessment.get('inputHash'),
        'submittedEdits': copy.deepcopy(previous),
    }
    if isinstance(findings, list) and assessment.get('inputHash'):
        from .review_assessment import assessment_hash
        receipt['assessmentHash'] = assessment_hash({'inputHash': assessment['inputHash'], 'findings': findings})
    task['rejectedCoordinatedRepair'] = receipt
    return task


def _fresh_binding(candidate, messages, original_requirements, equipment, history, resolved_decisions):
    from .joint_planning import candidate_menu_fingerprint
    from .planning_tools import latest_draft_submission, library_fingerprint
    from .restriction_policy import effective_restrictions

    draft, draft_id = latest_draft_submission(messages, equipment)
    if not isinstance(draft, dict):
        return False
    _, recorded = _latest_result(messages, 'set_workout_requirements')
    return bool(
        recorded.get('requirementsId') == candidate.get('originalRequirementsId')
        and _fingerprint(original_requirements) == candidate.get('originalRequirementsHash')
        and draft_id == candidate.get('sourceDraftId', candidate.get('baseDraftId'))
        and library_fingerprint(equipment) == candidate.get('libraryFingerprint')
        and getattr(history, 'fingerprint', None) == candidate.get('trainingHistoryFingerprint')
        and resolved_decisions == candidate.get('resolvedDecisions', {})
        and effective_restrictions(recorded, equipment) == candidate.get('restrictionPolicy', {})
        and candidate_menu_fingerprint(draft.get('workouts', [])) == candidate.get('sourceMenuFingerprint')
        and candidate_menu_fingerprint(candidate.get('workouts', [])) == candidate.get('candidateMenuFingerprint'))


def _audit_candidate(candidate, workouts, original_record, equipment, messages, history,
                     allow_educated_load_guesses):
    from .planning_tools import _audit_coverage, _validate_draft_schema

    requirements = candidate['requirements']
    arguments = {'requirementsId': candidate['requirementsId'],
        'name': candidate.get('name', 'Workout alternative'), 'workouts': copy.deepcopy(workouts)}
    if isinstance(candidate.get('programGuidance'), str) and candidate['programGuidance'].strip():
        arguments['programGuidance'] = candidate['programGuidance']
    _validate_draft_schema(arguments, requirements.get('workingSetRIR'))
    arguments = normalize_work_set_bounds(arguments, equipment, requirements)
    restriction_policy = effective_restrictions(original_record, equipment)
    plan = build_draft_plan(arguments, equipment, requirements, restriction_policy)
    from .training_history import apply_native_load_calibration_policy
    apply_native_load_calibration_policy(plan, messages, equipment, getattr(history, 'fingerprint', None),
        allow_educated_load_guesses=allow_educated_load_guesses)
    report = audit_workout_package(plan_audit_package(plan, allow_educated_load_guesses), requirements['auditTargets'],
        coverage_by_exercise=draft_coverage_assignments(plan, arguments))
    _audit_coverage(arguments, requirements, report)
    audit_execution_rules(arguments, requirements, report, plan)
    audit_execution_details(arguments, requirements, report)
    if history:
        missing = history.unreviewed(plan, messages, equipment)
        if missing:
            report['errors'].append({'code': 'training_evidence_required', 'definition_ids': missing,
                'message': 'Current training evidence is missing for selected movements.'})
        report['errors'].extend(history.load_suitability_errors(plan, messages, equipment))
    report['issues'] = [item.get('message', item.get('code', 'audit issue')) for item in report.get('errors', [])]
    return arguments, plan, report, restriction_policy


def _compiled_source_occurrences(submission, patch):
    """Replay a validated patch with source tags so solver positions map to the saved candidate."""
    from .json_patching import apply_json_patch

    tagged = copy.deepcopy(submission)
    for workout_index, day in enumerate(tagged['workouts']):
        for exercise_index, item in enumerate(day.get('exercises', [])):
            item['_sourceOccurrence'] = [workout_index, exercise_index]
    tagged_patch = copy.deepcopy(patch)
    for operation in tagged_patch:
        if operation.get('op') in ('add', 'replace'):
            match = re.fullmatch(r'/workouts/\d+/exercises/(?:\d+|-)', operation.get('path', ''))
            if match and isinstance(operation.get('value'), dict):
                operation['value']['_sourceOccurrence'] = None
    patched = apply_json_patch(tagged, tagged_patch)
    return [[copy.deepcopy(item.get('_sourceOccurrence')) for item in day.get('exercises', [])]
            for day in patched['workouts']]


def _patch_operation_references(workouts, patch):
    """Resolve every operation against the source occurrence positions at that patch step."""
    exercise_tokens = [[f'EXERCISE_{sum(len(day["exercises"]) for day in workouts[:workout]) + index}'
                        for index in range(len(day['exercises']))]
                       for workout, day in enumerate(workouts)]
    workout_tokens = [f'WORKOUT_{index}' for index in range(len(workouts))]
    exercise_path = re.compile(r'^/workouts/(\d+)/exercises/(\d+|-)$')
    exercise_item_path = re.compile(r'^/workouts/(\d+)/exercises/(\d+|-)(?:/.*)?$')
    workout_path = re.compile(r'^/workouts/(\d+)$')
    workout_item_path = re.compile(r'^/workouts/(\d+)(?:/.*)?$')
    references = []

    def token_at(path):
        match = exercise_item_path.fullmatch(path or '')
        if match:
            workout = int(match[1])
            index = match[2]
            if workout < len(exercise_tokens):
                return (workout_tokens[workout], None if index == '-' or int(index) >= len(exercise_tokens[workout])
                        else exercise_tokens[workout][int(index)])
        match = workout_item_path.fullmatch(path or '')
        if match and int(match[1]) < len(workout_tokens):
            return workout_tokens[int(match[1])], None
        return None, None

    for operation in patch:
        refs = set()
        exercise_tokens_before = copy.deepcopy(exercise_tokens)
        path = operation.get('path', '')
        workout_ref, exercise_ref = token_at(path)
        if workout_ref:
            refs.add(workout_ref)
        if exercise_ref and not (operation.get('op') == 'move'
                or (operation.get('op') == 'add' and exercise_path.fullmatch(path))):
            refs.add(exercise_ref)
        source_workout, source_exercise = token_at(operation.get('from', ''))
        if source_workout:
            refs.add(source_workout)
        if source_exercise:
            refs.add(source_exercise)
        source_match = exercise_path.fullmatch(operation.get('from', '') or '')
        destination_match = exercise_path.fullmatch(path)
        if operation.get('op') == 'move' and source_match and destination_match:
            source_index, destination_index = int(source_match[1]), int(destination_match[1])
            source_slot = int(source_match[2])
            token = exercise_tokens[source_index].pop(source_slot)
            destination_slot = (len(exercise_tokens[destination_index]) if destination_match[2] == '-'
                                else int(destination_match[2]))
            exercise_tokens[destination_index].insert(destination_slot, token)
        elif destination_match:
            workout, index = int(destination_match[1]), destination_match[2]
            if index == '-':
                slot = len(exercise_tokens[workout])
            else:
                slot = int(index)
            if operation.get('op') == 'remove':
                exercise_tokens[workout].pop(slot)
            elif operation.get('op') == 'add':
                exercise_tokens[workout].insert(slot, None)
            elif operation.get('op') == 'replace' and slot < len(exercise_tokens[workout]):
                exercise_tokens[workout][slot] = None
        if operation.get('op') == 'move':
            for before, after in zip(exercise_tokens_before, exercise_tokens):
                before_positions = {token: index for index, token in enumerate(before) if token is not None}
                after_positions = {token: index for index, token in enumerate(after) if token is not None}
                common_tokens = list(before_positions.keys() & after_positions.keys())
                for left_index, left in enumerate(common_tokens):
                    for right in common_tokens[left_index + 1:]:
                        if ((before_positions[left] < before_positions[right])
                                != (after_positions[left] < after_positions[right])):
                            refs.update((left, right))
        source_workout_match = workout_path.fullmatch(operation.get('from', '') or '')
        destination_workout_match = workout_path.fullmatch(path)
        if operation.get('op') == 'move' and source_workout_match and destination_workout_match:
            source_index, destination_index = int(source_workout_match[1]), int(destination_workout_match[1])
            token, exercises = workout_tokens.pop(source_index), exercise_tokens.pop(source_index)
            workout_tokens.insert(destination_index, token)
            exercise_tokens.insert(destination_index, exercises)
        elif destination_workout_match:
            index = int(destination_workout_match[1])
            if operation.get('op') == 'remove':
                workout_tokens.pop(index)
                exercise_tokens.pop(index)
            elif operation.get('op') == 'add':
                workout_tokens.insert(index, None)
                exercise_tokens.insert(index, [])
            elif operation.get('op') == 'replace' and index < len(workout_tokens):
                workout_tokens[index] = None
                exercise_tokens[index] = []
        references.append(sorted(refs))
    return references


def _append_hypothetical_requirements(messages, candidate, original_record, equipment, history,
                                      allow_educated_load_guesses):
    from .planning_tools import _fingerprint, build_draft_plan, library_fingerprint, AUDIT_VERSION

    record = copy.deepcopy(original_record)
    record.update(requirementsId=candidate['requirementsId'], requirements=copy.deepcopy(candidate['requirements']),
        restrictionPolicy=copy.deepcopy(candidate.get('restrictionPolicy', {})),
        resolvedDecisions=copy.deepcopy(candidate.get('resolvedDecisions', {})),
        proposedAlternative={'originalRequirementsId': candidate['originalRequirementsId'],
            'changes': copy.deepcopy(candidate['changes']), 'requiresUserApproval': True})
    local = copy.deepcopy(messages)
    local.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'alternative_repair_requirements', 'type': 'function',
            'function': {'name': 'set_workout_requirements', 'arguments': json.dumps(candidate['requirements'])}}]},
        {'role': 'tool', 'tool_call_id': 'alternative_repair_requirements', 'content': json.dumps(record)},
    ])
    ledger = _candidate_review_ledger(candidate, messages)
    reviewed_workouts = ledger['workouts'] if ledger else candidate['workouts']
    reviewed_receipt = ledger['review'] if ledger else candidate.get('review', {})
    submitted = {'requirementsId': candidate['requirementsId'], 'name': candidate.get('candidateName', 'Workout alternative'),
        'workouts': copy.deepcopy(reviewed_workouts)}
    if isinstance(candidate.get('programGuidance'), str) and candidate['programGuidance'].strip():
        submitted['programGuidance'] = candidate['programGuidance']
    local.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'alternative_repair_base_review', 'type': 'function',
            'function': {'name': 'audit_workout_plan', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'alternative_repair_base_review', 'content': json.dumps({
            'passed': False, 'requirementsId': candidate['requirementsId'],
            'draftId': 'PROPOSED_' + _fingerprint(submitted), 'currentDraftId': candidate.get('sourceDraftId', candidate.get('baseDraftId')),
            'submittedDraft': submitted, 'audit': copy.deepcopy(candidate['audit']),
            'errors': copy.deepcopy(candidate.get('reviewErrors', [])) if not ledger else [],
            'review': copy.deepcopy(reviewed_receipt),
            'planIndex': build_draft_plan(submitted, equipment, candidate['requirements'], candidate.get('restrictionPolicy', {})),
            'auditVersion': AUDIT_VERSION, 'libraryFingerprint': library_fingerprint(equipment),
            'historyFingerprint': getattr(history, 'fingerprint', None),
            'allowEducatedLoadGuesses': allow_educated_load_guesses,
            'resolvedDecisions': copy.deepcopy(candidate.get('resolvedDecisions', {})),
        })},
    ])
    return local


def _reviewed_proposal(candidate, workouts, audit, review, original_requirements):
    from .conflict_resolution import (_hash, _proposal_core,
        _shortfalls_against_original_requirements)

    proposal = {key: copy.deepcopy(candidate[key]) for key in ('requirementsId', 'baseDraftId',
        'diagnosisVersion', 'reviewVersion', 'originalRequirementsHash', 'libraryFingerprint',
        'trainingHistoryFingerprint', 'changes', 'requirements')}
    proposal['baseDraftId'] = candidate.get('sourceDraftId', proposal['baseDraftId'])
    proposal['originalRequirementsId'] = candidate['originalRequirementsId']
    proposal['programGuidance'] = candidate.get('programGuidance', '')
    if candidate.get('relaxationRanks'):
        proposal['relaxationRanks'] = copy.deepcopy(candidate['relaxationRanks'])
    proposal.update(workouts=copy.deepcopy(workouts), audit=copy.deepcopy(audit),
        independentReview=copy.deepcopy(review),
        shortfallsAgainstOriginalRequirements=_shortfalls_against_original_requirements(
            audit, original_requirements, candidate.get('changes', [])),
        claim='Validated against the proposed requirements; original-target shortfalls are shown. No global optimum is claimed.')
    proposal['proposalId'] = 'ALT_' + _hash(_proposal_core(proposal))[:24]
    return proposal


def _completed_review_ledger(candidate, workouts, review):
    if (not isinstance(review, dict) or review.get('failure') or review.get('inProgress')
            or not isinstance(review.get('version'), int) or isinstance(review.get('version'), bool)
            or not isinstance(review.get('instructionBoundary'), int)
            or not isinstance(review.get('inputHash'), str)
            or not isinstance(review.get('findings'), list)
            or not isinstance(review.get('assessment'), dict)):
        return None
    return {
        'sourceRepairCandidateId': candidate.get('repairCandidateId'),
        'requirementsId': candidate.get('requirementsId'),
        'originalRequirementsId': candidate.get('originalRequirementsId'),
        'originalRequirementsHash': candidate.get('originalRequirementsHash'),
        'sourceDraftId': candidate.get('sourceDraftId', candidate.get('baseDraftId')),
        'libraryFingerprint': candidate.get('libraryFingerprint'),
        'trainingHistoryFingerprint': candidate.get('trainingHistoryFingerprint'),
        'sourceMenuFingerprint': candidate.get('sourceMenuFingerprint'),
        'candidateMenuFingerprint': candidate.get('candidateMenuFingerprint'),
        'resolvedDecisions': copy.deepcopy(candidate.get('resolvedDecisions', {})),
        'workouts': copy.deepcopy(workouts),
        'review': copy.deepcopy(review),
    }


def _latest_materialized_reviewed_candidate(messages, source_candidate, after_index=-1):
    """Return the newest identity-bound revision with a completed review in this lineage."""
    from .joint_planning import candidate_menu_fingerprint

    source_id = source_candidate.get('diagnosisCandidateId') or source_candidate.get('repairCandidateId')
    source_draft_id = source_candidate.get('sourceDraftId', source_candidate.get('baseDraftId'))
    known = {source_candidate.get('repairCandidateId'): copy.deepcopy(source_candidate)}
    latest = None
    call_names = {call.get('id'): call.get('function', {}).get('name')
        for message in messages for call in message.get('tool_calls', [])}
    for index, message in enumerate(messages):
        if index <= after_index or message.get('role') != 'tool' or call_names.get(message.get('tool_call_id')) != 'repair_workout_alternative':
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        if not isinstance(result, dict):
            continue
        snapshot = result.get('candidateSnapshot')
        if (result.get('attemptStatus') != 'repair_review_failed' or not isinstance(snapshot, dict)
                or snapshot.get('diagnosisCandidateId', source_id) != source_id
                or snapshot.get('parentRepairCandidateId') not in known):
            continue
        parent = known[snapshot['parentRepairCandidateId']]
        review = snapshot.get('review')
        audit = snapshot.get('audit')
        review_version = review.get('version') if isinstance(review, dict) else None
        assessment = review.get('assessment') if isinstance(review, dict) else None
        if (any(snapshot.get(key) != source_candidate.get(key) for key in (
                'requirementsId', 'originalRequirementsId', 'originalRequirementsHash',
                'libraryFingerprint', 'trainingHistoryFingerprint', 'sourceMenuFingerprint'))
                or snapshot.get('requirements') != source_candidate.get('requirements')
                or snapshot.get('sourceDraftId', snapshot.get('baseDraftId')) != source_draft_id
                or snapshot.get('resolvedDecisions', {}) != source_candidate.get('resolvedDecisions', {})
                or snapshot.get('candidateMenuFingerprint') != candidate_menu_fingerprint(snapshot.get('workouts', []))
                or snapshot.get('workouts') == parent.get('workouts')
                and snapshot.get('programGuidance', '') == parent.get('programGuidance', '')
                or not isinstance(audit, dict) or audit.get('errors')
                or not isinstance(review_version, int) or isinstance(review_version, bool) or review_version < 1
                or review.get('failure') or review.get('inProgress')
                or not isinstance(review.get('inputHash'), str) or not review.get('inputHash')
                or review.get('inputHash') == parent.get('review', {}).get('inputHash')
                or not isinstance(review.get('findings'), list)
                or not isinstance(assessment, dict)
                or not isinstance(assessment.get('version'), int) or isinstance(assessment.get('version'), bool)
                or snapshot.get('reviewVersion') != review_version):
            continue
        if _completed_review_ledger(snapshot, snapshot.get('workouts'), review) is None:
            continue
        candidate_id = snapshot.get('repairCandidateId')
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in known:
            continue
        known[candidate_id] = copy.deepcopy(snapshot)
        latest = copy.deepcopy(snapshot)
    return latest


def _review_candidate_ancestors(candidate, messages):
    candidate_id = candidate.get('repairCandidateId')
    parents = {candidate_id: candidate.get('parentRepairCandidateId')}
    if messages is not None:
        call_names = {call.get('id'): call.get('function', {}).get('name')
            for message in messages for call in message.get('tool_calls', [])}
        for message in messages:
            if message.get('role') != 'tool' or call_names.get(message.get('tool_call_id')) not in (
                    'propose_workout_alternatives', 'repair_workout_alternative'):
                continue
            try:
                result = json.loads(message.get('content') or '{}')
            except (TypeError, ValueError):
                continue
            if not isinstance(result, dict):
                continue
            sources = list(result.get('alternativeRepairCandidates', []))
            if isinstance(result.get('candidateSnapshot'), dict):
                sources.append(result['candidateSnapshot'])
            for source in sources:
                if isinstance(source, dict) and source.get('repairCandidateId'):
                    parents[source['repairCandidateId']] = source.get('parentRepairCandidateId')

    ancestors = set()
    while candidate_id and candidate_id not in ancestors:
        ancestors.add(candidate_id)
        candidate_id = parents.get(candidate_id)
    return ancestors


def _review_ledger_matches(candidate, ledger, messages=None):
    if not isinstance(ledger, dict):
        return False
    lineage = _review_candidate_ancestors(candidate, messages)
    source_id = ledger.get('sourceRepairCandidateId')
    same_candidate = source_id == candidate.get('repairCandidateId')
    decisions_match = ledger.get('resolvedDecisions', {}) == candidate.get('resolvedDecisions', {})
    if not decisions_match and messages is not None:
        from .planning_decisions import resolved_decisions
        decisions_match = candidate.get('resolvedDecisions', {}) == resolved_decisions(messages)
    return bool(
        source_id in lineage
        and all(ledger.get(key) == candidate.get(key) for key in (
            'requirementsId', 'originalRequirementsId', 'originalRequirementsHash',
            'libraryFingerprint', 'trainingHistoryFingerprint'))
        and ledger.get('sourceDraftId') == candidate.get('sourceDraftId', candidate.get('baseDraftId'))
        and ledger.get('sourceMenuFingerprint') == candidate.get('sourceMenuFingerprint')
        and decisions_match
        and (not same_candidate or (
            ledger.get('candidateMenuFingerprint') == candidate.get('candidateMenuFingerprint')
            and _fingerprint(ledger.get('workouts')) == _fingerprint(candidate.get('workouts'))))
        and isinstance(ledger.get('workouts'), list)
        and _completed_review_ledger(candidate, ledger['workouts'], ledger.get('review')) is not None)


def _candidate_review_ledger(candidate, messages):
    call_names = {call.get('id'): call.get('function', {}).get('name')
        for message in messages for call in message.get('tool_calls', [])}
    lineage = _review_candidate_ancestors(candidate, messages)
    for message in reversed(messages):
        if message.get('role') != 'tool' or call_names.get(message.get('tool_call_id')) not in (
                'propose_workout_alternatives', 'repair_workout_alternative'):
            continue
        try:
            result = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        sources = list(result.get('alternativeRepairCandidates', [])) if isinstance(result, dict) else []
        snapshot = result.get('candidateSnapshot') if isinstance(result, dict) else None
        if isinstance(snapshot, dict):
            sources.append(snapshot)
        for source in sources:
            source_id = source.get('repairCandidateId')
            if source_id not in lineage:
                continue
            prior = _completed_review_ledger(source, source.get('workouts', []), source.get('review'))
            if prior and _review_ledger_matches(candidate, prior, messages):
                return prior
    return _completed_review_ledger(candidate, candidate.get('workouts', []), candidate.get('review'))


def _materialized_review_failure_snapshot(candidate, workouts, audit, review, program_guidance_changed=False):
    """Save a rejected, numerically valid revision as the next repair candidate."""
    from .joint_planning import candidate_menu_fingerprint

    snapshot = {key: copy.deepcopy(value) for key, value in candidate.items()
        if key not in ('currentDraft', 'findingsAssessment', 'reviewFindings', 'errors',
            'submissionCorrectionErrors', 'instruction')}
    source_candidate_id = candidate.get('diagnosisCandidateId', candidate['repairCandidateId'])
    parent_candidate_id = candidate['repairCandidateId']
    source_draft_id = candidate.get('sourceDraftId', candidate.get('baseDraftId'))
    changed = workouts != candidate.get('workouts') or program_guidance_changed
    snapshot.update(workouts=copy.deepcopy(workouts), audit=copy.deepcopy(audit),
        review=copy.deepcopy(review.get('review', {})),
        reviewErrors=copy.deepcopy(review.get('errors', [])),
        candidateMenuFingerprint=candidate_menu_fingerprint(workouts),
        sourceDraftId=source_draft_id, baseDraftId=source_draft_id,
        diagnosisCandidateId=source_candidate_id, parentRepairCandidateId=parent_candidate_id)
    if changed:
        snapshot['repairCandidateId'] = 'REVISION_' + str(int(_fingerprint({
            'diagnosisCandidateId': source_candidate_id,
            'parentRepairCandidateId': parent_candidate_id,
            'workouts': workouts,
            'programGuidance': snapshot.get('programGuidance', ''),
        })[:12], 16))
    receipt = snapshot.get('review')
    if isinstance(receipt, dict) and receipt.get('version') is not None:
        snapshot['reviewVersion'] = receipt['version']
    return snapshot


def refresh_candidate_assessment(candidate, messages, equipment, history, allow_educated_load_guesses,
                                 client, logger=None, progress=None):
    """Refresh only a saved alternative's stale assessment, preserving its candidate identity."""
    from .planning_decisions import resolved_decisions
    from .plan_review import REVIEW_VERSION, review_draft
    from .planning_tools import (AUDIT_VERSION, library_fingerprint, render_draft,
        require_approved_requirements)
    from .review_assessment import VERSION as ASSESSMENT_VERSION, validate_assessment

    candidate = copy.deepcopy(candidate)
    candidate.pop('diagnosisDeadlineUTC', None)
    candidate.pop('repairDeadlineUTC', None)
    require_approved_requirements(messages)
    _, original_record = _latest_result(messages, 'set_workout_requirements')
    if not _fresh_binding(candidate, messages, original_record.get('requirements', {}), equipment, history,
                          resolved_decisions(messages)):
        return {'status': 'unresolved', 'candidate': candidate,
            'reason': 'The saved alternative no longer matches the approved requirements, current draft, library, history, or decisions.'}

    review_candidate = {**candidate,
        'name': candidate.get('candidateName', candidate.get('name', 'Workout alternative'))}
    arguments, plan, audit, restrictions = _audit_candidate(review_candidate, candidate['workouts'], original_record,
        equipment, messages, history, allow_educated_load_guesses)
    if audit.get('errors'):
        return {'status': 'unresolved', 'candidate': candidate,
            'reason': 'The saved alternative no longer passes its current numerical audit.'}
    snapshot = {'passed': True, 'requirementsId': candidate['requirementsId'],
        'draftId': 'PROPOSED_' + _fingerprint(arguments), 'submittedDraft': arguments,
        'currentDraftId': candidate.get('sourceDraftId', candidate['baseDraftId']), 'audit': audit, 'errors': [],
        'planIndex': plan, 'auditVersion': AUDIT_VERSION,
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': getattr(history, 'fingerprint', None),
        'allowEducatedLoadGuesses': allow_educated_load_guesses,
        'resolvedDecisions': copy.deepcopy(candidate.get('resolvedDecisions', {}))}
    snapshot['preview'] = render_draft(plan, candidate['requirements'], audit, restrictions, arguments)
    review_messages = _append_hypothetical_requirements(messages, candidate, original_record,
        equipment, history, allow_educated_load_guesses)
    cancel_event = threading.Event()
    from .cancellation import run_cancellable
    try:
        review = run_cancellable(review_draft, client, snapshot, review_messages,
            equipment, history, logger, progress, cancel_event=cancel_event)
    except TimeoutError as error:
        cancel_event.set()
        return {'status': 'unresolved', 'candidate': candidate,
            'reason': f'The provider request timed out while refreshing the saved alternative review: {error}'}
    receipt = review.get('review', {}) if isinstance(review, dict) else {}
    candidate['review'] = copy.deepcopy(receipt)
    candidate['reviewVersion'] = receipt.get('version')
    candidate['reviewErrors'] = copy.deepcopy(review.get('errors', []))
    candidate['audit'] = copy.deepcopy(audit)
    if receipt.get('failure'):
        return {'status': 'unresolved', 'candidate': candidate,
            'reason': 'The saved alternative review failed at '
                + receipt.get('failureStage', 'independent_review') + ': ' + receipt['failure']}
    try:
        validate_assessment(receipt)
    except (KeyError, TypeError, ValueError):
        return {'status': 'unresolved', 'candidate': candidate,
            'reason': 'The saved alternative assessment refresh did not produce a current validated receipt.'}
    if receipt.get('version') != REVIEW_VERSION or receipt.get('assessment', {}).get('version') != ASSESSMENT_VERSION:
        return {'status': 'unresolved', 'candidate': candidate,
            'reason': 'The saved alternative assessment refresh returned stale review versions.'}

    # Keep the convenience summary fields aligned with the validated nested
    # review so saved candidate envelopes cannot advertise two review states.
    candidate['findingsAssessment'] = copy.deepcopy(receipt['assessment'])
    candidate['reviewFindings'] = copy.deepcopy(receipt['findings'])

    if review.get('passed') is True:
        return {'status': 'proposal_ready', 'candidate': candidate,
            'proposal': _reviewed_proposal(candidate, candidate['workouts'], audit, review,
                original_record.get('requirements', {}))}
    return {'status': 'refreshed', 'candidate': candidate}


def execute_repair(arguments, task, messages, equipment, history, allow_educated_load_guesses,
                   client, logger=None, progress=None):
    """Patch, numerically audit and independently review the saved hypothetical candidate."""
    from .planning_decisions import resolved_decisions
    from .plan_review import review_draft
    from .planning_tools import AUDIT_VERSION, library_fingerprint, render_draft

    candidate = copy.deepcopy(task)
    from .planning_tools import require_approved_requirements
    require_approved_requirements(messages)
    original_index, original_record = _latest_result(messages, 'set_workout_requirements')
    original_requirements = original_record.get('requirements', {})
    decisions = resolved_decisions(messages)
    if (arguments.get('repairCandidateId') != candidate.get('repairCandidateId')
            or arguments.get('originalRequirementsId') != candidate.get('originalRequirementsId')
            or not _fresh_binding(candidate, messages, original_requirements, equipment, history, decisions)):
        raise ValueError('The saved alternative no longer matches the approved requirements, current draft, library, history, or decisions. Diagnose again.')

    from .repair_capabilities import has_unresolved_capabilities
    if has_unresolved_capabilities(candidate.get('findingsAssessment')):
        return {'passed': False, 'outcome': 'unresolved', 'attemptStatus': 'capability_unresolved',
            'repairCandidateId': candidate.get('repairCandidateId'),
            'originalRequirementsId': candidate.get('originalRequirementsId'),
            'baseDraftId': candidate.get('sourceDraftId', candidate.get('baseDraftId')),
            'requirementsId': candidate.get('requirementsId'),
            'requirements': copy.deepcopy(candidate.get('requirements')),
            'candidateSnapshot': copy.deepcopy(candidate),
            'reason': 'The independent assessment requires behavior that no supported repair field can express. Preserve the candidate and surface the capability gap; do not ask the model to repeat this repair.'}

    compile_arguments = {'requirementsId': candidate['requirementsId'],
        'baseDraftId': candidate['repairCandidateId'],
        'addressedFindingIndexes': copy.deepcopy(arguments['addressedFindingIndexes']),
        'edits': copy.deepcopy(arguments['edits'])}
    if 'replaceRejectedRepair' in arguments:
        compile_arguments['replaceRejectedRepair'] = arguments['replaceRejectedRepair']
    submission = {'requirementsId': candidate['requirementsId'], 'name': task['currentDraft']['name'],
        'workouts': copy.deepcopy(candidate['workouts'])}
    original_program_guidance = candidate.get('programGuidance', '')
    if isinstance(original_program_guidance, str) and original_program_guidance.strip():
        submission['programGuidance'] = original_program_guidance
    compiler_task = _alternative_compiler_task(candidate)
    proposal_context = {}
    try:
        compiled, operation_refs = compile_coordinated_repair(
            compile_arguments, compiler_task, submission, proposal_context=proposal_context)
        scoped_task = copy.deepcopy(compiler_task)
        scoped_task['_compiledRepairOperationRefs'] = operation_refs
        validate_repair_scope(compiled, scoped_task, submission)
    except (PlanningInputError, ValidationError) as error:
        from .planning_tools import planning_tool_failure
        failure = planning_tool_failure('repair_workout_alternative', error, compile_arguments)
        active_edits = proposal_context.get('submittedEdits')
        if active_edits is None:
            active_edits = ((compiler_task.get('rejectedCoordinatedRepair') or {}).get('submittedEdits')
                or compile_arguments.get('edits', {}))
        result = {'passed': False, 'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
            'failureStage': 'repair_admission', 'repairCandidateId': candidate['repairCandidateId'],
            'originalRequirementsId': candidate['originalRequirementsId'],
            'requirementsId': candidate['requirementsId'],
            'baseDraftId': candidate.get('sourceDraftId', candidate['baseDraftId']),
            'requirements': copy.deepcopy(candidate.get('requirements')),
            'changes': copy.deepcopy(candidate.get('changes', [])),
            'candidateSnapshot': copy.deepcopy(candidate),
            'findingsAssessment': copy.deepcopy(candidate.get('findingsAssessment')),
            'reviewFindings': copy.deepcopy(candidate.get('reviewFindings', [])),
            'submittedEdits': copy.deepcopy(active_edits),
            'errors': copy.deepcopy(failure.get('errors', [])),
            'reason': 'The alternative repair was rejected before materialization. Its candidate and complete active proposal remain saved; no feasibility or requirement conflict was established.'}
        attempted_edits = compile_arguments.get('edits')
        if attempted_edits != active_edits:
            result['rejectedAttemptEdits'] = copy.deepcopy(attempted_edits)
        if proposal_context.get('replacedSubmittedEdits') is not None:
            result['replacedSubmittedEdits'] = copy.deepcopy(proposal_context['replacedSubmittedEdits'])
        return result
    submitted_edits = copy.deepcopy(proposal_context.get('submittedEdits', compile_arguments['edits']))
    rejected_attempt_edits = (copy.deepcopy(compile_arguments['edits'])
        if compile_arguments['edits'] != submitted_edits else None)
    replaced_submitted_edits = copy.deepcopy(proposal_context.get('replacedSubmittedEdits'))
    scoped_task = copy.deepcopy(task)
    scoped_task['_compiledRepairOperationRefs'] = operation_refs
    from .json_patching import apply_json_patch
    materialized_submission = apply_json_patch(submission, compiled['patch'])
    workouts = materialized_submission['workouts']
    materialized_program_guidance = materialized_submission.get('programGuidance', '')
    program_guidance_changed = materialized_program_guidance != original_program_guidance
    compiled_source_occurrences = _compiled_source_occurrences(submission, compiled['patch'])

    from .joint_planning import candidate_menu_fingerprint, prescription_patch, solve_prescribed_week
    preflight_arguments = {'requirementsId': candidate['requirementsId'],
        'name': candidate.get('candidateName', 'Workout alternative'), 'workouts': copy.deepcopy(workouts)}
    if isinstance(materialized_program_guidance, str) and materialized_program_guidance.strip():
        preflight_arguments['programGuidance'] = materialized_program_guidance
    try:
        _validate_draft_schema(preflight_arguments, candidate['requirements'].get('workingSetRIR'))
        preflight_arguments = normalize_work_set_bounds(preflight_arguments, equipment, candidate['requirements'])
        build_draft_plan(preflight_arguments, equipment, candidate['requirements'],
            candidate.get('restrictionPolicy', {}))
    except PlanningInputError as error:
        result = {'passed': False, 'outcome': 'unresolved', 'attemptStatus': 'repair_failed',
            'repairCandidateId': candidate['repairCandidateId'],
            'originalRequirementsId': candidate['originalRequirementsId'], 'requirementsId': candidate['requirementsId'],
            'baseDraftId': candidate.get('sourceDraftId', candidate['baseDraftId']),
            'requirements': copy.deepcopy(candidate['requirements']), 'changes': copy.deepcopy(candidate['changes']),
            'workouts': copy.deepcopy(workouts), 'candidateMenuFingerprint': candidate['candidateMenuFingerprint'],
            'submittedMenuFingerprint': candidate_menu_fingerprint(workouts),
            'libraryFingerprint': candidate['libraryFingerprint'],
            'trainingHistoryFingerprint': candidate['trainingHistoryFingerprint'],
            'candidateSnapshot': copy.deepcopy(candidate), 'repairOperations': compiled.get('patch', []),
            'findingsAssessment': copy.deepcopy(candidate.get('findingsAssessment')),
            'reviewFindings': copy.deepcopy(candidate.get('reviewFindings', [])),
            'operationReferences': operation_refs, 'submittedEdits': submitted_edits,
            'errors': copy.deepcopy(error.errors or [{'code': error.code, 'path': error.path,
                'message': str(error), 'repair': error.repair}]),
            'reason': 'The submitted repair has invalid executable fields and cannot enter joint solving. Correct the listed fields; no feasibility or requirement conflict was established.'}
        if rejected_attempt_edits is not None:
            result['rejectedAttemptEdits'] = rejected_attempt_edits
        if replaced_submitted_edits is not None:
            result['replacedSubmittedEdits'] = replaced_submitted_edits
        return result
    joint = solve_prescribed_week(workouts, candidate['requirements'], equipment, candidate.get('restrictionPolicy', {}),
        allow_educated_load_guesses=allow_educated_load_guesses, preserve_source_selection=True,
        training_history=history, messages=messages)
    result = {'passed': False, 'repairCandidateId': candidate['repairCandidateId'],
        'originalRequirementsId': candidate['originalRequirementsId'], 'requirementsId': candidate['requirementsId'],
        'baseDraftId': candidate.get('sourceDraftId', candidate['baseDraftId']), 'requirements': copy.deepcopy(candidate['requirements']),
        'changes': copy.deepcopy(candidate['changes']), 'workouts': copy.deepcopy(workouts),
        'candidateMenuFingerprint': candidate['candidateMenuFingerprint'],
        'submittedMenuFingerprint': candidate_menu_fingerprint(workouts),
        'libraryFingerprint': candidate['libraryFingerprint'],
        'trainingHistoryFingerprint': candidate['trainingHistoryFingerprint'],
        'candidateSnapshot': copy.deepcopy(candidate), 'jointSolve': _joint_repair_summary(joint),
        'findingsAssessment': copy.deepcopy(candidate.get('findingsAssessment')),
        'reviewFindings': copy.deepcopy(candidate.get('reviewFindings', [])),
        'repairOperations': compiled.get('patch', []), 'operationReferences': operation_refs,
        'submittedEdits': submitted_edits}
    if rejected_attempt_edits is not None:
        result['rejectedAttemptEdits'] = rejected_attempt_edits
    if replaced_submitted_edits is not None:
        result['replacedSubmittedEdits'] = replaced_submitted_edits
    if not joint.get('feasible'):
        has_rejected_options = bool(joint.get('rejectedOptions'))
        proven_infeasible = joint.get('status') == 'infeasible' and not has_rejected_options
        incomplete_menu = joint.get('status') == 'infeasible' and has_rejected_options
        rejected_messages = list(dict.fromkeys(option.get('message', option.get('code', 'invalid recipe'))
            for option in joint.get('rejectedOptions', [])))[:3]
        solver_message = ('The solver excluded invalid supplied recipes: ' + '; '.join(rejected_messages)
            + '. Correct these options before interpreting the remaining-menu infeasibility.'
            if incomplete_menu else joint.get('instruction', 'The joint repair solver did not establish feasibility.'))
        result.update(outcome='unresolved', attemptStatus=('repair_menu_infeasible' if proven_infeasible
            else 'joint_repair_unresolved'), errors=[{'code': 'joint_menu_infeasible' if proven_infeasible
            else 'joint_menu_incomplete' if incomplete_menu else 'joint_repair_unresolved',
            'message': solver_message}],
            reason=('No combination in this supplied repair menu satisfies the approved hypothetical requirements. Add or correct substantive prescription or movement options; this does not prove the requirements themselves impossible.'
                if proven_infeasible else 'The bounded joint repair solve did not establish feasibility or infeasibility. Preserve the requirements and candidate evidence; do not claim a conflict.'
                if not incomplete_menu else 'The solver rejected some supplied recipe options, so the complete menu was not validated. Correct the rejected options before interpreting the remaining-menu infeasibility; no requirement conflict was established.'))
        return result

    solved_workouts = joint['sessions']
    result.update(workouts=copy.deepcopy(solved_workouts),
        solvedMenuFingerprint=candidate_menu_fingerprint(solved_workouts))
    # Validate assessed coverage against the final solver output. The solver may
    # reallocate or remove an edit, so the submitted operation references alone
    # cannot prove that the final candidate still addresses each review group.
    solver_lineage = joint.get('occurrenceLineage')
    if (not isinstance(solver_lineage, list) or len(solver_lineage) != len(compiled_source_occurrences)
            or any(not isinstance(day, list) or len(day) != len(solved_workouts[index]['exercises'])
                   for index, day in enumerate(solver_lineage))):
        result.update(passed=False, outcome='unresolved', attemptStatus='joint_repair_unresolved',
            failureStage='solver_lineage', errors=[{'code': 'missing_occurrence_lineage',
                'message': 'The joint solver did not return a complete source-occurrence map.'}],
            reason='The joint solver produced a candidate without complete source-occurrence lineage. Preserve the solver receipt and solved candidate; this internal provenance failure cannot be corrected by changing the repair edits.')
        return result
    final_lineage = []
    for day_lineage, source_positions in zip(solver_lineage, compiled_source_occurrences):
        mapped = []
        for source in day_lineage:
            if source is None:
                mapped.append(None)
                continue
            if (not isinstance(source, (list, tuple)) or len(source) != 2
                    or any(type(value) is not int or value < 0 for value in source)):
                result.update(passed=False, outcome='unresolved', attemptStatus='joint_repair_unresolved',
                    failureStage='solver_lineage', errors=[{'code': 'invalid_occurrence_lineage',
                        'message': 'The joint solver returned an invalid source-occurrence reference.'}],
                    reason='The joint solver returned invalid source-occurrence lineage. Preserve the solver receipt and solved candidate; this internal provenance failure cannot be corrected by changing the repair edits.')
                return result
            source_workout, source_exercise = source
            if (source_workout >= len(compiled_source_occurrences)
                    or source_exercise >= len(compiled_source_occurrences[source_workout])):
                result.update(passed=False, outcome='unresolved', attemptStatus='joint_repair_unresolved',
                    failureStage='solver_lineage', errors=[{'code': 'invalid_occurrence_lineage',
                        'message': 'The joint solver referenced an occurrence outside its submitted source.'}],
                    reason='The joint solver referenced missing source-occurrence lineage. Preserve the solver receipt and solved candidate; this internal provenance failure cannot be corrected by changing the repair edits.')
                return result
            mapped.append(copy.deepcopy(compiled_source_occurrences[source_workout][source_exercise]))
        final_lineage.append(mapped)
    try:
        final_patch = prescription_patch(candidate['workouts'], solved_workouts, final_lineage)
    except ValueError as error:
        result.update(outcome='unresolved', attemptStatus='joint_repair_unresolved', failureStage='solver_lineage',
            errors=[{'code': 'invalid_occurrence_lineage', 'message': str(error)}],
            reason='The solver candidate could not be bound to unique source occurrences. Preserve the solver receipt and solved candidate; this internal provenance failure cannot be corrected by changing the repair edits.')
        return result
    if program_guidance_changed:
        final_patch.append({'op': 'replace' if original_program_guidance else 'add',
            'path': '/programGuidance', 'value': materialized_program_guidance})
    final_scope_task = copy.deepcopy(candidate)
    final_scope_task['_compiledRepairOperationRefs'] = _patch_operation_references(candidate['workouts'], final_patch)
    final_scope_draft = {'workouts': candidate['workouts']}
    if isinstance(original_program_guidance, str) and original_program_guidance.strip():
        final_scope_draft['programGuidance'] = original_program_guidance
    try:
        validate_repair_scope({'requirementsId': candidate['requirementsId'],
            'baseDraftId': candidate['repairCandidateId'],
            'addressedFindingIndexes': copy.deepcopy(arguments['addressedFindingIndexes']),
            'patch': final_patch}, final_scope_task, final_scope_draft)
    except PlanningInputError as error:
        result.update(passed=False, outcome='unresolved', attemptStatus='repair_failed',
            failureStage='final_repair_scope',
            workouts=copy.deepcopy(solved_workouts),
            solvedMenuFingerprint=candidate_menu_fingerprint(solved_workouts),
            errors=copy.deepcopy(error.errors or [{'code': error.code, 'path': error.path,
                'message': str(error), 'repair': error.repair}]),
            reason='The joint solver produced a candidate, but final repair-scope validation rejected its assessed coverage. The solver receipt and candidate are preserved for diagnosis; the candidate is not approved.')
        return result

    materialized_candidate = copy.deepcopy(candidate)
    if isinstance(materialized_program_guidance, str) and materialized_program_guidance.strip():
        materialized_candidate['programGuidance'] = materialized_program_guidance
    else:
        materialized_candidate.pop('programGuidance', None)
    try:
        audit_arguments, plan, audit, restrictions = _audit_candidate(materialized_candidate, solved_workouts, original_record,
            equipment, messages, history, allow_educated_load_guesses)
    except PlanningInputError as error:
        result.update(passed=False, outcome='unresolved', attemptStatus='repair_failed',
            failureStage='postsolve_audit',
            workouts=copy.deepcopy(solved_workouts),
            solvedMenuFingerprint=candidate_menu_fingerprint(solved_workouts),
            errors=copy.deepcopy(error.errors or [{'code': error.code, 'path': error.path,
                'message': str(error), 'repair': error.repair}]),
            reason='The joint solver produced a candidate, but post-solve audit preparation rejected it. The solver receipt and candidate are preserved for diagnosis; the candidate is not approved.')
        return result
    result.update(passed=not audit.get('errors'), workouts=copy.deepcopy(solved_workouts), audit=audit)
    if audit.get('errors'):
        result.update(passed=False, outcome='unresolved', attemptStatus='repair_failed',
            errors=copy.deepcopy(audit.get('errors', [])),
            reason='The repaired alternative did not pass the full numerical audit; it remains hypothetical and cannot be approved.')
        return result

    snapshot = {'passed': True, 'requirementsId': candidate['requirementsId'],
        'draftId': 'ALT_DRAFT_' + _fingerprint({'candidate': candidate['repairCandidateId'],
            'workouts': solved_workouts, 'programGuidance': materialized_program_guidance}),
        'currentDraftId': candidate['repairCandidateId'], 'submittedDraft': audit_arguments,
        'audit': audit, 'errors': [], 'planIndex': plan, 'auditVersion': AUDIT_VERSION,
        'libraryFingerprint': library_fingerprint(equipment),
        'historyFingerprint': getattr(history, 'fingerprint', None),
        'allowEducatedLoadGuesses': allow_educated_load_guesses,
        'resolvedDecisions': decisions}
    snapshot['preview'] = render_draft(plan, candidate['requirements'], audit, restrictions, audit_arguments)
    review_messages = _append_hypothetical_requirements(messages, materialized_candidate, original_record,
        equipment, history, allow_educated_load_guesses)
    cancel_event = threading.Event()
    from .cancellation import run_cancellable
    try:
        review = run_cancellable(review_draft, client, snapshot, review_messages,
            equipment, history, logger, progress, cancel_event=cancel_event)
    except TimeoutError as error:
        cancel_event.set()
        result.update(outcome='unresolved', attemptStatus='review_timeout',
            reason=f'The provider request timed out during independent review. The candidate and numerical audit are preserved: {error}')
        return result
    result['independentReview'] = review
    if review.get('passed') is not True:
        assessment = review.get('review', {}).get('assessment', review.get('assessment', {}))
        snapshot = _materialized_review_failure_snapshot(materialized_candidate, solved_workouts, audit, review,
            program_guidance_changed=program_guidance_changed)
        if has_unresolved_capabilities(assessment):
            snapshot['findingsAssessment'] = copy.deepcopy(assessment)
            result.update(passed=False, outcome='unresolved', attemptStatus='capability_unresolved',
                errors=copy.deepcopy(review.get('errors', [])), candidateSnapshot=snapshot,
                reason='Independent review identified behavior that no supported repair field can express. Preserve the candidate and surface the capability gap; do not ask the model to repeat this repair.')
        else:
            result.update(passed=False, outcome='unresolved', attemptStatus='repair_review_failed',
                errors=copy.deepcopy(review.get('errors', [])), candidateSnapshot=snapshot,
                reason='The repaired alternative still has actionable review findings; it remains hypothetical and cannot be approved.')
        return result

    proposal = _reviewed_proposal(materialized_candidate, solved_workouts, audit, review, original_requirements)
    result.update(passed=True, outcome='alternatives_ready', repairStatus='repaired_and_reviewed', proposal=proposal,
        preview=review['preview'], reason='The alternative passed full numerical audit and a fresh independent review. It still requires explicit user approval.')
    return result
