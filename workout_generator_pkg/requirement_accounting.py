"""Trace approved instructions to their existing enforcement paths."""
import copy
import hashlib
import json
import math

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
        'pattern': '^/(auditTargets|sessionsPerWeek|minimumRestDaysBetweenSessions|workingSetRIR|requiredCoverage|executionRules|exerciseRestrictions|objectiveOrder)(/.*)?$'},
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
    'description': 'Account for EVERY explicit instruction, including qualitative goals and exceptions. For movement goals, distinguish requested inclusion from development emphasis in requiredCoverage.intent, and encode only explicit source-backed comparisons in coverageBalance.relationship. Development is not a numeric floor; do not invent ratios. Cite original user SOURCE_n. Constraints point to existing extracted fields. Semantic checks retain instructions that require judgment. Mark genuinely unsupported or ambiguous instructions before drafting. Mandatory is the default; negotiable requires source authorization. A preference is never a new hard threshold.'}

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
