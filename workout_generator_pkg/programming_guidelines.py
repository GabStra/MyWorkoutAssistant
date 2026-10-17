"""Source-backed execution rules; training recommendations are not universal prohibitions."""

from itertools import combinations

from .generation_audit import add_audit_issue


_COVERAGE = {'type': 'string', 'minLength': 1, 'description': 'An approved requiredCoverage key. Execution review verifies that each assigned movement actually qualifies.'}
_SELECTOR = {'anyOf': [_COVERAGE, {'type': 'null'}], 'description': 'Coverage key, or null for all exercises to which this rule applies.'}


def _rule(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


EXECUTION_RULES_SCHEMA = {'type': 'array', 'maxItems': 30,
    'description': 'Extract explicit user execution constraints only. Use requiredCoverage for source-backed roles such as priority lifts. Never turn general recommendations into mandatory requirements. Order is checked within each session where both roles occur; earlier blocks must finish before later blocks. Rest ranges are inclusive, and apply only to rests the app actually executes.',
    'items': {'oneOf': [
        _rule({'kind': {'const': 'order'}, 'before': _COVERAGE, 'after': _COVERAGE}, ['kind', 'before', 'after']),
        _rule({'kind': {'const': 'straightSets'}, 'coverageKey': _COVERAGE}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'warmup'}, 'coverageKey': _COVERAGE}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'supersetNoReconfiguration'}, 'coverageKey': _SELECTOR}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'rest'}, 'coverageKey': _SELECTOR,
               'exerciseCategory': {'enum': ['HEAVY_COMPOUND', 'MODERATE_COMPOUND', 'ISOLATION']},
               'context': {'enum': ['straightSets', 'supersetTransition', 'supersetRound']},
               'minimumSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 1800},
               'maximumSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 1800}},
              ['kind', 'coverageKey', 'context', 'minimumSeconds', 'maximumSeconds']),
    ]}}

# Shared by planner and independent reviewer; no additional model call.
GUIDELINE_POLICY = {
    'version': 2,
    'deterministic': 'Approved executionRules enforce exercise-block order, straight sets, generated ramp-ups and rest ranges. Selectors use requiredCoverage assignments; the independent reviewer must verify their movement/role semantics. Volume, time, load suitability and required coverage use the existing audits.',
    'review': [
        'Order: prioritize the stated goal. Earlier exercise placement can favor strength in that movement; compound-first is not a universal hypertrophy requirement. Check whether earlier work materially undermines a stated priority.',
        'Fatigue and recovery: consider shared-muscle fatigue, technical demands, effort, frequency and the stated schedule together. No universal ban on consecutive compounds, fixed rest-day count, or fixed exercise count. Do not infer actual weekday spacing from a frequency alone.',
        'Supersets and rest: verify physical setup and recovery between successive sets of each member, including partner work. Non-competing pairings can save time; do not prohibit all supersets or impose antagonist-only pairings. Enforce source-backed setup/rest constraints.',
        'Progression: use comparable history and selectable resistance. Do not transfer loads across variants as proven equivalents. Require an actionable progression/calibration strategy; neither mandatory rep drop-off nor increasing load every week proves adequate effort.',
        'Warm-ups and effort: match preparation to the planned demand and account for stated tempo, setup, calibration and warm-ups in timing. A warm-up flag cannot prove preparation is sufficient, and prescribed sets cannot prove actual effort.',
    ],
    'severity': 'Only a source-backed requirement violation, concrete contradiction or unsupported material claim blocks. General training recommendations and uncertain fatigue effects are warnings with evidence and a practical suggestion. Ask about genuine ambiguity; do not invent targets or silently rewrite requirements.',
    'sources': [
        'https://pmc.ncbi.nlm.nih.gov/articles/PMC12965823/',
        'https://pubmed.ncbi.nlm.nih.gov/32077380/',
        'https://pmc.ncbi.nlm.nih.gov/articles/PMC12011898/',
    ],
}


def execution_rule_errors(requirements):
    """Validate links and bounds before a rule can be presented for approval."""
    coverage = {item['key'] for item in requirements.get('requiredCoverage', [])}
    errors = []
    effort = requirements.get('workingSetRIR')
    if effort and effort['minimum'] > effort['maximum']:
        errors.append({'code': 'invalid_effort_range', 'path': '/workingSetRIR', 'message': 'Minimum RIR exceeds maximum RIR.',
                       'repair': 'Correct the effort range against the user instructions; do not invent a new effort target.'})
    for index, rule in enumerate(requirements.get('executionRules', [])):
        path = f'/executionRules/{index}'
        keys = [rule['before'], rule['after']] if rule['kind'] == 'order' else [rule['coverageKey']]
        missing = set(keys) - coverage - {None}
        reason = f'Unknown coverage keys: {sorted(missing)}.' if missing else None
        if rule['kind'] == 'order' and rule['before'] == rule['after']:
            reason = 'An execution role cannot precede itself.'
        if rule['kind'] == 'rest' and rule['minimumSeconds'] > rule['maximumSeconds']:
            reason = 'Minimum rest exceeds maximum rest.'
        if reason:
            errors.append({'code': 'invalid_execution_rule', 'path': path, 'message': reason,
                           'repair': 'Correct the rule using existing source-backed requiredCoverage keys and valid bounds. Ask if the requested execution is ambiguous; do not invent a role or relax requirements.'})
    return errors


def render_execution_rule(rule):
    kind = rule['kind']
    if kind == 'order':
        return f"`{rule['before']}` blocks before `{rule['after']}` blocks (when both occur in a session)."
    selector = f"`{rule['coverageKey']}`" if rule['coverageKey'] else 'All applicable exercises'
    if kind == 'supersetNoReconfiguration':
        return f'{selector}: no shared-equipment reconfiguration between superset partners.'
    if kind == 'rest':
        label = {'straightSets': 'between straight sets', 'supersetTransition': 'between superset partners',
                 'supersetRound': 'after each superset round'}[rule['context']]
        category = f" ({rule['exerciseCategory']})" if rule.get('exerciseCategory') else ''
        return f"{selector}{category}: {rule['minimumSeconds']}–{rule['maximumSeconds']}s {label}."
    return f"{selector}: " + ('straight sets.' if kind == 'straightSets' else 'generated ramp-up sets before working sets.')


def audit_execution_rules(draft, requirements, report, plan=None):
    """Check the actual submitted order/grouping/rest fields without parsing exercise names or notes."""
    rules = requirements.get('executionRules', [])
    findings = 0
    definitions = {e['id']: e for e in (plan or {}).get('exercises', [])}
    for day_index, day in enumerate(draft['workouts']):
        exercises = day['exercises']
        blocks = []
        for index, item in enumerate(exercises):
            same_group = index and item['superset'] is not None and item['superset'] == exercises[index - 1]['superset']
            blocks.append(blocks[-1] if same_group else index)
        for rule_index, rule in enumerate(rules):
            kind = rule['kind']

            def matches(item, key):
                return key is None or key in item.get('satisfiesCoverage', [])

            def issue(index, field, message, repair, **details):
                nonlocal findings
                findings += 1
                add_audit_issue(report, 'execution_' + kind, f"{day['name']}: {message}", repair,
                    path=f'/workouts/{day_index}/exercises/{index}' + (f'/{field}' if field else ''),
                    rulePath=f'/executionRules/{rule_index}', **details)

            if kind == 'supersetNoReconfiguration' and plan:
                for (first, a), (second, b) in combinations(enumerate(exercises), 2):
                    if a['superset'] is None or a['superset'] != b['superset']:
                        continue
                    if not (matches(a, rule['coverageKey']) or matches(b, rule['coverageKey'])):
                        continue
                    ea, eb = [definitions[plan['workouts'][day_index]['exerciseIds'][i]] for i in (first, second)]
                    if ea.get('equipmentId') is None or ea.get('equipmentId') != eb.get('equipmentId'):
                        continue
                    loads = [{p['workSetIndex']: p.get('weight', p.get('additionalWeight'))
                              for p in item.get('targetSetPrescriptions', [])} for item in (a, b)]
                    conflict = any(loads[0][r] != loads[1][r] for r in loads[0].keys() & loads[1].keys())
                    uncertain = not all(loads) and not all(item.get('requiresEffortCalibration') for item in (a, b))
                    if conflict or uncertain:
                        issue(second, 'superset', 'Shared superset equipment has different prescribed loads.' if conflict else
                            'A common usable load is unverified for shared superset equipment.',
                            'Use compatible fixed loads justified for both movements, or separate/change the pairing. For an unknown common load, mark both members requiresEffortCalibration=true and remove fixed prescriptions; disclose conditional effort. Do not transfer historical loads or invent extra equipment. Re-audit timing and volume.',
                            partnerIndex=first)
                continue
            if kind == 'order':
                before = [i for i, item in enumerate(exercises) if matches(item, rule['before'])]
                after = [i for i, item in enumerate(exercises) if matches(item, rule['after'])]
                if before and after and max(blocks[i] for i in before) >= min(blocks[i] for i in after):
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
                if kind == 'straightSets' and item['superset'] is not None:
                    issue(index, 'superset', render_execution_rule(rule),
                        'Remove this occurrence from the superset and restore its approved between-set rest. Repair remaining group members and re-audit timing; do not delete required work.')
                elif kind == 'warmup' and not item['generateWarmUpSets']:
                    issue(index, 'generateWarmUpSets', render_execution_rule(rule),
                        'Set generateWarmUpSets=true for this occurrence; preserve working sets and re-audit the added preparation time.')
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
    report['executionGuidelines'] = {'checkedRules': len(rules), 'findings': findings,
        'assignmentVerification': 'Coverage-role semantics and contextual training recommendations require independent review.'}


def audit_execution_details(draft, requirements, report):
    """Require explicit timing assumptions and validate an actual repeating weekly schedule."""
    scheduled = []
    spacing = requirements.get('minimumRestDaysBetweenSessions')
    for day_index, day in enumerate(draft['workouts']):
        path = f'/workouts/{day_index}'
        if 'trainingDays' in day:
            if len(day['trainingDays']) != day['timesCompletedInAWeek']:
                add_audit_issue(report, 'schedule_frequency_mismatch', f"{day['name']}: trainingDays does not match weekly frequency.",
                    'Assign one weekday per weekly occurrence and re-audit the full schedule.', path=path + '/trainingDays')
            scheduled.extend((value, day_index) for value in day['trainingDays'])
        elif spacing is not None:
            add_audit_issue(report, 'schedule_days_required', f"{day['name']}: weekdays are required to verify recovery spacing.",
                'Set trainingDays to Monday=0 through Sunday=6, respecting any user-selected days. Do not infer spacing from frequency alone.', path=path + '/trainingDays')
        if requirements['auditTargets'].get('maximumSessionSeconds'):
            for index, item in enumerate(day['exercises'][1:], 1):
                if 'setupSeconds' not in item:
                    add_audit_issue(report, 'setup_time_required', f"{day['name']}: setup estimate missing before exercise {index + 1}.",
                        'Add setupSeconds for this transition, including implement, plate, rack, bench and attachment changes. Use an explicit estimate or ask for missing setup information; do not assert measured precision. It replaces the default allowance and does not replace prescribed rest.',
                        path=f'{path}/exercises/{index}/setupSeconds')
    if spacing is not None and scheduled:
        ordered = sorted(scheduled)
        for index, (value, day_index) in enumerate(ordered):
            next_day = ordered[(index + 1) % len(ordered)][0] + (7 if index == len(ordered) - 1 else 0)
            rest_days = max(0, next_day - value - 1)
            if rest_days < spacing:
                add_audit_issue(report, 'schedule_recovery_gap', f'Only {rest_days} full rest days between weekdays {value} and {next_day % 7}; required {spacing}.',
                    'Patch trainingDays to preserve the approved frequency and minimum spacing, including Sunday-to-Monday. Ask about a genuine scheduling conflict; do not relax the rule.',
                    path=f'/workouts/{day_index}/trainingDays', actual=rest_days, minimum=spacing)
