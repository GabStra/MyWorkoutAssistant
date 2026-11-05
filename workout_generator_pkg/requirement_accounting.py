"""Trace approved instructions to their existing enforcement paths."""
import copy
import hashlib
import json
import math
import re

STRUCTURED_REQUIREMENTS_MARKER = 'Current approved structured requirements for extraction (the numerical authority):'


def comparison_requirements(requirements):
    """Ignore presentation and set ordering, never approved quantities or priority order."""
    value = copy.deepcopy(requirements)
    value.pop('notes', None)
    if value.get('familySetBounds') == []:
        value.pop('familySetBounds')
    for rule in value.get('requiredCoverage', []):
        rule.pop('description', None)
    for rule in value.get('executionRules', []):
        for field in ('sharedResourceGroups', 'confirmedIndependentPairs'):
            if field in rule:
                rule[field] = sorted(sorted(group) for group in rule[field])
    for field in ('requiredCoverage', 'executionRules'):
        if field in value:
            value[field].sort(key=lambda item: json.dumps(item, sort_keys=True))
    for field in ('excludeNameTerms', 'exceptNameTerms'):
        if field in value.get('exerciseRestrictions', {}):
            value['exerciseRestrictions'][field].sort()
    return value

REQUIREMENT_INTAKE_POLICY = (
    'Normalize natural-language requests through the existing requirements intake before planning. '
    'Python fills neutral omissions and discloses application defaults; unspecified targets are not zero targets. '
    'Preserve explicit quantities, restrictions and qualifiers. Do not turn an ambiguous preference into a guessed numeric constraint. '
    'Represent explicit soft muscle-set ranges with preferredMinimum/preferredMaximum, separate from hard minimum/maximum; '
    'only explicitly ranked volume_target optimizes those ranges. A missed preference is not a requirement violation. '
    'For an explicit preference for more volume within a range, use a later weekly_effective_sets:MUSCLE goal tier; '
    'its negative target and positive scale must come from the source, not guessed physiology or a universal high-volume default. '
    'Use existing planning decisions for source-delegated proposals and show them for approval. '
    'Ask only about material missing choices, contradictions or unsupported requests. '
    'History and equipment are generation context: do not require historical conclusions in the initial request or assume missing capability. '
    'Do not copy one user\'s personal targets into defaults for other users.'
)


def structured_requirement_source(sources, schema):
    """Recognize the explicit user intake format, never arbitrary conversation JSON."""
    from jsonschema import validate

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate structured requirement key: {key}')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f'Nonfinite structured requirement value: {value}')

    decoder = json.JSONDecoder(object_pairs_hook=object_pairs, parse_constant=invalid_constant)
    matches = []
    for source in sources:
        if source.get('role') != 'user':
            continue
        text = source.get('content') or ''
        offset, fence, found = 0, None, False
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            fence_match = re.match(r'^(`{3,}|~{3,})', stripped)
            if fence_match:
                token = fence_match.group(1)[0]
                fence = None if fence == token else token if fence is None else fence
            if fence is None and line.rstrip('\r\n') == STRUCTURED_REQUIREMENTS_MARKER:
                if found:
                    raise ValueError('Only one current structured requirements block is allowed per user message.')
                found = True
                matches.append((source, text, offset + len(line)))
            offset += len(line)
    if not matches:
        return None
    source, text, start = matches[-1]
    if type(source.get('messageIndex')) is not int or source['messageIndex'] < 0:
        raise ValueError('Structured requirements require an original user message index.')
    start += len(text[start:]) - len(text[start:].lstrip())
    if text[start:].startswith('```json\n') or text[start:].startswith('```json\r\n'):
        start = text.index('\n', start) + 1
    payload, consumed = decoder.raw_decode(text[start:])
    input_schema = copy.deepcopy({key: value for key, value in schema.items() if key != 'required'})
    input_schema['properties']['auditTargets'].pop('required', None)
    validate(payload, input_schema)
    if not isinstance(payload, dict) or not payload:
        raise ValueError('The structured requirements block must be a nonempty object.')
    end = start + consumed
    return {'sourceMessageIndex': source['messageIndex'], 'start': start, 'end': end,
        'sha256': hashlib.sha256(text[start:end].encode('utf-8')).hexdigest(),
        'requirements': payload}


def comparable_requirement(value):
    """Ignore code-rendered labels while preserving quantities and ordered priorities."""
    if isinstance(value, dict):
        result = {key: comparable_requirement(item) for key, item in value.items()
                  if key not in ('description', 'notes')}
        if result.get('kind') == 'coverageBalance':
            result.setdefault('relationship', 'balanced')
        return result
    if isinstance(value, list):
        return [comparable_requirement(item) for item in value]
    return value


def complete_structured_requirements(authority, schema, candidate_requirements=None):
    """Require an explicit policy, allowing only already-equivalent neutral omissions."""
    if not authority:
        return False
    effective = authority['requirements'] if candidate_requirements is None else candidate_requirements
    fields = schema['properties'].keys() - {'notes', 'requirementAccounting', 'objectiveTiers', 'trainingDays'}
    # A retained nonempty bound still needs review when the current source omits it.
    if comparison_requirements({'familySetBounds': effective.get('familySetBounds', [])}) == {}:
        fields.discard('familySetBounds')
    return fields <= authority['requirements'].keys()


def seed_structured_requirements(arguments, authority):
    """Code copies supplied fields; only omitted fields remain model-owned."""
    result = copy.deepcopy(arguments)
    for key, value in authority['requirements'].items():
        if key == 'notes':
            continue
        if key == 'executionRules':
            supplied = result.get(key, [])
            if not isinstance(supplied, list):
                raise ValueError('Supplied executionRules must be an array; they cannot clear the marked user rules.')
            if any(comparable_requirement(rule) not in [comparable_requirement(item) for item in value]
                   for rule in supplied):
                raise ValueError('executionRules adds or changes a rule in the structured user source.')
            result[key] = copy.deepcopy(value)
        elif key == 'auditTargets':
            supplied = result.get(key, {})
            if not isinstance(supplied, dict) or any(
                    field in supplied and comparable_requirement(supplied[field]) != comparable_requirement(target)
                    for field, target in value.items()):
                raise ValueError('auditTargets differs from the structured user source.')
            result[key] = {**supplied, **copy.deepcopy(value)}
        else:
            if key in result and comparable_requirement(result[key]) != comparable_requirement(value):
                raise ValueError(f'{key} differs from the structured user source.')
            result[key] = copy.deepcopy(value)
    return result


def structured_authority_paths(requirements, authority):
    """Only exact current matches are settled; scoped amendments remain reviewable."""
    paths = []
    for key, value in authority['requirements'].items():
        if key == 'notes':
            continue
        actual = requirements.get(key)
        if key == 'executionRules':
            if comparable_requirement(actual) == comparable_requirement(value):
                paths.append('/requirements/executionRules')
            for index, rule in enumerate(actual or []):
                if comparable_requirement(rule) in [comparable_requirement(item) for item in value]:
                    paths.append(f'/requirements/executionRules/{index}')
        elif key == 'auditTargets' and isinstance(actual, dict):
            if comparable_requirement(actual) == comparable_requirement(value):
                paths.append('/requirements/auditTargets')
            paths.extend('/requirements/auditTargets/' + field for field, target in value.items()
                         if comparable_requirement(actual.get(field)) == comparable_requirement(target))
        elif comparable_requirement(actual) == comparable_requirement(value):
            paths.append('/requirements/' + key)
    return paths


def structured_requirement_mismatches(requirements, authority):
    paths = []
    for key, value in authority['requirements'].items():
        if key == 'notes':
            continue
        if key == 'executionRules':
            from .programming_guidelines import (MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE,
                DEFAULT_ISOLATION_REST_RULE)
            current = [comparable_requirement(rule) for rule in requirements.get(key, [])]
            explicit = [comparable_requirement(rule) for rule in value]
            defaults = [comparable_requirement(rule) for rule in (
                MINIMUM_WORK_SETS_RULE, SESSION_STRUCTURE_RULE, DEFAULT_ISOLATION_REST_RULE)]
            if (any(rule not in current for rule in explicit)
                    or any(rule not in explicit + defaults for rule in current)):
                paths.append('/requirements/executionRules')
        elif key == 'auditTargets':
            current = requirements.get(key, {})
            paths.extend('/requirements/auditTargets/' + field for field, target in value.items()
                         if comparable_requirement(current.get(field)) != comparable_requirement(target))
        elif comparable_requirement(requirements.get(key)) != comparable_requirement(value):
            paths.append('/requirements/' + key)
    return paths


def requirement_implementation_checks(requirements):
    from .recipe_contracts import CODE_OWNED_DIRECT_COVERAGE_ROLES
    from .repair_capabilities import CODE_OWNED_BEHAVIORS
    roles = sorted(item['key'] for item in requirements.get('requiredCoverage', [])
                   if item['key'] in CODE_OWNED_DIRECT_COVERAGE_ROLES)
    checks = {
        **{key: {'status': 'code_owned_runtime_behavior', 'answer': answer}
            for key, answer in CODE_OWNED_BEHAVIORS.items()},
        'direct_coverage': {'status': 'enforced_at_recipe_qualification_and_final_audit', 'roles': roles,
            'answer': 'Direct muscle-role eligibility is derived from primary library muscle tags by Python; secondary credit cannot satisfy it. The final audit checks approved per-session presence and explicit role floors. No exercise-level compliance is claimed before a plan exists.'},
        'physical_sets': {'status': 'enforced_at_final_audit',
            'answer': 'Python counts physical working sets once; overlapping abs/core role labels do not add another physical set. Actual totals are checked after solving.'},
        'regional_reporting': {'status': 'evidence_dependent',
            'answer': 'Regional contributions use reviewed library annotations; missing evidence remains unknown. Combined target compliance does not establish regional development.'},
        'source_instruction_preservation': {'status': 'retained_for_planning_and_final_review',
            'answer': 'Original user instructions remain in chronological sourceMessages for planning and final-artifact review. '
                'Qualitative, conditional and reporting obligations need no duplicate numerical requirement field or rewritten notes. '
                'Retention is not proof that the final output satisfies them; unsupported behavior and genuine ambiguity remain reviewable.'},
    }
    sessions = requirements.get('sessionsPerWeek')
    if 'role_concentration' in requirements.get('objectiveOrder', []) and sessions:
        from .joint_planning import _role_concentration_keys
        concentration_roles = set(_role_concentration_keys(requirements))
        checks['role_distribution'] = {
            'status': 'soft_objective_after_higher_ranked_priorities',
            'minimumDoseEqualShares': {rule['key']: rule['minimumWeeklySets'] / sessions
                for rule in requirements.get('requiredCoverage', [])
                if rule['key'] in concentration_roles and 'minimumWeeklySets' in rule},
            'answer': 'The approved role_concentration objective distributes targeted primary-muscle and all-session development roles. '
                'minimumDoseEqualShares computes equal per-session shares only for weekly floors in that quantitative objective. '
                'Inclusion and explicitly partial-week development retain their approved presence, dose and frequency constraints without an implied equal daily dose. '
                'These are soft distribution preferences, not hard per-session minima or a claim of achieved distribution; '
                'the final plan supplies actual doses and residual imbalance.'}
    return checks

MINIMUM_TARGET_POLICY = (
    'Minimum requirements are fixed by default. General permission to offer alternatives, compromise, '
    'or return a partially compliant plan does not authorize lowering minimums. Mark lower_minimum '
    'only when the user specifically permits reducing the affected minimum targets. For a range, '
    'account for its minimum and maximum separately when their permissions differ. Permission to '
    'exceed a volume ceiling authorizes raise_maximum only; preserve the minimum and all equipment, '
    'safety and duration restrictions unless separately authorized.'
)

ACCOUNTING_SCHEMA = {'type': 'array', 'items': {'type': 'object', 'properties': {
    'instruction': {'type': 'string', 'minLength': 1},
    'sourceReferences': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                         'items': {'type': 'string', 'pattern': '^SOURCE_[0-9]+$'}},
    'requirementPaths': {'type': 'array', 'items': {'type': 'string',
        'pattern': '^/(auditTargets|sessionsPerWeek|trainingDays|minimumRestDaysBetweenSessions|workingSetRIR|requiredCoverage|executionRules|exerciseRestrictions|objectiveOrder|objectiveTiers|durationBalanceToleranceSeconds|familySetBounds)(/.*)?$'},
        'description': 'JSON pointers into the submitted requirements object, e.g. /auditTargets/weeklyEffectiveSets/chest/minimum or /requiredCoverage/0. Coverage keys such as knee_dominant_each_session are VALUES, never pointer indices. Use [] for semantic instructions not represented by a numeric field.'},
    'priority': {'type': 'string', 'enum': ['mandatory', 'negotiable', 'preference'],
        'description': 'mandatory means fixed; negotiable means the source permits exploring a compromise, but the current value remains binding until a specific alternative is approved. Preserve explicit source-ranked compromises such as time over a volume target. preference is a soft goal, never a hard minimum.'},
    'relaxationDirection': {'type': 'string', 'enum': ['lower_minimum', 'raise_maximum', 'increase_duration'],
        'description': 'For every negotiable numeric constraint that supports an alternative, state the exact source-authorized direction. Omit for mandatory and preference entries. A negotiable label alone does not authorize changing both ends of a range. ' + MINIMUM_TARGET_POLICY},
    'relaxationRank': {'type': 'integer', 'minimum': 1,
        'description': 'Optional source-backed compromise order for negotiable supported numeric constraints. Lower ranks are relaxed sooner; equal ranks are tied. Omit when the user did not order trade-offs.'},
    'enforcement': {'type': 'string', 'enum': ['constraint', 'semantic_check', 'clarification', 'unsupported']},
    'reason': {'type': 'string', 'minLength': 1}},
    'required': ['instruction', 'sourceReferences', 'requirementPaths', 'priority', 'enforcement', 'reason'],
    'additionalProperties': False},
    'description': 'Account for EVERY explicit instruction, including qualitative goals and exceptions. For movement goals, distinguish requested inclusion from development emphasis in requiredCoverage.intent, and encode only explicit source-backed comparisons in coverageBalance.relationship. Development intent does not create an extra-exposure objective or a numeric floor; encode approved floors with explicit minimumWeeklySets/minimumSessions fields, and include any extra-exposure preference only when explicitly ranked in objectiveOrder. The approved soft workload_economy preference minimizes physical weekly working sets after earlier preferences in the approved objectiveOrder; it cannot alter explicit user numbers or hard constraints. The app owns progression and load calibration. Cite original user SOURCE_n. Constraints point to existing extracted fields. Semantic checks retain instructions that require judgment. Mark genuinely unsupported or ambiguous instructions before drafting. Mandatory is the default; negotiable requires source authorization. A preference is never a new hard threshold.'}

RELAXATION_PERMISSIONS_SCHEMA = {'type': 'array', 'items': {'type': 'object', 'properties': {
    'path': {'type': 'string', 'pattern': '^/auditTargets/(maximumSessionSeconds|weeklyEffectiveSets/.+/(minimum|maximum)|perSessionEffectiveSets/.+/(minimum|maximum))$'},
    'direction': {'type': 'string', 'enum': ['lower_minimum', 'raise_maximum', 'increase_duration']},
    'rank': {'type': 'integer', 'minimum': 1}},
    'required': ['path', 'direction'], 'additionalProperties': False},
    'description': 'Explicit source-authorized numeric changes that may be proposed for human review. Permissions never approve a change. Restrictions, equipment, and safety requirements cannot be relaxed.'}


def pointer(document, path):
    value = document
    if not path.startswith('/'):
        raise ValueError('Requirement paths must be JSON pointers.')
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def alternative_evaluation_contract(original_record, candidate_record):
    """Bind hypothetical evaluation to exactly the source-authorized numeric changes."""
    proposal = candidate_record['proposedAlternative']
    if proposal['originalRequirementsId'] != original_record['requirementsId']:
        raise ValueError('Alternative evaluation requires its original requirements record.')
    original = original_record['requirements']
    effective = candidate_record['requirements']
    expected = copy.deepcopy(original)
    allowed = set(relaxation_paths(original))
    seen = set()
    changes = proposal['changes']
    for change in changes:
        path = change['path']
        if path in seen or path not in allowed:
            raise ValueError('Alternative evaluation contains a duplicate or unauthorized requirement change: ' + path)
        seen.add(path)
        old, new = change['from'], change['to']
        if (pointer(original, path) != old or pointer(effective, path) != new
                or isinstance(new, bool) or not isinstance(new, (int, float))
                or not math.isfinite(new) or new == old):
            raise ValueError('Alternative evaluation change does not match its bound requirements: ' + path)
        if ((path.endswith('/minimum') and new >= old)
                or (path.endswith(('/maximum', '/maximumSessionSeconds')) and new <= old)):
            raise ValueError('Alternative evaluation changed a requirement in an unauthorized direction: ' + path)
        parent_path, _, field = path.rpartition('/')
        pointer(expected, parent_path)[field] = new
    if expected != effective or original_record.get('restrictionPolicy', {}) != candidate_record.get('restrictionPolicy', {}):
        raise ValueError('Alternative evaluation changed requirements or restrictions outside its listed proposal.')
    approved = bool(proposal.get('approvedAlternativeId')) and proposal.get('requiresUserApproval') is False
    return {'version': 1, 'originalRequirementsId': original_record['requirementsId'],
        'evaluationRequirementsId': candidate_record['requirementsId'],
        'originalRequirementsHash': hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest(),
        'evaluationRequirementsHash': hashlib.sha256(json.dumps(effective, sort_keys=True).encode()).hexdigest(),
        'proposedOverrides': copy.deepcopy(changes),
        'approval': {'status': 'approved' if approved else 'pending',
            'gate': 'after_full_validation', 'owner': 'alternative_acceptance'},
        'decisionScope': ('Original source instructions and resolved decisions remain binding except for the exact '
            'numeric paths in proposedOverrides. Evaluate those clauses using the proposed values; this does not '
            'accept the proposal or waive any other clause of a decision.'),
        'guidanceScope': ('Candidate guidance must accurately describe the hypothetical plan and disclose its '
            'proposed exceptions without claiming approval. Stale compliance claims are editable program_guidance '
            'defects, not missing approval or unsupported execution behavior.')}


def validate_accounting(requirements, sources):
    if 'requirementAccounting' not in requirements:
        return
    accounted_sources = set()
    for item in requirements.get('requirementAccounting', []):
        refs = item['sourceReferences']
        if any(ref not in sources for ref in refs) or any(sources[ref]['role'] != 'user' for ref in refs):
            raise ValueError('Every accounted instruction must cite only existing user sources.')
        accounted_sources.update(refs)
        for path in item['requirementPaths']:
            if path.startswith('/requirementAccounting'):
                raise ValueError('An instruction must point to the actual requirement, not its accounting.')
            if path.startswith('/objectiveOrder') and not requirements.get('objectiveOrder'):
                raise ValueError('An accounted solver preference must map to a nonempty source-backed objectiveOrder.')
            try:
                pointer(requirements, path)
            except (KeyError, ValueError, IndexError, TypeError) as error:
                raise ValueError(f'Invalid requirement pointer {path!r}. Use an actual submitted field, such as /requiredCoverage/0; array indices are numbers, not coverage keys.') from error
        if ('relaxationPermissions' not in requirements
                and item['priority'] == 'negotiable' and item['enforcement'] == 'constraint'
                and any(path.startswith('/auditTargets/') for path in item['requirementPaths'])):
            relaxable_paths = set()
            for direction in ('lower_minimum', 'raise_maximum', 'increase_duration'):
                probe = copy.deepcopy(requirements)
                probe['requirementAccounting'] = [{**item, 'relaxationDirection': direction}]
                relaxable_paths.update(relaxation_paths(probe))
            if relaxable_paths and not item.get('relaxationDirection'):
                raise ValueError('A negotiable numeric constraint needs its source-authorized relaxationDirection.')
            if item.get('relaxationDirection') and not relaxation_paths({**requirements,
                    'requirementAccounting': [item]}):
                raise ValueError('The relaxationDirection does not match a supported numeric requirement path.')
        if 'relaxationPermissions' not in requirements and 'relaxationRank' in item:
            rank = item['relaxationRank']
            if (not isinstance(rank, int) or isinstance(rank, bool) or rank < 1
                    or item['priority'] != 'negotiable' or item['enforcement'] != 'constraint'
                    or not item.get('relaxationDirection')):
                raise ValueError('A relaxation rank requires a positive integer on a negotiable supported numeric constraint with an explicit direction.')
            supported = set(relaxation_paths(requirements))
            if not any(path in supported or (path.startswith('/auditTargets/')
                    and any(candidate.startswith(path.rstrip('/') + '/') for candidate in supported))
                    for path in item['requirementPaths']):
                raise ValueError('A relaxation rank may only order supported numeric constraint paths.')
        if ('relaxationPermissions' not in requirements and item.get('relaxationDirection')
                and item['priority'] != 'negotiable'):
            raise ValueError('Only explicitly negotiable requirements may declare a relaxation direction.')
        if item['enforcement'] == 'constraint' and not item['requirementPaths']:
            raise ValueError('An enforced constraint needs its extracted requirement path.')
        if item['priority'] != 'mandatory' and any(path.startswith('/exerciseRestrictions') for path in item['requirementPaths']):
            raise ValueError('Explicit exercise/safety restrictions cannot be relaxed automatically.')
    missing_sources = sorted(reference for reference, source in sources.items()
                              if source.get('role') == 'user' and reference not in accounted_sources)
    if missing_sources:
        raise ValueError('Every original user source must be accounted for; missing: ' + ', '.join(missing_sources) + '.')


def _supported_permission(requirements, path, direction):
    parts = path.split('/')
    if path == '/auditTargets/maximumSessionSeconds':
        try:
            value = pointer(requirements, path)
        except (KeyError, ValueError, IndexError, TypeError):
            return False
        return direction == 'increase_duration' and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if (len(parts) != 5 or parts[1] != 'auditTargets'
            or parts[2] not in ('weeklyEffectiveSets', 'perSessionEffectiveSets')
            or parts[4] not in ('minimum', 'maximum')):
        return False
    try:
        value = pointer(requirements, path)
    except (KeyError, ValueError, IndexError, TypeError):
        return False
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return False
    return ((parts[4] == 'minimum' and direction == 'lower_minimum' and value >= 0)
            or (parts[4] == 'maximum' and direction == 'raise_maximum' and 0 < value <= 100))


def validate_relaxation_permissions(requirements):
    """Validate the code-owned authority for hypothetical numeric relaxation proposals."""
    if 'relaxationPermissions' not in requirements:
        return
    permissions = requirements['relaxationPermissions']
    if not isinstance(permissions, list):
        raise ValueError('relaxationPermissions must be an array.')
    seen = set()
    for item in permissions:
        if (not isinstance(item, dict) or set(item) - {'path', 'direction', 'rank'}
                or not isinstance(item.get('path'), str)
                or item.get('direction') not in ('lower_minimum', 'raise_maximum', 'increase_duration')):
            raise ValueError('Each relaxation permission needs a supported path and direction.')
        path = item['path']
        if path in seen:
            raise ValueError('A relaxation path may be authorized only once.')
        seen.add(path)
        if path.startswith('/exerciseRestrictions') or not _supported_permission(requirements, path, item['direction']):
            raise ValueError('Relaxation permission does not match a supported numeric target and direction; exercise and safety restrictions cannot be relaxed.')
        rank = item.get('rank')
        if 'rank' in item and (not isinstance(rank, int) or isinstance(rank, bool) or rank < 1):
            raise ValueError('A relaxation permission rank must be a positive integer.')


def accounting_gaps(requirements):
    return [copy.deepcopy(item) for item in requirements.get('requirementAccounting', [])
            if item['enforcement'] in ('clarification', 'unsupported')]


def relaxation_paths(requirements):
    """Return explicit permissions, or legacy accounting permissions for saved records."""
    if 'relaxationPermissions' in requirements:
        validate_relaxation_permissions(requirements)
        return sorted(item['path'] for item in requirements['relaxationPermissions'])
    paths = set()
    def supported(path, value, direction):
        if path == '/auditTargets/maximumSessionSeconds':
            if direction == 'increase_duration' and isinstance(value, (int, float)) and not isinstance(value, bool):
                paths.add(path)
        elif path.startswith(('/auditTargets/weeklyEffectiveSets', '/auditTargets/perSessionEffectiveSets')):
            if isinstance(value, dict):
                for key, child in value.items():
                    supported(path + '/' + key.replace('~', '~0').replace('/', '~1'), child, direction)
            elif (path.endswith('/minimum') and direction == 'lower_minimum'
                  and isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0):
                paths.add(path)
            elif (path.endswith('/maximum') and direction == 'raise_maximum'
                  and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < 100):
                paths.add(path)
    for item in requirements.get('requirementAccounting', []):
        if item['priority'] != 'negotiable' or item['enforcement'] != 'constraint':
            continue
        for path in item['requirementPaths']:
            if path.startswith('/auditTargets/'):
                supported(path, pointer(requirements, path), item.get('relaxationDirection'))
    return sorted(paths)


def has_unresolved_numeric_relaxation(requirements):
    """Whether a negotiable numeric constraint has no explicit supported direction."""
    if 'relaxationPermissions' in requirements:
        validate_relaxation_permissions(requirements)
        return False
    for item in requirements.get('requirementAccounting', []):
        if (item.get('priority') != 'negotiable' or item.get('enforcement') != 'constraint'
                or item.get('relaxationDirection')
                or not any(path.startswith('/auditTargets/') for path in item.get('requirementPaths', []))):
            continue
        for direction in ('lower_minimum', 'raise_maximum', 'increase_duration'):
            probe = copy.deepcopy(requirements)
            probe['requirementAccounting'] = [{**item, 'relaxationDirection': direction}]
            if relaxation_paths(probe):
                return True
    return False


def relaxation_rank_by_path(requirements):
    """Return ranks from explicit permissions, with legacy accounting fallback."""
    supported_paths = set(relaxation_paths(requirements))
    ranks = {}
    if 'relaxationPermissions' in requirements:
        return {item['path']: item['rank'] for item in requirements['relaxationPermissions']
                if item.get('rank') is not None}
    for item in requirements.get('requirementAccounting', []):
        rank = item.get('relaxationRank')
        if rank is None:
            continue
        for path in item.get('requirementPaths', []):
            if path in supported_paths:
                ranks[path] = rank
            elif path.startswith('/auditTargets/'):
                prefix = path.rstrip('/') + '/'
                for supported_path in supported_paths:
                    if supported_path.startswith(prefix):
                        ranks[supported_path] = rank
    return ranks


def outcome(result):
    joint = result.get('coordinatedJointPlanning') or result.get('automaticAllocation') or {}
    if result.get('passed') and result.get('review') and not result['review'].get('failure'):
        return {'status': 'verified_feasible', 'scope': 'Approved requirements, selected library configurations, production audit and independent review.',
                'conditions': []}
    reason = joint.get('instruction') or 'Candidate repair, capability support or independent validation is unfinished.'
    if joint.get('status') == 'infeasible':
        reason = ('The current menu is infeasible, but the candidate-menu expansion and bounded conflict diagnosis '
                  'have not established that the approved request conflicts. ' + reason)
    return {'status': 'unresolved',
            'scope': 'Current candidate construction and validation stage; an infeasible supplied menu is not a verified conflict.',
            'reason': reason}
