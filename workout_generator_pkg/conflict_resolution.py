"""Bounded conflict diagnosis and approval-bound workout alternatives."""

import copy
import hashlib
import json
import math
import time

from .requirement_accounting import (has_unresolved_numeric_relaxation, pointer,
    relaxation_paths, relaxation_rank_by_path)

CONFLICT_RESOLUTION_VERSION = 4


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _set_pointer(document, path, value):
    parent, _, key = path.rpartition('/')
    target = pointer(document, parent or '/')
    key = key.replace('~1', '/').replace('~0', '~')
    if isinstance(target, list):
        target[int(key)] = value
    else:
        target[key] = value


def _lowered(requirements, paths, ratio):
    result = copy.deepcopy(requirements)
    changes = []
    for path in paths:
        current = pointer(requirements, path)
        if path.endswith('/maximumSessionSeconds'):
            _set_pointer(result, path, None)
            changes.append({'path': path, 'from': current, 'temporarilyRemoved': True})
            continue
        if path.endswith('/maximum'):
            # Volume-bound maxima are supported through 100 by the requirements schema.
            value = 100
            if value > current:
                _set_pointer(result, path, value)
                changes.append({'path': path, 'from': current, 'to': value,
                                'temporarilyRaised': True})
            continue
        # Effective-set requirements can be fractional because secondary muscles count half.
        value = max(0, math.floor(current * ratio * 2) / 2)
        if value < current:
            _set_pointer(result, path, value)
            changes.append({'path': path, 'from': current, 'to': value})
    return result, changes


def _unchanged_except_relaxations(original, candidate, allowed_paths):
    left, right = copy.deepcopy(original), copy.deepcopy(candidate)
    for path in allowed_paths:
        _set_pointer(left, path, None)
        _set_pointer(right, path, None)
    return left == right


def _outcome(status, scope, **extra):
    return {'outcome': status, 'scope': scope, **extra}


def _conflict_details(receipt, requirements):
    accounted = []
    for item in requirements.get('requirementAccounting', []):
        if item.get('enforcement') != 'constraint':
            continue
        values = []
        for path in item.get('requirementPaths', []):
            try:
                values.append({'path': path, 'approvedValue': copy.deepcopy(pointer(requirements, path))})
            except (KeyError, TypeError, ValueError, IndexError):
                continue
        accounted.append({'instruction': item.get('instruction'),
            'sourceReferences': item.get('sourceReferences', []), 'priority': item.get('priority'),
            'requirementPaths': values})
    return {'solverStatus': receipt.get('status'),
        'solverConsideredConstraints': receipt.get('consideredConstraints', []),
        'instruction': receipt.get('instruction'), 'accountedRequirements': accounted,
        'claimScope': 'The joint solver proved this supplied menu infeasible; this is not a minimal conflicting-requirements core.'}


def _tighten_to_audited_volume(requirements, paths, receipt, original_requirements):
    result = copy.deepcopy(requirements)
    changes = []
    for path in paths:
        if path.endswith('/maximumSessionSeconds'):
            actual = max((row.get('estimatedSeconds', 0) for row in receipt.get('audit', {}).get('workouts', [])), default=0)
            original = pointer(original_requirements, path)
            target = max(original, actual)
            _set_pointer(result, path, target)
            if actual > original:
                changes.append({'path': path, 'from': original, 'to': target, 'basis': 'audited candidate duration'})
            continue
        parts = path.split('/')
        if path.startswith('/auditTargets/weeklyEffectiveSets/'):
            muscle = parts[3]
            actual = receipt.get('audit', {}).get('weeklyVolume', {}).get(muscle, {}).get('effective', 0)
        elif path.startswith('/auditTargets/perSessionEffectiveSets/'):
            muscle = parts[3]
            values = [row.get('volume', {}).get(muscle, {}).get('effective', 0)
                      for row in receipt.get('audit', {}).get('workouts', [])]
            actual = max(values, default=0) if path.endswith('/maximum') else min(values, default=0)
        else:
            continue
        original = pointer(original_requirements, path)
        target = max(original, actual) if path.endswith('/maximum') else min(original, actual)
        _set_pointer(result, path, target)
        if target < original:
            changes.append({'path': path, 'from': original, 'to': target, 'basis': 'audited candidate volume'})
        elif target > original:
            changes.append({'path': path, 'from': original, 'to': target, 'basis': 'audited candidate volume'})
    return result, changes


def _scaled_volume_minima(requirements, paths, ratio):
    result = copy.deepcopy(requirements)
    for path in paths:
        original = pointer(requirements, path)
        _set_pointer(result, path, math.floor(original * ratio * 2) / 2)
    return result


def _review_failure(review):
    if not isinstance(review, dict):
        return {'status': 'not_passed'}
    details = {'status': 'not_passed'}
    if review.get('instruction'):
        details['reason'] = str(review['instruction'])[:1200]
    errors = review.get('errors', [])
    findings = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        finding = {key: copy.deepcopy(item[key]) for key in
                   ('code', 'path', 'message', 'repair', 'evidencePaths', 'reviewScope', 'severity')
                   if key in item}
        if finding:
            findings.append(finding)
    if findings:
        details['findings'] = findings
    assessment = (review.get('review') or {}).get('assessment')
    if isinstance(assessment, dict) and assessment.get('repairPlan'):
        details['repairPlan'] = str(assessment['repairPlan'])[:5000]
    return details


def _proposal_core(proposal):
    core = {key: proposal[key] for key in ('requirementsId', 'baseDraftId', 'originalRequirementsHash',
        'libraryFingerprint', 'trainingHistoryFingerprint', 'changes', 'requirements', 'workouts', 'audit',
        'independentReview', 'diagnosisVersion', 'reviewVersion')}
    core['shortfallsAgainstOriginalRequirements'] = proposal.get('shortfallsAgainstOriginalRequirements', [])
    if isinstance(proposal.get('programGuidance'), str) and proposal['programGuidance'].strip():
        core['programGuidance'] = proposal['programGuidance']
    if proposal.get('allocationConflictFingerprint'):
        core['allocationConflictFingerprint'] = proposal['allocationConflictFingerprint']
    core['searchScope'] = proposal.get('searchScope', 'the supplied exercise menu')
    core['structuralSearchStatus'] = proposal.get('structuralSearchStatus',
        'Structural alternatives may remain unexplored.')
    if 'relaxationRanks' in proposal:
        core['relaxationRanks'] = proposal['relaxationRanks']
    core['claim'] = proposal.get('claim', 'Validated for this supplied menu; no global optimum is claimed.')
    return core


def _shortfalls_against_original_requirements(audit, requirements, changes):
    """Report the exact original numeric targets missed by a validated proposal."""
    shortfalls = []
    weekly = audit.get('weeklyVolume', {})
    sessions = audit.get('workouts', [])
    for change in changes:
        path = change['path']
        actual, required, unit = None, change['from'], 'effective sets'
        parts = path.split('/')
        if path == '/auditTargets/maximumSessionSeconds':
            actual = max((row.get('estimatedSeconds', 0) for row in sessions), default=0)
            unit = 'seconds'
        elif path.startswith('/auditTargets/weeklyEffectiveSets/'):
            muscle = parts[3]
            actual = weekly.get(muscle, {}).get('effective', 0)
        elif path.startswith('/auditTargets/perSessionEffectiveSets/'):
            muscle = parts[3]
            values = [row.get('volume', {}).get(muscle, {}).get('effective', 0)
                      for row in sessions]
            actual = (max(values, default=0) if path.endswith('/maximum')
                      else min(values, default=0))
            unit = 'effective sets per session'
        if actual is None:
            continue
        is_maximum = path.endswith('/maximum') or path.endswith('/maximumSessionSeconds')
        amount = max(0, actual - required) if is_maximum else max(0, required - actual)
        if amount <= 0:
            continue
        accounting = next((item for item in requirements.get('requirementAccounting', [])
            if any(path == source_path or path.startswith(source_path.rstrip('/') + '/')
                   or source_path.startswith(path.rstrip('/') + '/')
                   for source_path in item.get('requirementPaths', []))), None)
        shortfalls.append({'path': path, 'required': required, 'actual': actual,
            'shortfall': amount, 'unit': unit,
            **({'priority': accounting['priority']} if accounting else {}),
            **({'instruction': accounting['instruction']} if accounting else {}),
            **({'sourceReferences': copy.deepcopy(accounting['sourceReferences'])} if accounting else {})})
    return shortfalls


def _ranked_change_paths(changes, ranks):
    result = {}
    for change in changes:
        changed_path = change['path']
        for ranked_path, rank in ranks.items():
            if changed_path == ranked_path or changed_path.startswith(ranked_path.rstrip('/') + '/'):
                result[changed_path] = rank
                break
    return result


def _candidate_menu_expansion_is_verified(messages, audit, workouts, requirements_id,
                                          library_hash, resolved_decisions, requirements=None):
    """Require the persisted one-shot menu expansion before relaxing targets."""
    from .planner_context import _candidate_menu_expansion_status

    calls = {call.get('id'): call.get('function', {})
        for message in messages if isinstance(message, dict)
        for call in message.get('tool_calls', [])
        if call.get('function', {}).get('name') == 'audit_workout_plan'}
    results = []
    for index, message in enumerate(messages):
        function = calls.get(message.get('tool_call_id'))
        if message.get('role') != 'tool' or function is None:
            continue
        try:
            payload = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            results.append((index, function, payload))
    status, _ = _candidate_menu_expansion_status(results, audit, workouts,
        requirements_id, library_hash, resolved_decisions, messages, requirements)
    return status == 'expanded'


def render_alternative_preview(proposal):
    """Render the exact reviewed candidate whose content is covered by proposalId."""
    preview = proposal.get('independentReview', {}).get('preview')
    if not isinstance(preview, str) or not preview.strip():
        raise ValueError('A complete reviewed workout preview is required before presenting an alternative.')
    lines = ['Workout alternative ' + proposal['proposalId'], 'Original requirements remain active until you approve this proposal.', '',
        'Search scope: ' + proposal.get('searchScope', 'this supplied exercise menu') + '.',
        proposal.get('structuralSearchStatus', 'Structural alternatives may remain unexplored.'), '',
        'Program guidance (manual reference):',
        (proposal.get('programGuidance') or '(none provided)'), '',
        *[f"- {change['path']}: {change['from']} → {change['to']}" for change in proposal['changes']],
        '', 'Shortfalls against the original requirements:']
    shortfalls = proposal.get('shortfallsAgainstOriginalRequirements', [])
    if shortfalls:
        lines.extend(f"- {item.get('instruction', item['path'])}: {item['actual']} vs {item['required']} {item['unit']} (shortfall {item['shortfall']})"
                     for item in shortfalls)
    else:
        lines.append('- None on the changed numeric targets.')
    lines.extend(['', preview.strip(), '', proposal.get('claim',
        'Validated against the proposed requirements; original-target shortfalls are shown above. No global optimum is claimed.')])
    lines.extend(['Estimated session duration is a planning estimate.',
        'Approve only this alternative: APPROVE ALTERNATIVE ' + proposal['proposalId']])
    return '\n'.join(lines)


def diagnose_conflict_and_propose(*, requirements_id, base_draft_id, workouts=None, requirements,
                                  equipment, restriction_policy, review_candidate, training_history=None,
                                  messages=None, allow_educated_load_guesses=True,
                                  max_solver_attempts=8,
                                  existing_conflict=None, allocation_conflict=None):
    """Validate menu-scoped alternatives within explicitly negotiable numeric bounds.

    `review_candidate(sessions, requirements, solver_receipt)` must run the ordinary
    independent semantic review and return a receipt with `passed: true` to validate
    a proposal. If structural menu search is unresolved, alternatives remain scoped
    to the supplied menu and make no global-best or impossibility claim. Provider timeout
    or absent/failed review is unresolved, never a conflict. Search is bounded by the
    solver-attempt count, not elapsed wall-clock time.
    """
    from .joint_planning import joint_problem_fingerprint, solve_prescribed_week
    from .planning_tools import _latest_result, library_fingerprint
    from .cancellation import run_cancellable

    started = time.monotonic()

    def diagnosed_outcome(status, scope, **details):
        result = _outcome(status, scope, **details)
        result['diagnosisVersion'] = CONFLICT_RESOLUTION_VERSION
        return result

    if workouts is None:
        _, current_draft = _latest_result(messages or [], 'audit_workout_plan')
        if current_draft.get('currentDraftId', current_draft.get('draftId')) != base_draft_id:
            return diagnosed_outcome('unresolved', 'saved workout draft', reason='baseDraftId does not identify the current saved draft.')
        workouts = (current_draft.get('submittedDraft') or {}).get('workouts')
        if not workouts:
            return diagnosed_outcome('unresolved', 'saved workout draft', reason='The current audit receipt has no submitted workout menu.')

    # A fresh, exact audit proving a mandatory role is absent cannot be repaired
    # by changing numeric bounds. Keep this diagnosis unresolved until the menu
    # itself has been expanded and re-audited.
    _, current_audit = _latest_result(messages or [], 'audit_workout_plan')
    audited_workouts = (current_audit.get('submittedDraft') or {}).get('workouts')
    source_program_guidance = (current_audit.get('submittedDraft') or {}).get('programGuidance', '')
    if not isinstance(source_program_guidance, str):
        return diagnosed_outcome('unresolved', 'saved workout draft',
            reason='The current draft has invalid program guidance; refresh the saved draft before diagnosing alternatives.')
    if (current_audit.get('requirementsId') == requirements_id
            and current_audit.get('currentDraftId', current_audit.get('draftId')) == base_draft_id
            and current_audit.get('passed') is False and audited_workouts == workouts):
        missing_coverage = [copy.deepcopy(error) for error in current_audit.get('errors', [])
            if isinstance(error, dict) and error.get('code') == 'required_coverage_missing']
        if missing_coverage:
            blockers = sorted({error.get('coverageKey', error.get('path', 'required coverage'))
                               for error in missing_coverage})
            return diagnosed_outcome('unresolved', 'current validated candidate menu',
                reason='The current audit proves required coverage is missing from this menu. Numeric relaxations cannot add a missing movement; expand and re-audit the candidate menu before diagnosing negotiable targets.',
                blockerCoverageKeys=blockers, blockers=missing_coverage,
                nextStep='expand_candidate_menu')

    attempts = []
    paths = relaxation_paths(requirements)
    original = copy.deepcopy(requirements)
    original_hash = _hash(original)
    library_hash = library_fingerprint(equipment)
    history_hash = getattr(training_history, 'fingerprint', None)
    allocation_conflict_fingerprint = None
    if allocation_conflict is not None:
        if not isinstance(allocation_conflict, dict):
            return diagnosed_outcome('unresolved', 'saved count-allocation conflict',
                reason='The count-allocation conflict receipt is invalid.')
        from .joint_planning import candidate_menu_fingerprint
        from .allocation import allocation_input_fingerprint
        _, binding_audit = _latest_result(messages or [], 'audit_workout_plan')
        resolved_decisions = binding_audit.get('resolvedDecisions', {})
        current_menu_fingerprint = candidate_menu_fingerprint(workouts)
        allocation_conflict_fingerprint = allocation_conflict.get('conflictFingerprint')
        expected_allocation_fingerprint = allocation_input_fingerprint({'workouts': workouts},
            requirements_id, equipment, history_fingerprint=history_hash,
            resolved_decisions=resolved_decisions,
            allow_educated_load_guesses=allow_educated_load_guesses, requirements=original)
        if (allocation_conflict.get('status') != 'infeasible'
                or allocation_conflict.get('scope') != 'count_allocation_for_current_draft'
                or allocation_conflict.get('requirementsId') != requirements_id
                or allocation_conflict.get('baseDraftId') != base_draft_id
                or not isinstance(allocation_conflict_fingerprint, str)
                or not allocation_conflict_fingerprint
                or allocation_conflict.get('libraryFingerprint') != library_hash
                or allocation_conflict.get('historyFingerprint') != history_hash
                or allocation_conflict.get('allowEducatedLoadGuesses') != allow_educated_load_guesses
                or allocation_conflict.get('resolvedDecisions', {}) != resolved_decisions
                or allocation_conflict.get('inputFingerprint') != expected_allocation_fingerprint
                or allocation_conflict_fingerprint != expected_allocation_fingerprint
                or (allocation_conflict.get('menuFingerprint') is not None
                    and allocation_conflict.get('menuFingerprint') != current_menu_fingerprint)):
            return diagnosed_outcome('unresolved', 'saved count-allocation conflict',
                reason='The count-allocation conflict receipt is stale or does not match the current requirements, draft, library, history, or decisions.')

    def solver_attempt_count():
        return sum(not attempt.get('reused') for attempt in attempts)

    def solve(requirement_set, label):
        if solver_attempt_count() >= max_solver_attempts:
            return None
        receipt = solve_prescribed_week(workouts, requirement_set, equipment, restriction_policy,
            allow_educated_load_guesses=allow_educated_load_guesses,
            training_history=training_history, messages=messages)
        attempts.append({'scenario': label, 'status': receipt.get('status'),
                         'elapsedSeconds': receipt.get('elapsedSeconds')})
        return receipt

    def review_candidate_safely(sessions, requirement_set, receipt):
        try:
            return run_cancellable(review_candidate, sessions, requirement_set, receipt), None, None
        except TimeoutError as error:
            return None, 'timeout', str(error)[:500]
        except Exception as error:
            return None, 'error', f'{type(error).__name__}: {error}'[:500]

    expected_problem_fingerprint = joint_problem_fingerprint(
        workouts, original, equipment, training_history, messages,
        restriction_policy=restriction_policy, existing=None,
        allow_educated_load_guesses=allow_educated_load_guesses)
    if (isinstance(existing_conflict, dict)
            and existing_conflict.get('status') == 'infeasible'
            and existing_conflict.get('problemFingerprint') == expected_problem_fingerprint):
        first = existing_conflict
        attempts.append({'scenario': 'approved_requirements', 'status': 'infeasible', 'reused': True})
    else:
        first = solve(original, 'approved_requirements')
    if first is None:
        return diagnosed_outcome('unresolved', 'supplied prescription menu', reason='The configured solver-attempt limit prevented evaluation of the original request.', attempts=attempts)
    if first.get('feasible'):
        review, review_status, review_error = review_candidate_safely(first['sessions'], original, first)
        if review_status:
            attempts.append({'scenario': 'independent_review', 'review': review_status,
                             'reason': review_error})
            return diagnosed_outcome('unresolved', 'supplied prescription menu',
                reason='Independent review did not complete; numerical feasibility is not an accepted plan.',
                attempts=attempts)
        if isinstance(review, dict) and review.get('passed') is True:
            if not isinstance(review.get('preview'), str) or not review['preview'].strip():
                return diagnosed_outcome('candidate_feasible_pending_review', 'supplied prescription menu',
                    reason='Independent review passed, but the exact reviewed plan preview is missing.', attempts=attempts)
            return diagnosed_outcome('verified_feasible', 'supplied prescription menu',
                reason='The candidate passed production audit and independent review.', attempts=attempts)
        return diagnosed_outcome('candidate_feasible_pending_review', 'supplied prescription menu',
            reason='Numerical feasibility is established; independent review is still required.', attempts=attempts)
    if first.get('status') != 'infeasible':
        return diagnosed_outcome('unresolved', 'supplied prescription menu', reason=first.get('instruction', 'The solver did not prove a conflict.'), attempts=attempts)

    structural_search_verified = False
    if messages is not None:
        _, current_audit = _latest_result(messages, 'audit_workout_plan')
        if current_audit.get('currentDraftId', current_audit.get('draftId')) != base_draft_id:
            return diagnosed_outcome('unresolved', 'supplied prescription menu',
                reason='The current saved draft does not match the candidate being diagnosed.',
                attempts=attempts)
        structural_search_verified = _candidate_menu_expansion_is_verified(messages, current_audit, workouts,
            requirements_id, library_hash, current_audit.get('resolvedDecisions', {}), requirements)
    structural_status = ('A bounded structural menu search was validated; this is still not a global optimum.'
        if structural_search_verified else
        'Structural alternatives remain unresolved; this is a validated option for the supplied menu, not a global best or impossibility claim.')

    if has_unresolved_numeric_relaxation(requirements):
        return diagnosed_outcome('unresolved', 'approved negotiable numeric requirements',
            reason='A negotiable numeric constraint has no explicit supported relaxation direction. Refresh requirement accounting from the source instruction before proposing alternatives or claiming conflict.',
            attempts=attempts)

    numeric_candidates = []
    unexplored_axes = []
    if paths:
        volume_minima = [path for path in paths if path.startswith(
            ('/auditTargets/weeklyEffectiveSets/', '/auditTargets/perSessionEffectiveSets/'))
            and path.endswith('/minimum')]
        duration_paths = [path for path in paths if path.endswith('/maximumSessionSeconds')]
        volume_maxima = [path for path in paths if path.endswith('/maximum')]
        # When volume minima are the only negotiable dimensions, find the
        # highest common feasible floor instead of asking a feasibility solver
        # to choose arbitrarily after dropping every minimum to zero.
        rank_by_path = relaxation_rank_by_path(original)
        if (not rank_by_path and volume_minima and not duration_paths and not volume_maxima
                and len(volume_minima) == len(paths)):
            low, high = 0.0, 1.0
            best_requirements = _scaled_volume_minima(original, volume_minima, low)
            best_receipt = solve(best_requirements, 'relax:all_volume_minima:zero_floor')
            if best_receipt is not None and best_receipt.get('feasible'):
                for step in range(6):
                    if solver_attempt_count() >= max_solver_attempts:
                        break
                    ratio = (low + high) / 2
                    trial = _scaled_volume_minima(original, volume_minima, ratio)
                    receipt = solve(trial, f'relax:all_volume_minima:common_floor_{step + 1}')
                    if receipt is None:
                        break
                    if receipt.get('status') == 'infeasible':
                        high = ratio
                    elif receipt.get('feasible'):
                        low, best_requirements, best_receipt = ratio, trial, receipt
                    else:
                        break
                tightened, changes = _tighten_to_audited_volume(
                    best_requirements, volume_minima, best_receipt, original)
                if (changes and _unchanged_except_relaxations(original, tightened, volume_minima)
                        and isinstance(best_receipt.get('audit'), dict)
                        and not best_receipt['audit'].get('errors')):
                    numeric_candidates.append({'requirementsId': requirements_id, 'baseDraftId': base_draft_id,
                        'programGuidance': source_program_guidance,
                        'originalRequirementsHash': original_hash, 'libraryFingerprint': library_hash,
                        'trainingHistoryFingerprint': history_hash, 'changes': changes,
                        'requirements': tightened, 'workouts': best_receipt['sessions'],
                        'audit': best_receipt['audit'],
                        'search': {'method': 'common_volume_floor_bisection', 'ratio': low,
                                   'rounds': sum(1 for attempt in attempts
                                       if attempt['scenario'].startswith('relax:all_volume_minima:common_floor_'))}})
        scenarios = []
        volume_paths = [path for path in paths if path not in duration_paths]

        # Explicit source ranks form ordered tiers. A higher tier stays fixed
        # until every lower tier is proven infeasible. Unranked paths remain
        # separate trade-offs; their order below is only a search order.
        if rank_by_path:
            scenario_groups = []
            ranks = sorted(set(rank_by_path.values()))
            for rank in ranks:
                cumulative_paths = [path for path in paths if rank_by_path.get(path) <= rank]
                rank_paths = [path for path in paths if rank_by_path.get(path) == rank]
                scenario_groups.append((f'relax:rank:{rank}', cumulative_paths))
                lower_rank_paths = [path for path in paths if rank_by_path.get(path) < rank]
                scenario_groups.extend((f'relax:rank:{rank}:{path}', lower_rank_paths + [path])
                    for path in rank_paths)
            unranked_paths = [path for path in paths if path not in rank_by_path]
            scenario_groups.extend([
                ('relax:unranked:session_duration', [p for p in unranked_paths if p in duration_paths]),
                ('relax:unranked:volume_minima', [p for p in unranked_paths if p in volume_minima]),
                ('relax:unranked:volume_maxima', [p for p in unranked_paths if p in volume_maxima]),
            ])
            scenario_groups.extend((f'relax:unranked:{path}', [path]) for path in unranked_paths)
            scenario_groups = [(label, allowed) for label, allowed in scenario_groups if allowed]
            all_relaxation_scenarios = {label for label, _ in scenario_groups}
        else:
            # Exercise materially different trade-off dimensions before spending
            # the bounded solver-attempt allowance on individual field variants.
            scenario_groups = [
                ('relax:session_duration', duration_paths),
                ('relax:all_volume_minima', volume_minima),
                ('relax:all_volume_maxima', volume_maxima),
                ('relax:all_negotiable_constraints', paths),
            ]
            all_relaxation_scenarios = {label for label, allowed in scenario_groups
                                         if allowed and set(allowed) == set(paths)}
        seen_scenarios = set()
        for label, allowed in scenario_groups:
            if numeric_candidates and volume_minima and set(allowed) == set(volume_minima):
                continue
            if not allowed:
                continue
            modified, changes = _lowered(original, allowed, 0)
            key = json.dumps(modified, sort_keys=True, separators=(',', ':'))
            if changes and key not in seen_scenarios:
                scenarios.append((label, modified, changes, allowed))
                seen_scenarios.add(key)
        for path in paths:
            if rank_by_path and path in rank_by_path:
                continue
            if numeric_candidates and path in volume_minima:
                continue
            modified, changes = _lowered(original, [path], 0)
            key = json.dumps(modified, sort_keys=True, separators=(',', ':'))
            if changes and key not in seen_scenarios:
                scenarios.append((f'relax:{path}', modified, changes, [path]))
                seen_scenarios.add(key)
        ranked_search_stopped = False
        ranked_stop_rank = None
        for label, candidate_requirements, changes, allowed in scenarios:
            is_ranked = label.startswith('relax:rank:')
            scenario_rank = int(label.split(':')[2]) if is_ranked else None
            if is_ranked and ranked_search_stopped and scenario_rank > ranked_stop_rank:
                unexplored_axes.append(label)
                continue
            if not changes:
                continue
            if len(numeric_candidates) >= 2 or solver_attempt_count() >= max_solver_attempts:
                unexplored_axes.append(label)
                if is_ranked:
                    ranked_search_stopped = True
                    ranked_stop_rank = scenario_rank
                continue
            receipt = solve(candidate_requirements, label)
            if receipt is None:
                unexplored_axes.append(label)
                if is_ranked:
                    ranked_search_stopped = True
                    ranked_stop_rank = scenario_rank
                break
            if is_ranked and receipt.get('status') != 'infeasible':
                # Feasibility, timeout, or any inconclusive solver result is
                # not proof that a higher compromise rank should be considered.
                ranked_search_stopped = True
                ranked_stop_rank = scenario_rank
                if not receipt.get('feasible'):
                    unexplored_axes.append(label)
            if receipt.get('status') in ('unproven', 'unverified'):
                if label not in unexplored_axes:
                    unexplored_axes.append(label)
                continue
            if not receipt.get('feasible'):
                if receipt.get('status') != 'infeasible' and label not in unexplored_axes:
                    unexplored_axes.append(label)
                continue
            tightened, actual_changes = _tighten_to_audited_volume(candidate_requirements, allowed, receipt, original)
            if tightened != candidate_requirements:
                tightened_receipt = solve(tightened, label + ':tightened_to_audited_output')
                if tightened_receipt is None or not tightened_receipt.get('feasible'):
                    continue
                candidate_requirements, receipt = tightened, tightened_receipt
            if not actual_changes:
                # A temporary broadening that the audited output did not need is
                # not a user-facing trade-off.
                continue
            changes = actual_changes
            if not _unchanged_except_relaxations(original, candidate_requirements, allowed):
                continue
            if not isinstance(receipt.get('audit'), dict) or receipt['audit'].get('errors'):
                continue
            numeric_candidates.append({'requirementsId': requirements_id, 'baseDraftId': base_draft_id,
                'programGuidance': source_program_guidance,
                'originalRequirementsHash': original_hash, 'libraryFingerprint': library_hash,
                'trainingHistoryFingerprint': history_hash, 'changes': changes,
                'requirements': candidate_requirements, 'workouts': receipt['sessions'], 'audit': receipt['audit'],
                **({'relaxationRanks': _ranked_change_paths(changes, rank_by_path)} if rank_by_path else {})})

    candidates, seen_proposals = [], set()
    for candidate in numeric_candidates:
        review, review_status, review_error = review_candidate_safely(
            candidate['workouts'], candidate['requirements'], candidate)
        if review_status:
            attempts.append({'scenario': 'independent_review', 'review': review_status,
                             'reason': review_error})
            if candidates:
                unexplored_axes.append('independent_review')
                break
            return diagnosed_outcome('unresolved', 'supplied prescription menu and explored negotiable bounds',
                reason='Independent review did not complete before any proposal was validated; no alternative or conflict is claimed.',
                attemptedRelaxationPaths=paths, attempts=attempts, elapsedSeconds=time.monotonic() - started)
        if not isinstance(review, dict) or review.get('passed') is not True:
            attempts.append({'scenario': 'independent_review', **_review_failure(review),
                'candidateChanges': copy.deepcopy(candidate['changes']),
                'candidateSearch': copy.deepcopy(candidate.get('search'))})
            continue
        if not isinstance(review.get('preview'), str) or not review['preview'].strip():
            attempts.append({'scenario': 'independent_review', 'review': 'missing_full_preview'})
            continue
        from .plan_review import REVIEW_VERSION
        review_receipt = review.get('review', review)
        if review_receipt.get('version') != REVIEW_VERSION:
            attempts.append({'scenario': 'independent_review', 'review': 'stale_or_missing_review_version'})
            continue
        candidate['independentReview'] = review
        candidate['diagnosisVersion'] = CONFLICT_RESOLUTION_VERSION
        candidate['reviewVersion'] = REVIEW_VERSION
        candidate['shortfallsAgainstOriginalRequirements'] = _shortfalls_against_original_requirements(
            candidate['audit'], original, candidate['changes'])
        if allocation_conflict_fingerprint:
            candidate['allocationConflictFingerprint'] = allocation_conflict_fingerprint
        candidate['searchScope'] = 'the supplied exercise menu'
        candidate['structuralSearchStatus'] = structural_status
        candidate['claim'] = ('Validated against the proposed requirements for the supplied exercise menu; '
            'original-target shortfalls are shown. No global optimum or impossibility is claimed.')
        proposal_id = 'ALT_' + _hash(_proposal_core(candidate))[:24]
        if proposal_id in seen_proposals:
            continue
        seen_proposals.add(proposal_id)
        candidates.append({'proposalId': proposal_id, **candidate})

    elapsed = time.monotonic() - started
    if candidates:
        return diagnosed_outcome('alternatives_ready', 'supplied prescription menu and explicitly negotiable numerical bounds',
            requirementsId=requirements_id, originalRequirementsHash=original_hash, baseDraftId=base_draft_id,
            libraryFingerprint=library_hash, trainingHistoryFingerprint=history_hash,
            initialConflict=_conflict_details(first, requirements),
            proposals=candidates, attempts=attempts, elapsedSeconds=elapsed,
            **({'allocationConflictFingerprint': allocation_conflict_fingerprint}
                if allocation_conflict_fingerprint else {}),
            structuralSearchStatus=structural_status,
            searchComplete=not unexplored_axes,
            unexploredTradeoffAxes=unexplored_axes,
            approvalInstruction='No proposal changes the active requirements until its exact proposalId is explicitly approved.')
    all_relaxed = (not paths or (all(any(a['scenario'] == label and a.get('status') == 'infeasible'
                                    for a in attempts) for label in all_relaxation_scenarios)
                                 and (not rank_by_path or bool(all_relaxation_scenarios))))
    all_relaxed = all_relaxed and not unexplored_axes
    if (all_relaxed and structural_search_verified
            and all(a.get('status') not in ('unproven', 'unverified') for a in attempts)):
        return diagnosed_outcome('verified_conflict_within_menu', 'supplied prescription menu and modeled constraints',
            reason='The solver proved the supplied menu infeasible after exploring the explicitly negotiable numerical bounds within their supported ranges. Mandatory constraints, equipment and safety restrictions were preserved.',
            initialConflict=_conflict_details(first, requirements), attempts=attempts, elapsedSeconds=elapsed,
            searchComplete=True)
    return diagnosed_outcome('unresolved', 'supplied prescription menu and explored negotiable numerical bounds',
        reason='No reviewed alternative was validated within the bounded search; this does not establish that the request is impossible.',
        attemptedRelaxationPaths=paths, attempts=attempts, elapsedSeconds=elapsed,
        structuralSearchStatus=structural_status,
        searchComplete=not unexplored_axes, unexploredTradeoffAxes=unexplored_axes)


def accept_workout_alternative(*, proposal_id, proposal_result, messages, current_requirements,
                               equipment, training_history=None):
    """Accept only a displayed proposal with exact, current user authorization."""
    from .planning_tools import _latest_result, library_fingerprint

    _, recorded = _latest_result(messages, 'propose_workout_alternatives')
    if not isinstance(recorded, dict) or recorded.get('outcome') != 'alternatives_ready':
        raise ValueError('There is no stored, validated alternative proposal to approve.')
    if recorded.get('diagnosisVersion') != CONFLICT_RESOLUTION_VERSION:
        raise ValueError('The conflict diagnosis is stale; generate and review alternatives again.')
    proposal = next((item for item in recorded.get('proposals', []) if item.get('proposalId') == proposal_id), None)
    supplied = next((item for item in proposal_result.get('proposals', []) if item.get('proposalId') == proposal_id), None) if isinstance(proposal_result, dict) else None
    if proposal is None or supplied != proposal:
        raise ValueError('The proposal is missing, changed or not part of the latest proposal result.')
    if proposal.get('diagnosisVersion') != CONFLICT_RESOLUTION_VERSION:
        raise ValueError('The alternative was diagnosed under older rules; generate and review alternatives again.')
    from .plan_review import REVIEW_VERSION
    independent_review = proposal.get('independentReview', {})
    review_receipt = independent_review.get('review', independent_review)
    if proposal.get('reviewVersion') != REVIEW_VERSION or review_receipt.get('version') != REVIEW_VERSION:
        raise ValueError('The alternative review is stale; generate and review alternatives again.')
    if recorded.get('requirementsId') != current_requirements.get('requirementsId'):
        raise ValueError('The approved requirements changed; generate and review alternatives again.')
    if recorded.get('originalRequirementsHash') != _hash(current_requirements.get('requirements', current_requirements)):
        raise ValueError('The original requirements changed; generate and review alternatives again.')
    if recorded.get('libraryFingerprint') != library_fingerprint(equipment):
        raise ValueError('The exercise library or equipment changed; validate alternatives again.')
    if recorded.get('trainingHistoryFingerprint') != getattr(training_history, 'fingerprint', None):
        raise ValueError('Training evidence changed; validate alternatives again.')
    _, latest_draft = _latest_result(messages, 'audit_workout_plan')
    if latest_draft.get('currentDraftId', latest_draft.get('draftId')) != recorded.get('baseDraftId'):
        raise ValueError('The workout draft changed; generate and review alternatives again.')
    if proposal.get('independentReview', {}).get('passed') is not True:
        raise ValueError('The alternative has no passing independent review.')
    if proposal_id != 'ALT_' + _hash(_proposal_core(proposal))[:24]:
        raise ValueError('The alternative contents failed their integrity check.')
    preview_index = next((index for index, message in enumerate(messages)
        if message.get('role') == 'assistant'
        and message.get('canonicalAlternativePreview') == proposal_id
        and message.get('content') == render_alternative_preview(proposal)), None)
    if preview_index is None:
        raise ValueError('Display the exact alternative before accepting it.')
    approval = f'APPROVE ALTERNATIVE {proposal_id}'
    def is_continue_only(message):
        content = message.get('content')
        return (isinstance(content, str) and content.strip() == '/continue'
            and not any(message.get(field) for field in ('imageAttachments', 'images', 'attachments')))

    substantive_users = [message for message in messages[preview_index + 1:]
        if message.get('role') == 'user' and not is_continue_only(message)]
    latest_user = substantive_users[-1] if substantive_users else None
    if (latest_user is None or latest_user.get('imageAttachments') or latest_user.get('images')
            or latest_user.get('attachments') or not isinstance(latest_user.get('content'), str)
            or latest_user['content'].strip() != approval):
        raise ValueError(f'Explicitly approve by typing: {approval}')
    new_requirements = copy.deepcopy(proposal['requirements'])
    new_requirements_id = 'REQ_' + _hash({'supersedes': current_requirements['requirementsId'],
        'proposalId': proposal_id, 'requirements': new_requirements})[:24]
    return {'requirementsId': new_requirements_id, 'requirements': new_requirements,
        'supersedesRequirementsId': current_requirements['requirementsId'],
        'approvedAlternativeId': proposal_id,
        'originalRequirementsHash': recorded['originalRequirementsHash'],
        'workouts': copy.deepcopy(proposal['workouts']),
        'programGuidance': proposal.get('programGuidance', ''),
        'audit': copy.deepcopy(proposal['audit']),
        'independentReview': copy.deepcopy(proposal['independentReview'])}
