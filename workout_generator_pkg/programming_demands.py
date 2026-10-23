"""Reviewed library properties shared by selection, the solver, and final review."""

DEMAND_GROUPS = {
    'unsupported_trunk': 'Work performed without external trunk support',
    'axial_loading': 'Execution with an explicitly documented axial-loading exposure',
    'eccentric_emphasis': 'Execution with an explicitly prescribed eccentric emphasis',
}


def definition_demand_facts(definition):
    """Missing annotations remain unknown; names, categories and muscle credits are not evidence."""
    annotations = definition.get('programmingDemands', {})
    if not isinstance(annotations, dict) or set(annotations) - DEMAND_GROUPS.keys():
        raise ValueError('programmingDemands must contain only supported library property keys.')
    facts = {}
    for key in DEMAND_GROUPS:
        annotation = annotations.get(key)
        if annotation is None:
            facts[key] = {'status': 'unknown', 'source': None}
            continue
        if (not isinstance(annotation, dict) or set(annotation) != {'present', 'source'}
                or type(annotation['present']) is not bool
                or not isinstance(annotation['source'], str) or not annotation['source'].strip()):
            raise ValueError(f'programmingDemands.{key} requires a boolean present and a nonempty source.')
        facts[key] = {'status': 'present' if annotation['present'] else 'absent',
                      'source': annotation['source']}
    return facts


def demand_distribution_inputs(definitions):
    """Optimize a group only when every candidate has an explicit sourced classification."""
    facts_by_id = {definition['id']: definition_demand_facts(definition) for definition in definitions}
    groups, unavailable = {}, {}
    for key, label in DEMAND_GROUPS.items():
        unknown = sorted(identifier for identifier, facts in facts_by_id.items()
                         if facts[key]['status'] == 'unknown')
        if unknown or not facts_by_id:
            unavailable[key] = unknown
        else:
            groups[key] = {'label': label,
                'presentDefinitionIds': sorted(identifier for identifier, facts in facts_by_id.items()
                                               if facts[key]['status'] == 'present'),
                'evidenceByDefinition': {identifier: facts[key]['source']
                                         for identifier, facts in facts_by_id.items()}}
    return {'groups': groups, 'unavailableGroups': unavailable,
            'status': 'available' if groups and not unavailable else 'partial' if groups else 'unavailable',
            'interpretation': 'Counts of prescribed working sets sharing reviewed library properties, not equivalent fatigue, a tolerance threshold, or a personal-suitability verdict.'}
