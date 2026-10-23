"""Source-backed execution rules; training recommendations are not universal prohibitions."""

from itertools import combinations

from .generation_audit import add_audit_issue


_COVERAGE = {'type': 'string', 'minLength': 1, 'description': 'An approved requiredCoverage key. Execution review verifies that each assigned movement actually qualifies.'}
_SELECTOR = {'anyOf': [_COVERAGE, {'type': 'null'}], 'description': 'Coverage key, or null for all exercises to which this rule applies.'}
MINIMUM_WORK_SETS_RULE = {'kind': 'workSets', 'coverageKey': None, 'minimumSets': 2, 'maximumSets': 20}
SESSION_STRUCTURE_RULE = {'kind': 'sessionStructure', 'maximumExercises': 15, 'maximumSupersetSize': 3}


def _rule(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


EXECUTION_RULES_SCHEMA = {'type': 'array', 'maxItems': 30,
    'description': 'Extract explicit user execution constraints only. Use requiredCoverage for source-backed roles such as priority lifts. Never turn general recommendations into mandatory requirements. Order is checked within each session where both roles occur; earlier blocks must finish before later blocks. Rest ranges are inclusive, and apply only to rests the app actually executes: straightSets and supersetRound require at least two working sets; supersetTransition executes once per round even with one working set.',
    'items': {'oneOf': [
        _rule({'kind': {'const': 'sessionStructure'},
               'maximumExercises': {'type': 'integer', 'minimum': 1, 'maximum': 100},
               'maximumSupersets': {'type': 'integer', 'minimum': 0, 'maximum': 50},
               'maximumSupersetSize': {'type': 'integer', 'minimum': 2, 'maximum': 100}}, ['kind']),
        _rule({'kind': {'const': 'order'}, 'before': _COVERAGE, 'after': _COVERAGE}, ['kind', 'before', 'after']),
        _rule({'kind': {'const': 'coverageBalance'}, 'first': _COVERAGE, 'second': _COVERAGE,
               'scope': {'enum': ['weekly', 'eachSession']},
               'relationship': {'enum': ['balanced', 'first_not_less_than_second'],
                   'description': 'Use balanced only for a source-backed balance request. Use first_not_less_than_second only when the source explicitly prioritizes the first role at least as much as the second; this is a soft comparison, never a ratio or quota.'}},
              ['kind', 'first', 'second', 'scope']),
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
    'goalAuthority': 'Apply programming preferences to the approved structured requirements and original source instructions. Training goals are not interchangeable. Distinguish requested inclusion from development emphasis: `requiredCoverage.intent=inclusion` establishes presence only; `development` marks a source-backed emphasis for semantic assessment but creates no numeric floor or automatic proof of adequate stimulus. A source-backed coverageBalance relationship may express balanced exposure or that the first role should not receive less exposure than the second; neither defines a ratio or hard minimum. Compare direct and weighted secondary contributions; regional stimulus needs supported execution evidence. Clarify only material source ambiguity; do not invent user requirements or numeric thresholds for qualitative goals. Apply code-owned defaults only when shown in the approved requirements. Recommendations never authorize compromise; objectiveOrder represents only supported numerical priorities.',
    'deterministic': 'New requirements candidates include the application policy of at least two working sets per selected exercise occurrence, at most 15 exercise occurrences per session including every superset member, and at most three exercises per superset. These session limits apply to the selected plan, not the candidate pool. The existing working-set cap of 20 is a numeric domain limit, not a training recommendation. The approved rules are shown for approval and shared by selection and audit. Existing approved requirements are not retroactively changed. Other executionRules enforce explicit working-set limits, exercise-block order, straight sets, generated ramp-ups and rest ranges. Selectors use requiredCoverage assignments; the independent reviewer verifies their movement/role semantics. Volume, time, load suitability and required coverage use the existing audits.',
    'review': [
        'Prescription authority: structured fields own rep ranges, rest intervals and loading configuration. Python renders the standard working-set underperformance stop/re-audit rule; it is fixed behavior, not a local-note repair. Preserve source-backed movement-specific technique and safety cues. Assess only rests the app executes: a straightSets restBetweenSetsSeconds field does not represent an executed rest when numWorkSets is 1, and a superset-round rest is likewise inactive for one round. Do not repair an inactive between-set/round rest field; check actual prescribed recovery during every executed interval. In notes, refer to the prescribed range/rest instead of repeating those numbers. Explain only execution and acceptance details not already represented. A note contradicting a structured prescription is an established violation, not uncertainty. New loading configurations or exercise variants require selection and re-audit before use.',
        'Execution capabilities: every working, warm-up, calibration, assistance, progression and fallback action must use confirmed equipment and available help. Describe bodyweight assistance operationally; an unspecified assistance setting does not establish a usable method. A re-audit instruction does not authorize using new gear, help or a different movement before confirmation and validation. Unavailable alternatives may be proposed for confirmation, never prescribed as executable fallbacks. The app owns native load calibration; generator notes must not add a second calibration procedure. Conflicting instructions are blocking, not merely uncertain load suitability.',
        'Order: prioritize the stated goal. Earlier exercise placement can favor strength in that movement; compound-first is not a universal hypertrophy requirement. Check whether earlier work materially undermines a stated priority.',
        'Fatigue and recovery: assess the complete week, not just each muscle total. Trace repeated demands on prime movers, grip, trunk bracing and spinal loading through exercise order, working-set counts, effort, rest and actual scheduled recovery. Include eccentric/unfamiliar work and how earlier fatigue may limit later technical or priority lifts. Ground each concern in supplied movement definitions, prescriptions and comparable history; do not infer spinal loading or recovery from muscle credits alone. No universal ban on consecutive compounds, fixed exercise count, fatigue score or invented recovery threshold. Do not infer actual weekday spacing from frequency alone.',
        'Fatigue management: prefer distributing demanding exposures, reducing redundant work, using a supported less fatiguing variant, or changing order/pairing before changing approved targets. Preserve the approved training goal, practical progression, equipment feasibility and numerical constraints. Do not claim a token rest day, different exercise name or a generic recovery note resolves repeated loading. When evidence makes feasibility materially uncertain, repair the exercise selection or supported prescription conservatively; never silently count reduced fallback volume toward the original target.',
        'Supersets and rest: verify physical setup and recovery between successive sets of each member, including partner work. Use supported equipment transitions, unilateral execution and timing assumptions to assess practicality; similar duration does not establish similar fatigue. Do not double-count setup time, prohibit all supersets or impose antagonist-only pairings. Enforce source-backed setup/rest constraints.',
        'Progression: use comparable history and selectable resistance. Do not transfer loads across variants as proven equivalents. The app owns progression; use native requiresLoadCalibration for unknown starting loads; neither mandatory rep drop-off nor increasing load every week proves adequate effort.',
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
        keys = ([] if rule['kind'] == 'sessionStructure' else
                [rule['first'], rule['second']] if rule['kind'] == 'coverageBalance' else
                [rule['before'], rule['after']] if rule['kind'] == 'order' else [rule['coverageKey']])
        missing = set(keys) - coverage - {None}
        reason = f'Coverage keys not declared in requiredCoverage: {sorted(missing)}.' if missing else None
        if rule['kind'] == 'sessionStructure' and not any(key in rule for key in (
                'maximumExercises', 'maximumSupersets', 'maximumSupersetSize')):
            reason = 'A session structure rule must specify at least one upper bound.'
        if rule['kind'] == 'order' and rule['before'] == rule['after']:
            reason = 'An execution role cannot precede itself.'
        if rule['kind'] == 'coverageBalance' and rule['first'] == rule['second']:
            reason = 'A coverage comparison requires two different roles.'
        if (rule['kind'] == 'coverageBalance'
                and rule.get('relationship', 'balanced') not in ('balanced', 'first_not_less_than_second')):
            reason = 'The coverage comparison relationship is unsupported.'
        if rule['kind'] == 'rest' and rule['minimumSeconds'] > rule['maximumSeconds']:
            reason = 'Minimum rest exceeds maximum rest.'
        if rule['kind'] == 'workSets' and rule['minimumSets'] > rule['maximumSets']:
            reason = 'Minimum working sets exceeds maximum working sets.'
        if reason:
            error = {'code': 'invalid_execution_rule', 'path': path, 'message': reason,
                     'repair': 'Correct the rule using existing source-backed requiredCoverage keys and valid bounds. Ask if the requested execution is ambiguous; do not invent a role or relax requirements.'}
            if missing:
                error['repair'] = ('Reference a declared requiredCoverage key, or declare a supported role there when the original source explicitly requires it. '
                    'An undeclared reference does not mean the role is unavailable. Do not substitute a different movement role or relax the source requirement.')
                error['allowedCoverageKeys'] = sorted(coverage)
                error['invalidReferences'] = {field: value for field, value in rule.items()
                    if field in ('first', 'second', 'before', 'after', 'coverageKey') and value in missing}
            errors.append(error)
    work_set_rules = [(index, rule) for index, rule in enumerate(requirements.get('executionRules', []))
                      if rule['kind'] == 'workSets' and rule['minimumSets'] <= rule['maximumSets']]
    for position, (index, rule) in enumerate(work_set_rules):
        for other_index, other in work_set_rules[position + 1:]:
            coverage_overlaps = (rule['coverageKey'] is None or other['coverageKey'] is None
                                 or rule['coverageKey'] == other['coverageKey'])
            category_overlaps = (rule.get('exerciseCategory') is None or other.get('exerciseCategory') is None
                                 or rule['exerciseCategory'] == other['exerciseCategory'])
            minimum = max(rule['minimumSets'], other['minimumSets'])
            maximum = min(rule['maximumSets'], other['maximumSets'])
            if coverage_overlaps and category_overlaps and minimum > maximum:
                errors.append({'code': 'conflicting_execution_rules', 'path': f'/executionRules/{other_index}',
                    'message': f'Overlapping working-set rules at /executionRules/{index} and /executionRules/{other_index} have no compatible set count.',
                    'repair': 'Resolve the conflicting set-count constraints before approval; preserve the code-owned two-set minimum.'})
    return errors


def render_execution_rule(rule):
    kind = rule['kind']
    if kind == 'sessionStructure':
        labels = {'maximumExercises': 'exercise occurrences per session (including every superset member)',
                  'maximumSupersets': 'superset groups per session',
                  'maximumSupersetSize': 'exercises per superset'}
        return '; '.join(f'At most {rule[key]} {label}' for key, label in labels.items() if key in rule) + '.'
    if kind == 'coverageBalance':
        scope = 'over the week' if rule['scope'] == 'weekly' else 'within each session'
        if rule.get('relationship', 'balanced') == 'first_not_less_than_second':
            return (f"Prefer `{rule['first']}` to receive at least as much exposure as `{rule['second']}` {scope}; "
                    'this is a source-backed comparison, not a fixed ratio or hard minimum.')
        return f"Balance `{rule['first']}` with `{rule['second']}` {scope}. Assess comparable exposure under the approved priority policy; no numerical tolerance was specified."
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


def native_warmup_supported(definition, equipment_ids):
    """Whether the app's generated ramp-up path can run for this library configuration."""
    return bool(definition
        and definition.get('exerciseType') in ('WEIGHT', 'BODY_WEIGHT')
        and definition.get('equipmentId') in equipment_ids
        and (definition.get('exerciseType') != 'BODY_WEIGHT'
             or definition.get('bodyWeightPercentage') is not None))


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
            if kind == 'sessionStructure':
                groups = {}
                for index, item in enumerate(exercises):
                    if item.get('superset') is not None:
                        groups.setdefault(item['superset'], []).append(index)
                counts = {'maximumExercises': len(exercises), 'maximumSupersets': len(groups),
                          'maximumSupersetSize': max(map(len, groups.values()), default=0)}
                for key, actual in counts.items():
                    if key in rule and actual > rule[key]:
                        findings += 1
                        add_audit_issue(report, 'execution_sessionStructure',
                            f"{day['name']}: {key} is {actual}; approved maximum is {rule[key]}.",
                            'Reselect or regroup exercises within the approved session limits, preserving required coverage, volume and timing; re-audit.',
                            path=f'/workouts/{day_index}/exercises', rulePath=f'/executionRules/{rule_index}',
                            limit=key, actual=actual, maximum=rule[key])
                continue

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
                    for item in (ea, eb):
                        if item.get('requiresLoadCalibration') is True:
                            from .domain_ops import get_selectable_weights_for_exercise
                            gear = next((gear for gear in plan.get('equipments', [])
                                         if gear['id'] == item['equipmentId']), None)
                            choices = (get_selectable_weights_for_exercise(item.get('exerciseType'), gear)
                                       if gear else [])
                            uncertain = uncertain or len(set(choices)) != 1
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
                    identifiers = (plan or {}).get('workouts', [{}])[day_index].get('exerciseIds', []) \
                        if plan and day_index < len(plan.get('workouts', [])) else []
                    identifier = identifiers[index] if index < len(identifiers) else None
                    definition = definitions.get(identifier)
                    equipment_ids = {gear.get('id') for gear in (plan or {}).get('equipments', [])}
                    if plan and not native_warmup_supported(definition, equipment_ids):
                        issue(index, '', 'The approved generated-ramp-up rule applies, but this exercise configuration cannot produce native ramp-up sets.',
                            'Replace this occurrence with a library configuration supported by the app warm-up generator while preserving required coverage. If no such option is available, ask the user to resolve the conflict; do not toggle the flag or change the requirement.',
                            warmupCapability='unsupported')
                    else:
                        issue(index, 'generateWarmUpSets', render_execution_rule(rule),
                            'Set generateWarmUpSets=true for this supported occurrence; preserve working sets and re-audit the added preparation time.')
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


def session_structure_limits(requirements):
    """Intersect approved session bounds without applying them to an unselected candidate pool."""
    limits = {}
    for rule in requirements.get('executionRules', []):
        if rule['kind'] == 'sessionStructure':
            for key in ('maximumExercises', 'maximumSupersets', 'maximumSupersetSize'):
                if key in rule:
                    limits[key] = min(limits.get(key, rule[key]), rule[key])
    return limits


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
