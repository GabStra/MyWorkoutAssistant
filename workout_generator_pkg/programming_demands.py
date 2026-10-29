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


def demand_union_exposure_input(demand_inputs):
    """Describe unique sets with any verified-present property, without treating unknown as absent."""
    groups = demand_inputs.get('groups', {})
    present_by_group = {key: frozenset(group.get('presentDefinitionIds', []))
                        for key, group in groups.items()}
    union = frozenset().union(*present_by_group.values()) if present_by_group else frozenset()
    if (len(groups) < 2 or len(set(present_by_group.values())) < 2
            or any(union == present for present in present_by_group.values())):
        return None

    evidence_by_definition = {}
    for key, group in groups.items():
        for identifier in group.get('presentDefinitionIds', []):
            source = group.get('evidenceByDefinition', {}).get(identifier)
            if source:
                evidence_by_definition.setdefault(identifier, {})[key] = source

    return {
        'presentDefinitionIds': sorted(union),
        'evidenceByDefinition': evidence_by_definition,
        'availableGroups': sorted(groups),
        'status': demand_inputs.get('status', 'unavailable'),
        'unavailableGroups': dict(demand_inputs.get('unavailableGroups', {})),
        'interpretation': ('Unique work sets with at least one sourced-present property among the listed complete groups; '
            'overlapping properties count a set once. This is structural concentration only; unavailable properties '
            'remain unknown, with no fatigue-equivalence, tolerance threshold, or personal-suitability claim.'),
    }
