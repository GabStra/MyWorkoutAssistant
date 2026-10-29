"""Code-owned subjects and factual premises for qualitative review choices."""
import re


CONCERNS = {
    'source_compliance': 'Source compliance',
    'movement_coverage': 'Movement-role suitability',
    'equipment_setup': 'Equipment and setup',
    'load_suitability': 'Loading suitability',
    'fatigue_recovery': 'Fatigue and recovery',
    'practical_execution': 'Practical execution',
    'guidance_consistency': 'Guidance consistency',
    'review_error': 'Correction of a prior review',
}
JUDGMENTS = {
    'source_conflict': 'The reviewer judges that the selected subjects conflict with the cited requirement.',
    'role_mismatch': 'The reviewer judges that the selected movements do not support the cited role.',
    'setup_uncertainty': 'Execution with the selected setup requires clarification.',
    'capacity_uncertainty': 'Personal capacity for the selected prescription is not established.',
    'recovery_uncertainty': 'Recovery tolerance for the selected exposure is not established.',
    'concentration_tradeoff': 'The reviewer identifies a concentration tradeoff in the selected exposure.',
    'overlap_tradeoff': 'The reviewer identifies overlapping work in the selected exposure.',
    'emphasis_tradeoff': 'The reviewer identifies a movement-emphasis tradeoff.',
    'execution_conflict': 'The reviewer judges that the selected execution conflicts with the cited requirement.',
    'unsupported_behavior': 'The requested execution behavior is not represented by the supported fields.',
    'unsupported_requirement': 'The prior objection requires an unapproved requirement.',
    'contradicted_by_current_data': 'The current code-owned facts contradict the prior objection.',
}
WITHDRAWAL_JUDGMENTS = {'unsupported_requirement', 'contradicted_by_current_data'}
QUALITATIVE_JUDGMENTS = {'setup_uncertainty', 'capacity_uncertainty', 'recovery_uncertainty',
    'concentration_tradeoff', 'overlap_tradeoff', 'emphasis_tradeoff'}


def review_subject_catalog(context):
    """Select canonical definitions, occurrences or sessions independently of citations."""
    exercises = context.get('draft', {}).get('exercises', [])
    by_id = {item['id']: f'EXERCISE_{index}' for index, item in enumerate(exercises)}
    catalog = {}
    for index, item in enumerate(exercises):
        occurrence = f'EXERCISE_{index}'
        catalog[occurrence] = {'exerciseRefs': [occurrence], 'workoutRefs': [],
            'path': f'/draft/exercises/{index}'}
        definition = item['libraryDefinitionId']
        catalog.setdefault(definition, {'exerciseRefs': [], 'workoutRefs': [],
            'path': '/draft/libraryDefinitions/' + definition.replace('~', '~0').replace('/', '~1')})['exerciseRefs'].append(occurrence)
    for index, day in enumerate(context.get('draft', {}).get('workouts', [])):
        catalog[f'WORKOUT_{index}'] = {'exerciseRefs': [by_id[identifier] for identifier in day['exerciseIds']],
            'workoutRefs': [f'WORKOUT_{index}'], 'path': f'/draft/workouts/{index}'}
    return catalog


def bind_review_subject_references(references, catalog, facts, context):
    """Bind only exact indexed aliases; unknown references still need correction."""
    from .plan_review import _pointer
    if len(references) != len(set(references)):
        return references
    bound = []
    by_id = {item['id']: f'EXERCISE_{index}'
        for index, item in enumerate(context.get('draft', {}).get('exercises', []))}
    for reference in references:
        if reference in catalog:
            selected = [reference]
        else:
            path = facts.get(reference, '')
            definition = re.fullmatch(r'/(?:programmingSummary/exposures|draft/libraryDefinitions|history|progressionCapabilities)/([^/]+)', path)
            occurrence = re.fullmatch(r'/draft/exercises/(\d+)', path)
            session = re.fullmatch(r'/(?:finalArtifact/workouts|programmingSummary/sessions)/(\d+)', path)
            if definition and definition[1] in catalog:
                selected = [definition[1]]
            elif occurrence and f'EXERCISE_{occurrence[1]}' in catalog:
                selected = [f'EXERCISE_{occurrence[1]}']
            elif session and f'WORKOUT_{session[1]}' in catalog:
                selected = [f'WORKOUT_{session[1]}']
            elif path == '/finalArtifact':
                selected = [key for key in catalog if key.startswith('WORKOUT_')]
            elif re.fullmatch(r'/finalArtifact/workouts/\d+/components/\d+(?:/exercises/\d+)?', path):
                component = _pointer(context, path)
                members = component.get('exercises', []) if component.get('type') == 'Superset' else [component]
                selected = [by_id[item['id']] for item in members if item.get('id') in by_id]
            else:
                selected = []
            selected = selected or [reference]
        bound.extend(selected)
    return list(dict.fromkeys(bound))


def compile_review_subjects(subject_refs, catalog, context):
    """Compute selected and whole-plan exposure from the reviewed occurrence identities."""
    if not subject_refs or len(subject_refs) != len(set(subject_refs)):
        raise ValueError('A review finding needs distinct code-provided subjects.')
    unknown = set(subject_refs) - catalog.keys()
    if unknown:
        raise ValueError('Unknown review subjects: ' + ', '.join(sorted(unknown)))
    selected = set().union(*(set(catalog[ref]['exerciseRefs']) for ref in subject_refs))
    exercises = context['draft']['exercises']
    by_id = {item['id']: (index, item) for index, item in enumerate(exercises)}
    definitions = context['draft'].get('libraryDefinitions', {})
    subjects = {}
    for day in context['draft']['workouts']:
        for identifier in day['exerciseIds']:
            index, item = by_id[identifier]
            definition_ref = item['libraryDefinitionId']
            if f'EXERCISE_{index}' not in selected:
                continue
            subjects.setdefault(definition_ref, {'definitionRef': definition_ref,
                'name': item.get('name') or definitions.get(definition_ref, {}).get('name', definition_ref),
                'selectedWeeklyWorkingSets': 0, 'weeklyWorkingSets': 0,
                'sessionWorkingSets': [], 'exerciseRefs': []})
    for day in context['draft']['workouts']:
        daily = dict.fromkeys(subjects, 0)
        for identifier in day['exerciseIds']:
            index, item = by_id[identifier]
            reference = item['libraryDefinitionId']
            if reference not in subjects:
                continue
            count = item['numWorkSets']
            frequency = day.get('timesCompletedInAWeek', 1)
            subjects[reference]['weeklyWorkingSets'] += count * frequency
            daily[reference] += count
            if f'EXERCISE_{index}' in selected:
                subjects[reference]['selectedWeeklyWorkingSets'] += count * frequency
                subjects[reference]['exerciseRefs'].append(f'EXERCISE_{index}')
        for reference, count in daily.items():
            subjects[reference]['sessionWorkingSets'].append({'session': day['name'], 'sets': count,
                'sessionsPerWeek': day.get('timesCompletedInAWeek', 1)})
    return sorted(selected, key=lambda ref: int(ref.rsplit('_', 1)[1])), list(subjects.values())


def render_review_judgment(concern, judgment, subjects):
    """Only code renders identities and quantities entering a repair obligation."""
    label, assessment = CONCERNS[concern], JUDGMENTS[judgment]
    rows = [f"{item['name']}: {item['weeklyWorkingSets']} weekly sets; "
        + ', '.join(f"{day['session']} {day['sets']}" for day in item['sessionWorkingSets'])
        for item in subjects[:3]]
    if len(subjects) > 3:
        rows.append('Additional subjects are listed in the structured subject facts.')
    names = ', '.join(item['name'] for item in subjects[:3])
    message = label + ' — ' + names + '. ' + assessment
    return message, message + ' Code-owned exposure: ' + '; '.join(rows)


def validate_review_judgments(review):
    """Apply the same disposition semantics to live, cached and planner-consumed reviews."""
    groups = {index: group for group in review.get('assessment', {}).get('groups', [])
        for index in group.get('findingIndexes', [])}
    for index, finding in enumerate(review.get('findings', [])):
        disposition = groups.get(index, {}).get('disposition')
        judgment = finding.get('reviewJudgment')
        if judgment and disposition and ((judgment in WITHDRAWAL_JUDGMENTS)
                != (disposition == 'withdrawn_review_error')):
            raise ValueError('Withdrawal judgments cannot authorize candidate repairs or approval.')
        if (disposition == 'repair' and judgment in QUALITATIVE_JUDGMENTS
                and not groups[index].get('repairObjectives')):
            raise ValueError('A qualitative repair needs an executable outcome or human adjudication.')


def validate_review_subjects(review, context):
    """Recheck cached/exported finding premises against the current reviewed artifact."""
    validate_review_judgments(review)
    if not review.get('findings'):
        return
    catalog = review_subject_catalog(context)
    for finding in review.get('findings', []):
        refs, subjects = compile_review_subjects(finding.get('subjectRefs'), catalog, context)
        workouts = sorted({ref for subject in finding['subjectRefs'] for ref in catalog[subject]['workoutRefs']})
        if (finding.get('subjectExerciseRefs') != refs or finding.get('subjectFacts') != subjects
                or finding.get('subjectWorkoutRefs') != workouts
                or finding.get('reviewConcern') not in CONCERNS or finding.get('reviewJudgment') not in JUDGMENTS):
            raise ValueError('Review subject facts do not match the current artifact.')
        message, reason = render_review_judgment(finding['reviewConcern'], finding['reviewJudgment'], subjects)
        if finding.get('message') != message or not finding.get('repair', '').endswith(reason):
            raise ValueError('Review factual premises must be rendered from code-owned subjects.')
