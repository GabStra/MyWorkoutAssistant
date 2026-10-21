"""Source-backed execution rules; training recommendations are not universal prohibitions."""

from itertools import combinations

from .generation_audit import add_audit_issue


_COVERAGE = {'type': 'string', 'minLength': 1, 'description': 'An approved requiredCoverage key. Execution review verifies that each assigned movement actually qualifies.'}
_SELECTOR = {'anyOf': [_COVERAGE, {'type': 'null'}], 'description': 'Coverage key, or null for all exercises to which this rule applies.'}


def _rule(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


EXECUTION_RULES_SCHEMA = {'type': 'array', 'maxItems': 30,
    'description': 'Extract explicit user execution constraints only. Use requiredCoverage for source-backed roles such as priority lifts. Never turn general recommendations into mandatory requirements. Order is checked within each session where both roles occur; earlier blocks must finish before later blocks. Rest ranges are inclusive, and apply only to rests the app actually executes: straightSets and supersetRound require at least two working sets; supersetTransition executes once per round even with one working set.',
    'items': {'oneOf': [
        _rule({'kind': {'const': 'order'}, 'before': _COVERAGE, 'after': _COVERAGE}, ['kind', 'before', 'after']),
        _rule({'kind': {'const': 'coverageBalance'}, 'first': _COVERAGE, 'second': _COVERAGE,
               'scope': {'enum': ['weekly', 'eachSession']}}, ['kind', 'first', 'second', 'scope']),
        _rule({'kind': {'const': 'straightSets'}, 'coverageKey': _COVERAGE}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'warmup'}, 'coverageKey': _COVERAGE}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'workSets'}, 'coverageKey': _SELECTOR,
               'exerciseCategory': {'enum': ['HEAVY_COMPOUND', 'MODERATE_COMPOUND', 'ISOLATION']},
               'minimumSets': {'type': 'integer', 'minimum': 1, 'maximum': 20},
               'maximumSets': {'type': 'integer', 'minimum': 1, 'maximum': 20}},
              ['kind', 'coverageKey', 'minimumSets', 'maximumSets']),
        _rule({'kind': {'const': 'supersetNoReconfiguration',
            'description': 'Keep the same shared-equipment load between superset partners; Python checks compatible prescribed loads. Native per-exercise calibration does not establish a shared load. This does not prohibit every minor physical adjustment. Other source-backed setup constraints require execution review.'},
            'coverageKey': _SELECTOR}, ['kind', 'coverageKey']),
        _rule({'kind': {'const': 'rest'}, 'coverageKey': _SELECTOR,
               'exerciseCategory': {'enum': ['HEAVY_COMPOUND', 'MODERATE_COMPOUND', 'ISOLATION']},
               'context': {'enum': ['straightSets', 'supersetTransition', 'supersetRound']},
               'minimumSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 1800},
               'maximumSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 1800}},
              ['kind', 'coverageKey', 'context', 'minimumSeconds', 'maximumSeconds']),
    ]}}

# Shared by planner and independent reviewer; no additional model call.
GUIDELINE_POLICY = {
    'version': 12,
    'goalAuthority': 'Apply programming preferences to the approved source goals and requirementAccounting. Hypertrophy, strength, endurance and time efficiency are not interchangeable objectives. Recommendations never create user constraints or authorize a compromise; use objectiveOrder only for explicitly supported numerical priorities.',
    'deterministic': 'Approved executionRules enforce working-set limits, exercise-block order, straight sets, generated ramp-ups and rest ranges. Selectors use requiredCoverage assignments; the independent reviewer verifies their movement/role semantics. Volume, time, load suitability and required coverage use the existing audits.',
    'review': [
        'Prescription authority: structured fields own rep ranges, rest intervals and loading configuration. Python renders the standard working-set underperformance stop/re-audit rule; it is fixed behavior, not a local-note repair. Preserve source-backed movement-specific technique and safety cues. Assess only rests the app executes: a straightSets restBetweenSetsSeconds field does not represent an executed rest when numWorkSets is 1, and a superset-round rest is likewise inactive for one round. Do not repair an inactive between-set/round rest field; check actual prescribed recovery during every executed interval. In notes, refer to the prescribed range/rest instead of repeating those numbers. Explain only execution, acceptance, adjustment and progression details not already represented. A note contradicting a structured prescription is an established violation, not uncertainty. New loading configurations or exercise variants require selection and re-audit before use.',
        'Execution capabilities: every working, warm-up, calibration, assistance, progression and fallback action must use confirmed equipment and available help. Describe bodyweight assistance operationally; an unspecified assistance setting does not establish a usable method. A re-audit instruction does not authorize using new gear, help or a different movement before confirmation and validation. Unavailable alternatives may be proposed for confirmation, never prescribed as executable fallbacks. The app owns native load calibration; generator notes must not add a second calibration procedure. Conflicting instructions are blocking, not merely uncertain load suitability.',
        'Order: prioritize the stated goal. Earlier exercise placement can favor strength in that movement; compound-first is not a universal hypertrophy requirement. Check whether earlier work materially undermines a stated priority.',
        'Fatigue and recovery: assess the complete week, not just each muscle total. Trace repeated demands on prime movers, grip, trunk bracing and spinal loading through exercise order, working-set counts, effort, rest and actual scheduled recovery. Include eccentric/unfamiliar work and how earlier fatigue may limit later technical or priority lifts. Ground each concern in supplied movement definitions, prescriptions and comparable history; do not infer spinal loading or recovery from muscle credits alone. No universal ban on consecutive compounds, fixed exercise count, fatigue score or invented recovery threshold. Do not infer actual weekday spacing from frequency alone.',
        'Fatigue management: prefer distributing demanding exposures, reducing redundant work, using a supported less fatiguing variant, or changing order/pairing before changing approved targets. Preserve the approved training goal, practical progression, equipment feasibility and numerical constraints. Do not claim a token rest day, different exercise name or a generic recovery note resolves repeated loading. When evidence makes feasibility materially uncertain, repair the exercise selection or supported prescription conservatively; never silently count reduced fallback volume toward the original target.',
        'Supersets and rest: verify physical setup and recovery between successive sets of each member, including partner work. Non-competing pairings can save time; do not prohibit all supersets or impose antagonist-only pairings. Enforce source-backed setup/rest constraints.',
        'Progression: use comparable history and selectable resistance. Do not transfer loads across variants as proven equivalents. Require actionable progression; use native requiresLoadCalibration for unknown starting loads; neither mandatory rep drop-off nor increasing load every week proves adequate effort.',
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
        keys = ([rule['first'], rule['second']] if rule['kind'] == 'coverageBalance' else
                [rule['before'], rule['after']] if rule['kind'] == 'order' else [rule['coverageKey']])
        missing = set(keys) - coverage - {None}
        reason = f'Unknown coverage keys: {sorted(missing)}.' if missing else None
        if rule['kind'] == 'order' and rule['before'] == rule['after']:
            reason = 'An execution role cannot precede itself.'
        if rule['kind'] == 'coverageBalance' and rule['first'] == rule['second']:
            reason = 'Balance requires two different coverage roles.'
        if rule['kind'] == 'rest' and rule['minimumSeconds'] > rule['maximumSeconds']:
            reason = 'Minimum rest exceeds maximum rest.'
        if rule['kind'] == 'workSets' and rule['minimumSets'] > rule['maximumSets']:
            reason = 'Minimum working sets exceeds maximum working sets.'
        if reason:
            errors.append({'code': 'invalid_execution_rule', 'path': path, 'message': reason,
                           'repair': 'Correct the rule using existing source-backed requiredCoverage keys and valid bounds. Ask if the requested execution is ambiguous; do not invent a role or relax requirements.'})
    return errors


def render_execution_rule(rule):
    kind = rule['kind']
    if kind == 'coverageBalance':
        scope = 'over the week' if rule['scope'] == 'weekly' else 'within each session'
        return f"Balance `{rule['first']}` with `{rule['second']}` {scope}. Optimize comparable set exposure within all hard constraints; no numerical tolerance was specified."
    if kind == 'order':
        return f"`{rule['before']}` blocks before `{rule['after']}` blocks (when both occur in a session)."
    selector = f"`{rule['coverageKey']}`" if rule['coverageKey'] else 'All applicable exercises'
    if kind == 'workSets':
        category = f" ({rule['exerciseCategory']})" if rule.get('exerciseCategory') else ''
        return f"{selector}{category}: {rule['minimumSets']}–{rule['maximumSets']} working sets per occurrence."
    if kind == 'supersetNoReconfiguration':
        return f'{selector}: same shared-equipment load between superset partners; other setup constraints require execution review.'
    if kind == 'rest':
        label = {'straightSets': 'between straight sets', 'supersetTransition': 'between superset partners',
                 'supersetRound': 'after each superset round'}[rule['context']]
        category = f" ({rule['exerciseCategory']})" if rule.get('exerciseCategory') else ''
        applicability = (' (only when at least two working sets are prescribed)' if rule['context'] in ('straightSets', 'supersetRound')
                         else ' (for each executed transition)')
        return f"{selector}{category}: {rule['minimumSeconds']}–{rule['maximumSeconds']}s {label}{applicability}."
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
            if kind == 'coverageBalance':
                continue  # A qualitative balance goal does not authorize an invented hard ratio.

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
                              for p in item.get('targetSetPrescriptions', [])} for item in (ea, eb)]
                    conflict = any(loads[0][r] != loads[1][r] for r in loads[0].keys() & loads[1].keys())
                    uncertain = not all(loads)
                    if conflict or uncertain:
                        issue(second, 'superset', 'Shared superset equipment has different prescribed loads.' if conflict else
                            'A common usable load is unverified for shared superset equipment.',
                            'Use a common prescribed load justified for both movements, or separate/change the pairing. Native per-exercise calibration does not guarantee a shared load. Do not transfer historical loads or invent extra equipment. Re-audit timing and volume.',
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
                if kind == 'workSets' and not rule['minimumSets'] <= item['numWorkSets'] <= rule['maximumSets']:
                    issue(index, 'numWorkSets', render_execution_rule(rule),
                        'Restore a working-set count within the approved requirement; re-audit volume and duration.')
                elif kind == 'straightSets' and item['superset'] is not None:
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
