"""Observe support semantics in the source, then instantiate rig constraints.

Visual review owns contact identity; source tracks independently own stationarity.
Reconstructed joints supply dimensions, never evidence that a contact exists.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np

POLICY_VERSION = 7
BODY_SUPPORT_ANCHORS = ('pelvis', 'left_shoulder', 'right_shoulder')
_REGION_ANCHORS = {
    'shoulders': ('left_shoulder', 'right_shoulder'),
    'upper_body': ('left_shoulder', 'right_shoulder'),
    'upper_limb': ('left_shoulder', 'right_shoulder'),
    'pelvis': ('pelvis',),
    'hips': ('pelvis',),
    'core': ('pelvis',),
}
_SUPPORT_SURFACES = {'floor', 'bench', 'seat', 'wall', 'other'}
_HAND_SUPPORT_SURFACES = _SUPPORT_SURFACES | {'fixed_bar'}
_ANKLE_SUPPORT_SURFACES = {'fixed_bar', 'other'}
_OBSERVATION_FIELDS = {
    'torsoSurface', 'pelvisAndUpperBackSameSurface', 'pelvis', 'upperBack', 'head',
    'pelvisContactSurface', 'upperBackContactSurface', 'headContactSurface',
    'leftFoot', 'rightFoot', 'leftFootSurface', 'rightFootSurface',
    'leftFootSurfaceMotion', 'rightFootSurfaceMotion',
    'leftFootSurfaceOrientation', 'rightFootSurfaceOrientation',
    'leftFootContactContinuity', 'rightFootContactContinuity',
    'leftFootSurfaceImageRegion', 'rightFootSurfaceImageRegion',
    'leftHand', 'rightHand', 'leftHandContactSurface', 'rightHandContactSurface',
    'handsSameHorizontalSurface', 'observations',
    'leftKnee', 'rightKnee', 'leftKneeContactSurface', 'rightKneeContactSurface',
    'leftAnkle', 'rightAnkle', 'leftAnkleContactSurface', 'rightAnkleContactSurface',
}
CONTACT_TIMELINE_POLICY_VERSION = 8
_SUPPORTED_CONTACT_TIMELINE_POLICY_VERSIONS = {5, 6, CONTACT_TIMELINE_POLICY_VERSION}
_CONTACT_STATES = {'full_sole', 'forefoot', 'heel_only', 'airborne', 'unknown', 'direct_contact', 'no_contact'}
_CONTACT_SURFACES = {'ground', 'raised_surface', 'none', 'unknown',
                     *_SUPPORT_SURFACES, *_HAND_SUPPORT_SURFACES, *_ANKLE_SUPPORT_SURFACES}
_CONTACT_TIMELINE_FOOT_BATCH_SIZE = 6
CONTACT_TIMELINE_CROP_POLICY = 'symmetric-body-region-header-locators-and-foot-atlas-v2'
_STATIONARY_SOLE_REVIEW_IMAGES_PER_REQUEST = 5
_STATIONARY_SOLE_REVIEW_PROMPT_POLICY = 'stationary-sole-per-image-v2'

_CONTACT_SURFACE_REFERENTS = {
    'floor': 'floor means the floor-level support face, including a visible mat or pad covering it; contact with that covering counts without claiming bare-floor contact or a known floor height',
    'ground': 'ground means the floor-level support face, including a visible mat or pad covering it; contact with that covering counts without claiming bare-ground contact or a known floor height',
    'bench': 'bench means its visible support face, including upholstery or a pad; this does not establish the bench height',
    'seat': 'seat means its visible support face, including upholstery or a pad; this does not establish the seat height',
    'wall': 'wall means its visible face, including a directly attached covering or pad; this does not establish a metric position',
    'fixed_bar': 'fixed_bar means the fixed bar or a visible pad, roller, or restraint attached to it; direct body contact with that part must be visible',
    'raised_surface': 'raised_surface means the visible elevated support face itself, including its visible covering; this does not establish its metric height',
    'moving_implement': 'moving_implement means the visible surface of the moving implement itself; do not infer contact from proximity',
    'other': 'other means another directly visible support face; retain this category without guessing its identity or metric position',
    'none': 'none means no external support face is visibly touching the body region',
    'unknown': 'unknown means the support face or contact interface cannot be identified confidently',
}


def _contact_surface_referent(surface):
    label = str(surface or 'unknown').casefold()
    return _CONTACT_SURFACE_REFERENTS.get(
        label, 'the named support face itself; do not infer contact from proximity or assign metric geometry')


def _contact_surface_referent_guidance():
    return 'Support-surface labels describe the visible contact face, not a metric anchor: ' + '; '.join(
        _CONTACT_SURFACE_REFERENTS[surface] for surface in
        ('floor', 'ground', 'bench', 'seat', 'wall', 'fixed_bar', 'raised_surface',
         'moving_implement', 'other')) + '.'


def _nonfoot_contact_timeline_prompt(candidate):
    region = candidate['contactRegion'].replace('_', ' ')
    target = region if region in {'upper back', 'pelvis', 'head'} else f"{candidate['side']} {region}"
    surface_key = candidate['expectedSurface']
    surface = surface_key.replace('_', ' ')
    locator = candidate.get('jointName')
    locator_note = (f'The {locator} marker is an anatomical locator, not a contact point.'
                    if locator else
                    'The marked center is context only, not a contact point.')
    return (f'Inspect the {target} body surface in this exact source frame. '
            f'{locator_note} '
            f'Does the body region visibly touch the candidate surface category {surface}? '
            f'For this category: {_contact_surface_referent(surface_key)}. '
            'Choose direct_contact for visible physical touching, no_contact for visible separation, '
            'or unresolved when the interface is hidden or ambiguous. Return one choice; '
            'joint-center position, proximity and stationarity are not contact evidence.')


class _QuestionCacheMiss(Exception):
    """Internal signal used to probe an exact legacy question cache without a call."""


def _review_model_identity(caption_images):
    """Bind cached visual evidence to the actual reviewer, not only source bytes."""
    owner = getattr(caption_images, '__self__', None)
    if owner is None:
        owner = caption_images
    marker = object()
    external_identity = getattr(owner, 'source_review_identity', marker)
    if external_identity is not marker:
        if not isinstance(external_identity, dict) or not external_identity:
            raise ValueError('source_review_identity must be a non-empty JSON object')
        if (not isinstance(external_identity.get('provider'), str)
                or not external_identity['provider'].strip()
                or isinstance(external_identity.get('reviewProtocolVersion'), bool)
                or not isinstance(external_identity.get('reviewProtocolVersion'), int)
                or external_identity['reviewProtocolVersion'] < 1):
            raise ValueError('source_review_identity requires provider and positive reviewProtocolVersion')
        try:
            normalized = json.loads(json.dumps(
                external_identity, sort_keys=True, separators=(',', ':'), allow_nan=False,
            ))
        except (TypeError, ValueError) as exc:
            raise ValueError('source_review_identity must contain only JSON values') from exc
        # Keep non-llama reviewers in a separate namespace. The identity is
        # attached by the code-owned callback, never accepted from model output.
        return {'sourceReviewer': normalized}
    from .bake_and_rank import source_review_model_identity
    settings = getattr(owner, 'settings', None)
    identity = source_review_model_identity(settings)
    return json.loads(json.dumps(identity, sort_keys=True, default=str))


_NONFOOT_STATES = ('stationary_support', 'moving', 'unsupported', 'unknown')
_NONFOOT_FIELDS = ('pelvis', 'upperBack', 'head',
                   *(f'{side}{part}' for side in ('left', 'right') for part in ('Hand', 'Knee', 'Ankle')))
# One table owns the non-foot state/surface vocabulary: the canonical surface
# field, the surfaces that count as actual stationary support, and the surfaces
# that may accompany an explicit unknown. Moving accepts the union of both sets.
_NONFOOT_PAIR_FIELD_SPECS = (
    ('pelvis', 'pelvisContactSurface', _SUPPORT_SURFACES, {'none', 'unknown'}),
    ('upperBack', 'upperBackContactSurface', _SUPPORT_SURFACES, {'none', 'unknown'}),
    ('head', 'headContactSurface', _SUPPORT_SURFACES, {'none', 'unknown'}),
    ('leftHand', 'leftHandContactSurface', _HAND_SUPPORT_SURFACES,
     _HAND_SUPPORT_SURFACES | {'moving_implement', 'none', 'unknown'}),
    ('rightHand', 'rightHandContactSurface', _HAND_SUPPORT_SURFACES,
     _HAND_SUPPORT_SURFACES | {'moving_implement', 'none', 'unknown'}),
    ('leftKnee', 'leftKneeContactSurface', _SUPPORT_SURFACES,
     _SUPPORT_SURFACES | {'none', 'unknown'}),
    ('rightKnee', 'rightKneeContactSurface', _SUPPORT_SURFACES,
     _SUPPORT_SURFACES | {'none', 'unknown'}),
    ('leftAnkle', 'leftAnkleContactSurface', _ANKLE_SUPPORT_SURFACES,
     _ANKLE_SUPPORT_SURFACES | {'none', 'unknown'}),
    ('rightAnkle', 'rightAnkleContactSurface', _ANKLE_SUPPORT_SURFACES,
     _ANKLE_SUPPORT_SURFACES | {'none', 'unknown'}),
)
_NONFOOT_PAIR_SPECS = {
    field: (surface_field, frozenset(stationary), frozenset(unknown_surfaces))
    for field, surface_field, stationary, unknown_surfaces in _NONFOOT_PAIR_FIELD_SPECS
}
_NONFOOT_CONTACT_SURFACE_FIELDS = frozenset(
    surface_field for _, surface_field, _, _ in _NONFOOT_PAIR_FIELD_SPECS)
_SUPPORT_ENUM_FIELDS = {
    **{field: _NONFOOT_STATES for field in _NONFOOT_FIELDS},
    **{f'{side}FootContactContinuity': {'continuous', 'intermittent', 'unknown'} for side in ('left', 'right')},
    **{f'{side}FootSurfaceMotion': {'stationary', 'moving', 'unknown'} for side in ('left', 'right')},
    **{f'{side}FootSurfaceOrientation': {'horizontal', 'inclined', 'vertical', 'unknown'} for side in ('left', 'right')},
    **{surface_field: set(stationary) | set(unknown_surfaces)
       for _, surface_field, stationary, unknown_surfaces in _NONFOOT_PAIR_FIELD_SPECS},
    'torsoSurface': {'horizontal', 'inclined', 'vertical', 'unknown'},
    'leftFoot': {'stationary_full_sole', 'stationary_forefoot', 'supported_dorsum', 'moving', 'unknown'},
    'rightFoot': {'stationary_full_sole', 'stationary_forefoot', 'supported_dorsum', 'moving', 'unknown'},
    'leftFootSurface': {'ground', 'raised_surface', 'unknown'},
    'rightFootSurface': {'ground', 'raised_surface', 'unknown'},
}


def _nonfoot_pair_tokens():
    """Legal atomic state:surface tokens derived from the shared pair table."""
    tokens = {}
    for field, (_, stationary, unknown_surfaces) in _NONFOOT_PAIR_SPECS.items():
        tokens[field] = tuple(
            f'{state}:{surface}'
            for state, surfaces in (
                ('stationary_support', sorted(stationary)),
                ('moving', sorted(stationary | unknown_surfaces)),
                ('unsupported', ('none',)),
                ('unknown', sorted(unknown_surfaces)),
            )
            for surface in surfaces)
    return tokens


def _support_observation_response_fields():
    """Response field -> advertised value vocabulary shared by prompt and schema."""
    fields = {field: choices for field, choices in _SUPPORT_ENUM_FIELDS.items()
              if field not in _NONFOOT_CONTACT_SURFACE_FIELDS}
    fields.update(_nonfoot_pair_tokens())
    return fields


def _support_observation_prompt_example():
    lines = [f'"{field}":"{"|".join(sorted(values))}"'
             for field, values in _support_observation_response_fields().items()]
    lines.extend((
        '"pelvisAndUpperBackSameSurface":true or false',
        '"handsSameHorizontalSurface":true or false',
        '"observations":"Brief visible evidence for the reported contacts"',
    ))
    return ',\n '.join(lines)


def _decode_support_pair_answer(answer):
    """Decode atomic non-foot state:surface tokens into canonical flat fields.

    Legacy flat state/surface pairs are accepted only when they form one of the
    same legal combinations. Malformed, unauthorized or duplicated claims return
    None so the response stays retryable instead of becoming a support contact.
    """
    tokens = _nonfoot_pair_tokens()
    decoded = dict(answer)
    for field, (surface_field, _, _) in _NONFOOT_PAIR_SPECS.items():
        if field not in decoded:
            if surface_field in decoded:
                return None
            continue
        value = decoded[field]
        if isinstance(value, str) and ':' in value:
            if surface_field in decoded or value not in tokens[field]:
                return None
            state, _, surface = value.partition(':')
            decoded[field] = state
            decoded[surface_field] = surface
            continue
        surface = decoded.get(surface_field)
        if not isinstance(value, str) or not isinstance(surface, str):
            return None
        if f'{value}:{surface}' not in tokens[field]:
            return None
    return decoded


def validated_body_support_answer(observed):
    """Return only current, schema-valid support claims; incomplete fields stay unknown."""
    if (not isinstance(observed, dict)
            or observed.get('status') != 'observed'
            or observed.get('source') != 'exact_source_visual_support_observation'
            or not isinstance(observed.get('sourceVideoSha256'), str)
            or not observed['sourceVideoSha256'].strip()
            or observed.get('policyVersion') != POLICY_VERSION):
        return None
    answer = observed.get('observation')
    if not isinstance(answer, dict) or not answer or set(answer) - _OBSERVATION_FIELDS:
        return None
    if not set(answer).intersection(_OBSERVATION_FIELDS - {'observations'}):
        return None
    answer = deepcopy(answer)
    for field, choices in _SUPPORT_ENUM_FIELDS.items():
        if field in answer and (not isinstance(answer[field], str) or answer[field] not in choices):
            return None
    for field in ('pelvisAndUpperBackSameSurface', 'handsSameHorizontalSurface'):
        if field in answer and not isinstance(answer[field], bool):
            return None
    if 'observations' in answer and not isinstance(answer['observations'], str):
        return None
    for region in ('pelvis', 'upperBack', 'head'):
        state, surface = answer.get(region), answer.get(f'{region}ContactSurface')
        if state == 'stationary_support' and surface not in _SUPPORT_SURFACES:
            answer.pop(region, None)
            answer.pop(f'{region}ContactSurface', None)
        elif state == 'unknown' and surface in _SUPPORT_SURFACES:
            answer.pop(region, None)
            answer.pop(f'{region}ContactSurface', None)
    if answer.get('pelvisAndUpperBackSameSurface') is True:
        same_surface = (
            answer.get('pelvis') == answer.get('upperBack') == 'stationary_support'
            and answer.get('pelvisContactSurface') in _SUPPORT_SURFACES
            and answer.get('pelvisContactSurface') == answer.get('upperBackContactSurface')
        )
        if not same_surface:
            answer.pop('pelvisAndUpperBackSameSurface', None)
    for side in ('left', 'right'):
        region = answer.get(f'{side}FootSurfaceImageRegion')
        if region is not None:
            try:
                polygon = np.asarray(region.get('polygonNormalizedXY'), dtype=float)
                valid = (polygon.ndim == 2 and polygon.shape[1] == 2 and len(polygon) >= 3
                         and np.isfinite(polygon).all() and np.all((polygon >= 0.) & (polygon <= 1.))
                         and region.get('sourceVideoSha256') == observed.get('sourceVideoSha256')
                         and region.get('sourceClock') == 'video_frame_zero_seconds'
                         and isinstance(region.get('nativeVideoFrameIndex'), int)
                         and region['nativeVideoFrameIndex'] >= 0)
                if valid:
                    edges = np.roll(polygon, -1, axis=0)-polygon
                    turns = edges[:, 0]*np.roll(edges[:, 1], -1)-edges[:, 1]*np.roll(edges[:, 0], -1)
                    uncertainty = float(region.get('uncertaintyPixels') or 0.)
                    valid = (bool(np.all(turns > 0.) or np.all(turns < 0.))
                             and np.isfinite(uncertainty) and uncertainty >= 0.)
            except (AttributeError, TypeError, ValueError):
                valid = False
            if not valid:
                answer.pop(f'{side}FootSurfaceImageRegion', None)
        if (answer.get(f'{side}Foot') == 'supported_dorsum'
                and answer.get(f'{side}FootSurface') != 'raised_surface'):
            answer.pop(f'{side}Foot', None)
            answer.pop(f'{side}FootSurface', None)
        if (answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}
                and answer.get(f'{side}FootSurface') not in {'ground', 'raised_surface'}):
            answer.pop(f'{side}Foot', None)
            answer.pop(f'{side}FootSurface', None)
        if answer.get(f'{side}Foot') == 'unknown':
            if answer.get(f'{side}FootSurface') in {'ground', 'raised_surface'}:
                answer.pop(f'{side}Foot', None)
                answer.pop(f'{side}FootSurface', None)
    for side in ('left', 'right'):
        if (answer.get(f'{side}Ankle') == 'stationary_support'
                and answer.get(f'{side}AnkleContactSurface') not in _ANKLE_SUPPORT_SURFACES):
            answer.pop(f'{side}Ankle', None)
            answer.pop(f'{side}AnkleContactSurface', None)
        if (answer.get(f'{side}Knee') == 'stationary_support'
                and answer.get(f'{side}KneeContactSurface') not in _SUPPORT_SURFACES):
            answer.pop(f'{side}Knee', None)
            answer.pop(f'{side}KneeContactSurface', None)
        if (answer.get(f'{side}Hand') == 'stationary_support'
                and answer.get(f'{side}HandContactSurface') not in _HAND_SUPPORT_SURFACES):
            answer.pop(f'{side}Hand', None)
    for field in _NONFOOT_FIELDS:
        if answer.get(field) == 'unsupported' and answer.get(f'{field}ContactSurface') != 'none':
            answer.pop(field, None)
            answer.pop(f'{field}ContactSurface', None)
    if answer.get('handsSameHorizontalSurface') is True and not (
            answer.get('leftHand') == answer.get('rightHand') == 'stationary_support'):
        answer.pop('handsSameHorizontalSurface', None)
    if not set(answer).intersection(_OBSERVATION_FIELDS - {'observations'}):
        return None
    return answer


def attach_reviewed_surface_region(observed, *, side, proposal, review_authority):
    """Resolve a short reviewed proposal ID to code-owned image geometry."""
    if (side not in {'left', 'right'} or not review_authority
            or proposal.get('sourceVideoSha256') != observed.get('sourceVideoSha256')):
        raise ValueError('Surface region review does not match exact source identity')
    result = deepcopy(observed)
    field = side+'FootSurfaceImageRegion'
    result.setdefault('observation', {})[field] = {
        'proposalId': proposal['choice'], 'polygonNormalizedXY': proposal['polygonNormalizedXY'],
        'sourceVideoSha256': proposal['sourceVideoSha256'],
        'sourceClock': 'video_frame_zero_seconds',
        'nativeVideoFrameIndex': proposal['sourceFrameIndex'],
        'nativeExposureTimeSec': proposal['sourceTimeSec'],
        'uncertaintyPixels': proposal.get('uncertaintyPixels'),
        'reviewAuthority': review_authority,
    }
    answer = validated_body_support_answer(result)
    if answer is None or field not in answer:
        raise ValueError('Invalid selected surface image region')
    return result


def _contract_primary_moving_regions(contract):
    contract = contract or {}
    regions = set(contract.get('primaryMovingRegions') or [])
    spec = contract.get('observableMotionSpec') or {}
    if isinstance(spec, dict):
        regions.update(spec.get('primaryMovingRegions') or [])
    return {str(region).casefold() for region in regions if region}


def body_support_required_anchors(contract=None, *, source_pose=None, observed=None):
    """Observed stationary origins can support an articulating body region."""
    source_reference = source_pose if isinstance(source_pose, dict) else {}
    source_pose = (source_reference.get('pose') if isinstance(source_reference.get('pose'), dict)
                   else source_reference)
    excluded = set()
    for region in _contract_primary_moving_regions(contract):
        excluded.update(_REGION_ANCHORS.get(region, ()))
    source_digest = str(source_reference.get('sourceVideoSha256')
                        or (source_pose or {}).get('sourceVideoSha256') or '').casefold()
    if (source_digest
            and source_digest == str((observed or {}).get('sourceVideoSha256') or '').casefold()):
        excluded.difference_update(
            name for name in observed_body_support_contacts(observed, source_pose)
            if stationary_source_track(source_pose, name))
    return tuple(name for name in BODY_SUPPORT_ANCHORS if name not in excluded)


def source_support_observation_needed(source_pose, evidence, exercise_motion_contract=None):
    """Request exact-source observation for explicit support intent or stationary tracks.

    A contract requests observation; it is not itself evidence of contact.
    """
    requirements = (exercise_motion_contract or {}).get('bodySupportRequirements')
    contract_requires_observation = isinstance(requirements, dict) and bool(
        requirements.get('required') or requirements.get('prohibited'))
    # Discovery hints request inspection only. They never assert that a contact
    # exists and never become hard support requirements.
    requires_discovery = bool(body_support_discovery_hint_items(exercise_motion_contract))
    return (contract_requires_observation or requires_discovery
            or bool(observed_stationary_sole_contacts(evidence)) or any(
        stationary_source_track(source_pose, name)
        for name in (*BODY_SUPPORT_ANCHORS, 'left_wrist', 'right_wrist',
                     'left_ankle', 'right_ankle', 'left_knee', 'right_knee')))


def body_support_discovery_hint_items(exercise_motion_contract):
    """Return validated discovery-only hints: regions to inspect, not requirements."""
    from .youtube import normalize_body_support_requirements

    value = normalize_body_support_requirements(
        (exercise_motion_contract or {}).get('bodySupportDiscoveryHints'))
    if value is None:
        return []
    hints = []
    seen = set()
    for hint in (*value['required'], *value['prohibited']):
        # Inferred intent scopes the body region, not its actual source surface.
        hint.pop('surface', None)
        identity = (hint['region'], hint['side'], hint.get('surface', 'any'),
                    hint.get('contactMode', 'stationary'))
        if identity in seen:
            continue
        seen.add(identity)
        hints.append(hint)
    return hints


def body_support_requirement_observation_fields(exercise_motion_contract):
    """Map typed support requirements to exact observation fields needed to decide them."""
    requirements = (exercise_motion_contract or {}).get('bodySupportRequirements') or {}
    fields = set()
    for disposition in ('required', 'prohibited'):
        for item in requirements.get(disposition, []) or []:
            region, side = item.get('region'), item.get('side')
            sides = ('left', 'right') if side in {'both', 'either'} else (side,)
            name = {'upper_back': 'upperBack'}.get(region, str(region or '').title())
            for current_side in sides:
                field = name if region in {'pelvis', 'head', 'upper_back'} else f'{current_side}{name}'
                if field in _SUPPORT_ENUM_FIELDS:
                    fields.add(field)
                    if item.get('surface', 'any') != 'any':
                        surface_field = f'{field}ContactSurface'
                        if field.endswith('Foot'):
                            surface_field = f'{field}Surface'
                        if surface_field in _SUPPORT_ENUM_FIELDS:
                            fields.add(surface_field)
    return fields


def body_support_discovery_observation_fields(exercise_motion_contract):
    """Union requirement and hint fields for source discovery only.

    Callers use the result to decide which coarse observation fields to request
    and when a cached observation is complete. It is not a hard requirement
    list: validators keep reading ``bodySupportRequirements`` alone.
    """
    fields = set(body_support_requirement_observation_fields(exercise_motion_contract))
    hints = body_support_discovery_hint_items(exercise_motion_contract)
    if hints:
        hint_fields = body_support_requirement_observation_fields(
            {'bodySupportRequirements': {'required': hints, 'prohibited': []}})
        fields.update(hint_fields)
        for field in hint_fields:
            surface_field = f'{field}Surface' if field.endswith('Foot') else f'{field}ContactSurface'
            if surface_field in _SUPPORT_ENUM_FIELDS:
                fields.add(surface_field)
    return fields


def body_support_discovery_request_identity(exercise_motion_contract):
    """Stable identity for a hint-bearing observation request, or None without hints."""
    hints = body_support_discovery_hint_items(exercise_motion_contract)
    if not hints:
        return None
    payload = {
        'policyVersion': POLICY_VERSION,
        'hints': sorted(hints, key=lambda hint: json.dumps(hint, sort_keys=True)),
        'observationFields': sorted(
            body_support_discovery_observation_fields(exercise_motion_contract)),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def body_support_observation_covers(observation, required_fields=()):
    answer = validated_body_support_answer(observation)
    return answer is not None and all(field in answer for field in required_fields)


def _merge_support_observations(previous, current):
    old_answer = validated_body_support_answer(previous)
    if old_answer is None:
        return current, {}
    new_answer = validated_body_support_answer(current)
    if new_answer is None:
        return current, {}
    merged = dict(old_answer)
    conflicts = dict(previous.get('observationConflicts') or {})
    for field, value in new_answer.items():
        old_value = merged.get(field)
        if old_value in (None, 'unknown'):
            merged[field] = value
        elif value not in (None, 'unknown') and value != old_value:
            conflicts[field] = list(dict.fromkeys([*(conflicts.get(field) or []), old_value, value]))
            if field in _SUPPORT_ENUM_FIELDS:
                merged[field] = 'unknown'
            else:
                merged.pop(field, None)
    result = dict(current, observation=merged)
    history = list(previous.get('previousObservations') or [])
    prior = {key: previous.get(key) for key in (
        'source', 'sourceVideoSha256', 'policyVersion', 'sourceClock', 'observation', 'rawResponse')
        if key in previous}
    if prior and (not history or history[-1] != prior):
        history.append(prior)
    if history:
        result['previousObservations'] = history
    if conflicts:
        result['observationConflicts'] = conflicts
    return result, conflicts


def _support_identity_landmarks(video_path, digest):
    from .foot_contact_observation import load_cached_foot_landmarks
    observed = load_cached_foot_landmarks(video_path)
    return observed if (isinstance(observed, dict) and observed.get('available')
                        and observed.get('sourceVideoSha256') == digest) else None


def _mark_support_components(frame, source_frame):
    """Code binds opaque component labels to observed source joints."""
    import cv2
    height, width = frame.shape[:2]
    joints = source_frame.get('joints') or {}
    components = {}
    for label, joint in (('A', 'left_ankle'), ('B', 'right_ankle'),
                         ('C', 'left_knee'), ('D', 'right_knee'),
                         ('E', 'left_wrist'), ('F', 'right_wrist')):
        point = joints.get(joint) or {}
        image = np.asarray(point.get('image', []), dtype=float)
        if (point.get('confidence', 0.) >= .8 and image.shape == (2,)
                and np.isfinite(image).all() and np.all((image >= 0.) & (image <= 1.))):
            components[label] = {'sourceJoint': joint, 'imagePoint': image.tolist()}
    hips = [joints.get(side+'_hip') or {} for side in ('left', 'right')]
    if all(point.get('confidence', 0.) >= .8 for point in hips):
        image = np.asarray([point.get('image', []) for point in hips], dtype=float)
        if image.shape == (2, 2) and np.isfinite(image).all() and np.all((image >= 0.) & (image <= 1.)):
            components['P'] = {'sourceJoint': 'pelvis_from_observed_hips',
                               'imagePoint': image.mean(axis=0).tolist()}
    for label, point in components.items():
        x, y = np.rint(np.asarray(point['imagePoint'])*[width, height]).astype(int)
        cv2.circle(frame, (x, y), 4, (0, 230, 255), 2)
        cv2.putText(frame, label, (x+5, y-5), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 3)
        cv2.putText(frame, label, (x+5, y-5), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 230, 255), 1)
    return components


def _support_identity_fields():
    fields = {}
    for side, foot, knee, hand in (('left', 'A', 'C', 'E'), ('right', 'B', 'D', 'F')):
        for suffix in ('', 'Surface', 'SurfaceMotion', 'SurfaceOrientation', 'ContactContinuity'):
            fields[foot+suffix] = side+'Foot'+suffix
        fields[knee] = side+'Knee'
        fields[knee+'ContactSurface'] = side+'KneeContactSurface'
        fields[foot+'Ankle'] = side+'Ankle'
        fields[foot+'AnkleContactSurface'] = side+'AnkleContactSurface'
        fields[hand] = side+'Hand'
        fields[hand+'ContactSurface'] = side+'HandContactSurface'
    fields.update(P='pelvis', PContactSurface='pelvisContactSurface')
    return fields


def observe_body_support(video_path, caption_images, cache_dir, *, existing_observation=None,
                         require_knee_observation=False, require_labeled_identity=False,
                         required_observation_fields=(), request_identity=None):
    """One cached, target-blind contact observation for the exact selected cut."""
    video_path, cache_dir = Path(video_path), Path(cache_dir)
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    review_identity = _review_model_identity(caption_images)
    cache = cache_dir / f'body-support-{digest}-v{POLICY_VERSION}.json'
    labeled_cache = cache.with_name(cache.stem+'-labeled.json')
    identity_source = _support_identity_landmarks(video_path, digest) if require_labeled_identity else None
    identity_digest = (hashlib.sha256(json.dumps(identity_source, sort_keys=True).encode()).hexdigest()
                       if identity_source is not None else None)
    observations = []
    prior_observation = (existing_observation if isinstance(existing_observation, dict)
                         and existing_observation.get('sourceVideoSha256') == digest
                         and (caption_images is None
                              or existing_observation.get('reviewIdentity') == review_identity) else None)
    if (validated_body_support_answer(existing_observation) is not None
            and (caption_images is None or existing_observation.get('reviewIdentity') == review_identity)):
        observations.append(existing_observation)
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cached = None
        observations.append(cached)
    if labeled_cache.is_file():
        try:
            observations.insert(0, json.loads(labeled_cache.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass
    for cached in observations:
        if (not isinstance(cached, dict) or caption_images is not None
                and cached.get('reviewIdentity') != review_identity):
            continue
        if request_identity is not None and cached.get('requestIdentity') != request_identity:
            # Hints changed the requested observation scope. Keep the old
            # answer as history at most; do not reuse it for this request.
            continue
        if (require_labeled_identity and isinstance(cached, dict)
                and cached.get('status') == 'unknown'
                and cached.get('reason') == 'support_source_frame_unavailable'
                and cached.get('sourceVideoSha256') == digest
                and cached.get('policyVersion') == POLICY_VERSION):
            return cached
        if require_labeled_identity and (
                not isinstance(cached, dict) or identity_digest is None
                or (cached.get('identityMarkers') or {}).get('sourceLandmarksSha256') != identity_digest):
            continue
        if (isinstance(cached, dict) and cached.get('status') == 'unknown'
                and cached.get('reason') != 'support_observation_schema_invalid'
                and (not require_knee_observation
                     or cached.get('reason') == 'support_source_frame_unavailable')
                and cached.get('policyVersion') == POLICY_VERSION
                and cached.get('sourceVideoSha256') == digest):
            return cached
        answer = validated_body_support_answer(cached)
        if (prior_observation is None and answer is not None
                and cached.get('sourceVideoSha256') == digest):
            prior_observation = cached
        conflicts = cached.get('observationConflicts') or {}
        if set(required_observation_fields).intersection(conflicts):
            return cached
        missing_hand_surface = answer is not None and any(
            cached['observation'].get(f'{side}Hand') == 'stationary_support'
            and f'{side}HandContactSurface' not in cached['observation']
            for side in ('left', 'right'))
        if (answer is not None and cached.get('sourceVideoSha256') == digest
                and (not missing_hand_surface or caption_images is None)
                and (not require_knee_observation or all(
                    f'{side}Knee' in answer for side in ('left', 'right')))
                and body_support_observation_covers(cached, required_observation_fields)):
            unresolved = set((cached.get('observation') or {})) - set(answer)
            return {**cached, 'observation': answer,
                    'unresolvedClaims': sorted(set(cached.get('unresolvedClaims') or []) | unresolved)}
        # Malformed responses remain retryable; valid observations are reused.
    if caption_images is None:
        return {'status': 'unknown', 'reason': 'support_observer_unavailable'}
    identity_source = identity_source or _support_identity_landmarks(video_path, digest)
    if require_labeled_identity and identity_source is None:
        return {'status': 'unknown', 'reason': 'support_source_identity_unavailable',
                'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
                'reviewIdentity': review_identity}
    if identity_source is not None:
        identity_digest = hashlib.sha256(json.dumps(identity_source, sort_keys=True).encode()).hexdigest()
        cache = labeled_cache
    import cv2
    cache_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    paths = []
    identity_frames = []
    try:
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if identity_source is not None and len(identity_source.get('frames', [])) != count:
            return {'status': 'unknown', 'reason': 'support_source_identity_frame_mismatch',
                    'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
                    'reviewIdentity': review_identity}
        for index, ratio in enumerate((.05, .25, .5, .75, .95)):
            native_index = round(max(0, count-1)*ratio)
            capture.set(cv2.CAP_PROP_POS_FRAMES, native_index)
            ok, frame = capture.read()
            if not ok:
                return {'status': 'unknown', 'reason': 'support_source_frame_unavailable',
                        'reviewIdentity': review_identity}
            if identity_source is not None:
                source_frame = identity_source['frames'][native_index]
                if not np.isfinite(fps) or fps <= 0 or abs(source_frame['timeSeconds']-native_index/fps) > 1e-6:
                    return {'status': 'unknown', 'reason': 'support_source_identity_clock_mismatch',
                            'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
                            'reviewIdentity': review_identity}
                components = _mark_support_components(frame, source_frame)
            path = cache_dir / f'{digest}-support-{index}{"-labeled" if identity_source is not None else ""}.jpg'
            if not cv2.imwrite(str(path), frame):
                raise OSError(f'Cannot write support observation frame: {path}')
            paths.append(path)
            if identity_source is not None:
                identity_frames.append({'nativeVideoFrameIndex': native_index,
                                        'nativeTimeSec': source_frame['timeSeconds'],
                                        'components': components, 'path': str(path),
                                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    finally:
        capture.release()
    prompt = ('''Inspect these chronological frames of the SAME source movement.
Report only visible support contacts; do not judge exercise correctness or infer
contacts from an exercise name. Stationary means resting at the same place on
the surface throughout the samples. A body part merely near a surface is NOT
confirmed support. stationary_support requires visible direct contact throughout
the samples. unsupported means visibly no direct external support even if the
body part is stationary; report unsupported only with contact surface none.
Choose unknown when hidden or ambiguous. Do not mistake the left/right sides of
the image for the person's anatomical left/right.
Return JSON only with these exact fields:
{''' + _support_observation_prompt_example() + '''}
Horizontal describes the actual surface, not its apparent screen angle.
supported_dorsum means visible top-of-shoe/instep support on a raised surface;
it does not assert that the ankle or one material patch stays fixed. Report
surface motion/orientation only when visible; hidden or uncertain stays unknown.
ContactSurface means DIRECT visible contact with that surface, not indirect
support through the feet. A free-standing torso has contact surface none even
when upright and stationary. Require direct contact throughout the samples.
For hands, moving_implement means a held object moving with the athlete;
fixed_bar means an externally fixed bar supporting the athlete.
Ankle support means direct restraint by an external fixed support, independently
of sole or forefoot contact. It does not establish a contact face or plane height.
Full sole means heel AND forefoot visibly planted. A lifted heel is forefoot.
Do not assume both feet or hands agree when only one is visible.
For handsSameHorizontalSurface, require both hands visibly resting on the same
level surface throughout; a bar, handle, wall or hidden contact is not evidence
of a shared horizontal surface.
For pelvis, upperBack, head, knee, ankle and hand, return one atomic
state:surface token from its listed choices. stationary_support lists only
actual support surfaces, unsupported appears only with none, and moving keeps
its listed surfaces, none or unknown. Do not split these into separate fields.''')
    prompt += '\n' + _contact_surface_referent_guidance()
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {
                  **{field: {'type': 'string', 'enum': sorted(choices)}
                     for field, choices in _support_observation_response_fields().items()},
                  'pelvisAndUpperBackSameSurface': {'type': 'boolean'},
                  'handsSameHorizontalSurface': {'type': 'boolean'},
                  'observations': {'type': 'string'},
              }}
    field_map = _support_identity_fields() if identity_frames else {}
    if field_map:
        inverse = {value: key for key, value in field_map.items()}
        for field, label in sorted(inverse.items(), key=lambda item: -len(item[0])):
            prompt = prompt.replace('"'+field+'"', '"'+label+'"')
        prompt += ('\nThe yellow component markers define identity: A/B are feet, C/D knees, '
                   'E/F hands, P pelvis. Use marker identity only, never anatomical or image-side '
                   'guessing. AAnkle/BAnkle ask external restraint at the corresponding foot marker. '
                   'Choose unknown for any component not marked throughout the samples.')
        schema['properties'] = {inverse.get(key, key): value for key, value in schema['properties'].items()}
    # Image regions are code-owned observations, never requested numeric output.
    schema['required'] = sorted(schema['properties'])
    raw = caption_images(frame_paths=paths, prompt=prompt, max_tokens=1000, temperature=0.,
                         json_response=True, response_schema=schema, disable_reasoning=True)
    try:
        answer = json.loads(raw[raw.index('{'):raw.rindex('}')+1])
        if not isinstance(answer, dict):
            raise ValueError('Support response must be an object')
        if field_map:
            legacy_surface_labels = {inverse[field] for field in _NONFOOT_CONTACT_SURFACE_FIELDS
                                     if field in inverse}
            if set(answer)-set(schema['properties'])-legacy_surface_labels:
                raise ValueError('Support response used an unbound component identity')
            answer = {field_map.get(key, key): value for key, value in answer.items()}
            marked = set.intersection(*(set(frame['components']) for frame in identity_frames))
            for label, field in field_map.items():
                if label[0] not in marked and field in answer:
                    if field in _NONFOOT_PAIR_SPECS:
                        answer[field] = 'unknown:unknown'
                        answer.pop(_NONFOOT_PAIR_SPECS[field][0], None)
                    elif field not in _NONFOOT_CONTACT_SURFACE_FIELDS:
                        answer[field] = 'unknown'
    except (ValueError, TypeError):
        result = {'status': 'unknown', 'reason': 'support_observation_unparseable'}
        if request_identity is not None:
            result['requestIdentity'] = request_identity
        return result
    response_answer = answer
    answer = _decode_support_pair_answer(answer)
    if answer is None:
        result = {'status': 'unknown', 'reason': 'support_observation_schema_invalid',
                  'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
                  'observation': response_answer, 'rawResponse': raw,
                  'reviewIdentity': review_identity}
        if request_identity is not None:
            result['requestIdentity'] = request_identity
        cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    result = {'status': 'observed', 'source': 'exact_source_visual_support_observation',
              'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
              'observation': answer, 'sourceClock': 'video_frame_zero_seconds',
              'reviewIdentity': review_identity}
    if request_identity is not None:
        result['requestIdentity'] = request_identity
    if identity_frames:
        result['identityMarkers'] = {'sourceVideoSha256': digest,
                                     'sourceLandmarksSha256': identity_digest,
                                     'fieldMap': field_map, 'frames': identity_frames}
        if (isinstance(existing_observation, dict)
                and existing_observation.get('sourceVideoSha256') == digest
                and existing_observation.get('reviewIdentity') == review_identity):
            for key, value in existing_observation.items():
                if (key.startswith('contactTimeline') and isinstance(value, dict)
                        and value.get('reviewIdentity') == review_identity):
                    result[key] = deepcopy(value)
    validated = validated_body_support_answer(result)
    if validated is None:
        result = {'status': 'unknown', 'reason': 'support_observation_schema_invalid',
                  'sourceVideoSha256': digest, 'policyVersion': POLICY_VERSION,
                  'observation': answer, 'rawResponse': raw,
                  'reviewIdentity': review_identity}
        if request_identity is not None:
            result['requestIdentity'] = request_identity
        cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    result['unresolvedClaims'] = sorted(set(answer) - set(validated))
    result['observation'] = validated
    if prior_observation is not None:
        result, _ = _merge_support_observations(prior_observation, result)
        if request_identity is not None:
            result['requestIdentity'] = request_identity
    result['rawResponse'] = raw
    cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def _contact_region_for_locator(joint):
    if joint in {'left_shoulder', 'right_shoulder'}:
        return 'upper_back'
    return 'hand' if joint.endswith('_wrist') else joint.rsplit('_', 1)[-1]


def _contact_timeline_candidates(source_pose, evidence):
    """Select bounded observations where patch contact authority is unresolved."""
    from .contact_constraints import contact_frame_bounds, is_stationary_contact, motion_support_contacts
    pose = (source_pose.get('pose') if isinstance(source_pose, dict)
            and isinstance(source_pose.get('pose'), dict) else source_pose)
    pose = pose if isinstance(pose, dict) else {}
    if pose.get('coordinateSpace') != 'normalized_image_xy':
        return []
    frames = pose.get('frames') or []
    patch = (evidence or {}).get('footPatchEvidence') or {}
    times = patch.get('sourceTimesSec')
    feet = patch.get('feet') or {}
    try:
        cadences = np.diff(np.asarray(times, dtype=float))
        cadences = cadences[np.isfinite(cadences) & (cadences > 0.)]
    except (TypeError, ValueError):
        cadences = np.asarray([], dtype=float)
    cadence = float(np.median(cadences)) if len(cadences) else None
    candidates = []
    answer = validated_body_support_answer((evidence or {}).get('bodySupportObservation')) or {}
    for side in ('left', 'right') if cadence is not None else ():
        foot_patch = feet.get(side) or {}
        states = foot_patch.get('states') or []
        stationary_ranges = [
            contact_frame_bounds(contact, len(states))
            for contact in motion_support_contacts(evidence)
            if contact.get('jointName') == f'{side}_foot'
            and contact.get('contactState') in {'full_sole', 'toe_only', 'heel_only'}
            and is_stationary_contact(contact)
        ]
        intervals = ((evidence or {}).get('feet') or {}).get(side, {}).get('contactIntervals') or []
        if (not intervals and answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}
                and answer.get(f'{side}FootSurface') == 'ground'
                and stationary_source_track(pose, f'{side}_ankle')):
            # Stationarity proposes a review span; visual review still owns contact.
            source_times = [float(frame['sourceTimeSec']) for frame in frames
                            if isinstance(frame.get('sourceTimeSec'), (int, float))
                            and np.isfinite(frame['sourceTimeSec'])]
            if len(source_times) > 1:
                intervals = [{'contactMotion': 'stationary', 'sourceTimeBasis': patch.get('sourceTimeBasis'),
                              'sourceStartTimeSec': min(source_times), 'sourceEndTimeSec': max(source_times)}]
        intervals = list(intervals)
        unknown_runs = []
        for index, state in enumerate(states):
            if state != 'unknown' or index >= len(times):
                continue
            if unknown_runs and index == unknown_runs[-1][-1] + 1:
                unknown_runs[-1].append(index)
            else:
                unknown_runs.append([index])
        for run in unknown_runs:
            intervals.append({'contactMotion': 'review_only',
                              'sourceTimeBasis': patch.get('sourceTimeBasis'),
                              'sourceStartTimeSec': times[run[0]],
                              'sourceEndTimeSec': times[run[-1]]})
        unknown_intervals = []
        for interval_index, interval in enumerate(intervals):
            if (interval.get('contactMotion') not in {'stationary', 'review_only'}
                    or interval.get('sourceTimeBasis') != patch.get('sourceTimeBasis')):
                continue
            try:
                start = float(interval['sourceStartTimeSec'])
                end = float(interval['sourceEndTimeSec'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if not np.isfinite([start, end]).all() or end < start:
                continue
            pose_samples = []
            for pose_index, frame in enumerate(frames):
                try:
                    source_time = float(frame['sourceTimeSec'])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                joints = frame.get('joints') or {}
                point = joints.get(f'{side}_ankle')
                confidence = (frame.get('jointConfidence') or {}).get(f'{side}_ankle', 0.)
                heel, toe = joints.get(f'{side}_heel'), joints.get(f'{side}_toe')
                heel_confidence = (frame.get('jointConfidence') or {}).get(f'{side}_heel', 0.)
                toe_confidence = (frame.get('jointConfidence') or {}).get(f'{side}_toe', 0.)
                if (not start <= source_time <= end or point is None or confidence < .5
                        or len(point) < 2 or not np.isfinite(point[:2]).all()
                        or any(coord < 0. or coord > 1. for coord in point[:2])):
                    continue
                try:
                    patch_index = min(range(len(times)),
                                      key=lambda index: abs(float(times[index]) - source_time))
                    patch_time = float(times[patch_index])
                except (TypeError, ValueError, OverflowError):
                    continue
                if (patch_index >= len(states) or not np.isfinite(patch_time)
                        or abs(patch_time - source_time) > cadence * .5 + 1e-6):
                    continue
                patch_landmarks = (foot_patch.get('heelImageObservations') or [])
                if patch_index < len(patch_landmarks):
                    observation = patch_landmarks[patch_index]
                    try:
                        patch_confidence = min(float(observation.get('heelConfidence') or 0.),
                                               float(observation.get('toeConfidence') or 0.))
                        patch_matches_time = abs(float(observation.get('sourceTimeSec')) - patch_time) <= 1e-6
                    except (AttributeError, TypeError, ValueError, OverflowError):
                        patch_confidence, patch_matches_time = 0., False
                    if isinstance(observation, dict) and patch_matches_time and patch_confidence >= .8:
                        try:
                            width, height = float(pose['imageWidth']), float(pose['imageHeight'])
                            if not np.isfinite([width, height]).all() or min(width, height) <= 0.:
                                continue
                            # Patch geometry uses image-height units; crops use normalized image XY.
                            heel, toe = (np.asarray(observation[key], dtype=float)
                                         * [height / width, 1.] for key in ('heelImagePoint', 'toeImagePoint'))
                            heel, toe = heel.tolist(), toe.tolist()
                        except (KeyError, TypeError, ValueError, OverflowError):
                            continue
                        heel_confidence = toe_confidence = patch_confidence
                if (heel is None or toe is None or min(heel_confidence, toe_confidence) < .8
                        or any(value is None or len(value) < 2 or not np.isfinite(value[:2]).all()
                               or any(coord < 0. or coord > 1. for coord in value[:2])
                               for value in (heel, toe))):
                    continue
                state = str(states[patch_index]).casefold()
                if interval.get('contactMotion') == 'review_only' and state != 'unknown':
                    continue
                if (state != 'unknown' and (state not in {'full_sole', 'toe_only', 'heel_only'}
                        or any(first <= patch_index <= last for first, last in stationary_ranges))):
                    continue
                pose_samples.append({
                    'side': side, 'poseFrameIndex': pose_index,
                    'landmark': 'foot',
                    'sourceTimeSec': source_time,
                    'ankle': [float(point[0]), float(point[1])],
                    'heel': [float(heel[0]), float(heel[1])],
                    'toe': [float(toe[0]), float(toe[1])],
                    'point': [float((heel[0] + toe[0]) * .5),
                              float((heel[1] + toe[1]) * .5)],
                    'knee': joints.get(f'{side}_knee'),
                    'intervalIndex': interval_index,
                    'reviewOnly': interval.get('contactMotion') == 'review_only',
                    'stationaryStartTimeSec': start,
                    'stationaryEndTimeSec': end,
                })
            if pose_samples:
                # Boundary and interior samples expose variation without turning
                # sparse visual observations into an interval-wide contact claim.
                indexes = sorted({0, len(pose_samples) // 2, len(pose_samples) - 1})
                unknown_intervals.extend(pose_samples[index] for index in indexes)
        candidates.extend(unknown_intervals)

    # Any coarse stationary-contact claim that can become a fitted anchor must
    # receive the same exact-time visual check. Pose stationarity alone is not contact.
    source_frames = pose.get('frames') or []
    claims = []
    for region, joints in (
        ('pelvis', ('pelvis',)), ('upperBack', ('left_shoulder', 'right_shoulder')),
        ('head', ('head',)),
    ):
        if answer.get(region) == 'stationary_support':
            claims.extend((joint, answer.get(f'{region}ContactSurface')) for joint in joints)
    for side in ('left', 'right'):
        for region in ('Hand', 'Ankle', 'Knee'):
            if answer.get(f'{side}{region}') == 'stationary_support':
                claims.append((f'{side}_{region.casefold() if region != "Hand" else "wrist"}',
                               answer.get(f'{side}{region}ContactSurface')))
    for joint, surface in claims:
        if (surface not in _SUPPORT_SURFACES
                and surface not in _HAND_SUPPORT_SURFACES
                and surface not in _ANKLE_SUPPORT_SURFACES):
            continue
        if (not stationary_source_track(pose, joint)
                and _contact_region_for_locator(joint) != 'upper_back'):
            continue
        side = joint.split('_', 1)[0] if joint.startswith(('left_', 'right_')) else 'center'
        landmark = 'knee' if joint.endswith('_knee') else 'joint'
        valid = []
        for pose_index, frame in enumerate(source_frames):
            try:
                source_time = float(frame['sourceTimeSec'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            joints = frame.get('joints') or {}
            point = joints.get(joint)
            confidence = (frame.get('jointConfidence') or {}).get(joint, 0.)
            if (not np.isfinite(source_time) or source_time < 0.
                    or point is None or confidence < .5
                    or len(point) < 2 or not np.isfinite(point[:2]).all()
                    or any(value < 0. or value > 1. for value in point[:2])):
                continue
            valid.append({'side': side, 'landmark': landmark, 'jointName': joint,
                          'contactRegion': _contact_region_for_locator(joint),
                          'regionPoints': [joints[name][:2] for name in (
                                              'left_shoulder', 'right_shoulder',
                                              'spine1', 'spine2', 'spine3', 'pelvis',
                                              'left_hip', 'right_hip')
                                           if isinstance(joints.get(name), (list, tuple, np.ndarray))
                                           and len(joints[name]) >= 2
                                            and (frame.get('jointConfidence') or {}).get(name, 0.) >= .5
                                           and np.isfinite(joints[name][:2]).all()]
                                          if joint.endswith('_shoulder') else [],
                          'poseFrameIndex': pose_index, 'sourceTimeSec': source_time,
                          'point': [float(point[0]), float(point[1])],
                          'expectedSurface': surface,
                          'stationaryStartTimeSec': source_time,
                          'stationaryEndTimeSec': source_time})
        if valid:
            indexes = sorted({0, len(valid) - 1})
            candidates.extend(valid[index] for index in indexes)

    upper_back_surface = answer.get('upperBackContactSurface')
    if (answer.get('upperBack') == 'stationary_support'
            and upper_back_surface in _SUPPORT_SURFACES):
        context_names = ('left_shoulder', 'right_shoulder', 'spine1', 'spine2', 'spine3',
                         'pelvis', 'left_hip', 'right_hip')
        regional_frames = []
        for pose_index, frame in enumerate(source_frames):
            try:
                source_time = float(frame['sourceTimeSec'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if not np.isfinite(source_time) or source_time < 0.:
                continue
            joints = frame.get('joints') or {}
            confidence = frame.get('jointConfidence') or {}
            valid_context = [
                (name, joints[name][:2]) for name in context_names
                if isinstance(joints.get(name), (list, tuple, np.ndarray))
                and len(joints[name]) >= 2
                and confidence.get(name, 0.) >= .5
                and np.isfinite(joints[name][:2]).all()
                and np.all((np.asarray(joints[name][:2], dtype=float) >= 0.)
                           & (np.asarray(joints[name][:2], dtype=float) <= 1.))
            ]
            points = [point for _, point in valid_context]
            if len(points) < 2 or not {'left_shoulder', 'right_shoulder'}.intersection(
                    name for name, _ in valid_context):
                continue
            center = np.mean(np.asarray(points, dtype=float), axis=0)
            regional_frames.append({
                'side': 'center', 'landmark': 'region', 'contactRegion': 'upper_back',
                'regionPoints': points, 'poseFrameIndex': pose_index,
                'sourceTimeSec': source_time, 'point': center.tolist(),
                'expectedSurface': upper_back_surface,
                'stationaryStartTimeSec': source_time, 'stationaryEndTimeSec': source_time,
                'sourceTrackStationary': False,
            })
        if regional_frames:
            # Boundaries plus an interior phase sample preserve variation evidence.
            indexes = sorted({0, len(regional_frames) // 2, len(regional_frames) - 1})
            candidates.extend(regional_frames[index] for index in indexes)

    # A raised foot can visibly contact its support while its ankle moves with
    # the exercise. Ask about the foot region at exact source times without
    # turning that moving locator into a stationary joint restraint or asking
    # the observer to infer full-sole contact from an instep crop.
    for side in ('left', 'right'):
        foot_state = answer.get(f'{side}Foot')
        if (answer.get(f'{side}FootSurface') != 'raised_surface'
                or foot_state not in {'stationary_full_sole', 'stationary_forefoot'}):
            continue
        regional_frames = []
        for pose_index, frame in enumerate(frames):
            try:
                source_time = float(frame['sourceTimeSec'])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            joints = frame.get('joints') or {}
            confidence = frame.get('jointConfidence') or {}
            point = joints.get(f'{side}_ankle')
            if (not np.isfinite(source_time) or source_time < 0.
                    or not isinstance(point, (list, tuple, np.ndarray)) or len(point) < 2
                    or confidence.get(f'{side}_ankle', 0.) < .5
                    or not np.isfinite(point[:2]).all()
                    or np.any((np.asarray(point[:2], dtype=float) < 0.)
                              | (np.asarray(point[:2], dtype=float) > 1.))):
                continue
            regional_frames.append({
                'side': side, 'landmark': 'region', 'contactRegion': 'foot',
                'regionPoints': [], 'poseFrameIndex': pose_index,
                'sourceTimeSec': source_time, 'point': [float(point[0]), float(point[1])],
                'expectedSurface': 'raised_surface',
                'stationaryStartTimeSec': source_time, 'stationaryEndTimeSec': source_time,
                'sourceTrackStationary': False,
            })
        if regional_frames:
            # Raised-foot readiness represents a source-wide stationary support
            # claim, so every canonical pose frame must receive a direct review.
            candidates.extend(regional_frames)

    deduplicated = {}
    for row in candidates:
        key = (row['side'], row.get('landmark', 'foot'), row.get('jointName'),
               row['poseFrameIndex'])
        if key not in deduplicated or not row.get('reviewOnly'):
            deduplicated[key] = row
    ordered = sorted(deduplicated.values(), key=lambda row: (row['sourceTimeSec'], row['side']))
    for row in ordered:
        row['sampleId'] = (f"contact-{row['side']}-knee-pose-{row['poseFrameIndex']}"
                           if row.get('landmark') == 'knee'
                           else f"contact-region-foot-{row['side']}-pose-{row['poseFrameIndex']}"
                           if row.get('landmark') == 'region' and row.get('contactRegion') == 'foot'
                           else f"contact-region-{row['contactRegion']}-pose-{row['poseFrameIndex']}"
                           if row.get('landmark') == 'region'
                           else f"contact-{row['jointName']}-pose-{row['poseFrameIndex']}"
                           if row.get('landmark') == 'joint'
                           else f"contact-{row['side']}-pose-{row['poseFrameIndex']}")
        if row.get('landmark') != 'region':
            row['sourceTrackStationary'] = (stationary_source_track(pose, row['jointName'])
                                            if row.get('jointName') else not row.get('reviewOnly', False))
    return ordered


def _render_contact_timeline_crop(cv2, frame, candidate, *, mark_target=True):
    """Mark a code-selected contact landmark and keep its label outside source pixels."""
    frame_height, frame_width = frame.shape[:2]
    radius_x = max(16, int(round(frame_width * .075)))
    radius_y_top = max(8, int(round(frame_height * .025)))
    radius_y_bottom = max(24, int(round(frame_height * .13)))
    target = candidate.get('point') or candidate.get('ankle') or candidate.get('knee')
    ankle_x, ankle_y = target
    for context_point in (candidate.get('heel'), candidate.get('toe'), candidate.get('knee'),
                          *(candidate.get('regionPoints') or [])):
        if isinstance(context_point, (list, tuple)) and len(context_point) >= 2 \
                and np.isfinite(context_point[:2]).all():
            delta = np.abs((np.asarray(context_point[:2]) - [ankle_x, ankle_y])
                           * [frame_width, frame_height])
            radius_x = max(radius_x, int(np.ceil(delta[0])) + 8)
            radius_y_top = max(radius_y_top, int(np.ceil(delta[1])) + 8)
            radius_y_bottom = max(radius_y_bottom, int(np.ceil(delta[1])) + 8)
    if candidate.get('landmark') in {'joint', 'knee', 'region'}:
        # A hand can contact a surface above its wrist; body regions are not foot-shaped.
        radius_y_top = max(radius_y_top, radius_y_bottom)
    x = int(round(ankle_x * frame_width))
    y = int(round(ankle_y * frame_height))
    x0, x1 = max(0, x - radius_x), min(frame_width, x + radius_x)
    y0, y1 = max(0, y - radius_y_top), min(frame_height, y + radius_y_bottom)
    if x1 <= x0 or y1 <= y0:
        return None

    crop = frame[y0:y1, x0:x1].copy()
    landmark = ('FOOT SOLE' if candidate.get('landmark') == 'foot' else
                str(candidate.get('contactRegion') or 'region').replace('_', ' ').upper()
                if candidate.get('landmark') == 'region' else
                str(candidate.get('jointName') or candidate.get('landmark') or 'foot').upper())
    label = f"TARGET {candidate['side'].upper()} {landmark}  {candidate['sampleId']}"
    if candidate.get('landmark') in {'knee', 'joint'}:
        region = candidate.get('contactRegion') or _contact_region_for_locator(candidate['jointName'])
        label = f"TARGET {region.replace('_', ' ').upper()} | LOCATOR {candidate['jointName'].upper()}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale, thickness = .48, 1
    (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness)
    padding_x, padding_y = 8, 6
    header_height = text_height + baseline + 2 * padding_y
    canvas_width = max(crop.shape[1], text_width + 2 * padding_x)
    left_padding = (canvas_width - crop.shape[1]) // 2
    right_padding = canvas_width - crop.shape[1] - left_padding
    canvas = cv2.copyMakeBorder(
        crop, header_height, 0, left_padding, right_padding,
        cv2.BORDER_CONSTANT, value=(24, 24, 24))
    cv2.putText(canvas, label, (padding_x, padding_y + text_height), font,
                font_scale, (255, 255, 255), thickness, cv2.LINE_AA)

    marker_x = left_padding + x - x0
    marker_y = header_height + y - y0
    if not mark_target:
        cv2.line(canvas, (marker_x, header_height - 7), (marker_x, header_height - 3),
                 (0, 255, 255), 2, cv2.LINE_AA)
        return canvas, (marker_x, marker_y), (x0, y0, x1, y1), header_height
    # Black outlines keep the crosshair visible against both the shoe and floor.
    cv2.circle(canvas, (marker_x, marker_y), 5, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.line(canvas, (marker_x - 7, marker_y), (marker_x + 7, marker_y),
             (0, 0, 0), 4, cv2.LINE_AA)
    cv2.line(canvas, (marker_x, marker_y - 7), (marker_x, marker_y + 7),
             (0, 0, 0), 4, cv2.LINE_AA)
    cv2.circle(canvas, (marker_x, marker_y), 5, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.line(canvas, (marker_x - 7, marker_y), (marker_x + 7, marker_y),
             (0, 255, 255), 1, cv2.LINE_AA)
    cv2.line(canvas, (marker_x, marker_y - 7), (marker_x, marker_y + 7),
             (0, 255, 255), 1, cv2.LINE_AA)
    return canvas, (marker_x, marker_y), (x0, y0, x1, y1), header_height


def _assemble_contact_timeline_atlas(tiles, sample_ids, columns=3, gutter=8):
    """Pack labeled native-size tiles into one lossless, bounded image input."""
    if (not tiles or len(tiles) != len(sample_ids)
            or len(set(sample_ids)) != len(sample_ids)
            or type(columns) is not int or columns < 1):
        return None
    columns = min(columns, len(tiles))
    cell_width = max(tile.shape[1] for tile in tiles)
    cell_height = max(tile.shape[0] for tile in tiles)
    rows = (len(tiles) + columns - 1) // columns
    atlas = np.full((rows * cell_height + (rows + 1) * gutter,
                     columns * cell_width + (columns + 1) * gutter, 3),
                    24, dtype=np.uint8)
    positions = []
    for index, tile in enumerate(tiles):
        row, column = divmod(index, columns)
        x = gutter + column * (cell_width + gutter)
        y = gutter + row * (cell_height + gutter)
        height, width = tile.shape[:2]
        atlas[y:y + height, x:x + width] = tile
        positions.append((x, y, width, height))
    return atlas, positions


_CONTACT_CHOICES = {
    **{f'{state}_{surface}': (state, surface, True)
       for state in ('full_sole', 'forefoot', 'heel_only')
       for surface in ('ground', 'raised_surface')},
    'airborne': ('airborne', 'none', True),
    'unresolved': ('unknown', 'unknown', False),
}
_NONFOOT_CONTACT_CHOICES = {
    'direct_contact': ('direct_contact', None, True),
    'no_contact': ('no_contact', 'none', True),
    'unresolved': ('unknown', 'unknown', False),
}


def _contact_timeline_response_schema(sample_ids, *, candidates=None):
    by_id = {row['sampleId']: row for row in (candidates or [])}
    return {
        'type': 'object', 'additionalProperties': False,
        'required': list(sample_ids),
        'properties': {sample_id: {'type': 'string', 'enum': list(
            _NONFOOT_CONTACT_CHOICES if by_id.get(sample_id, {}).get('landmark') in {'knee', 'joint', 'region'}
            else _CONTACT_CHOICES)}
                       for sample_id in sample_ids},
    }


def _validated_contact_timeline_response(raw, candidates, *, allow_partial=False):
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError):
        return None
    expected = {row['sampleId']: row for row in candidates}
    rows = answer.get('samples') if isinstance(answer, dict) else None
    if isinstance(answer, dict) and 'samples' not in answer:
        rows = []
        for sample_id, choice in answer.items():
            candidate = expected.get(sample_id) or {}
            choices = (_NONFOOT_CONTACT_CHOICES if candidate.get('landmark') in {'knee', 'joint', 'region'}
                       else _CONTACT_CHOICES)
            if not isinstance(choice, str) or choice not in choices:
                continue
            state, surface, visible = choices[choice]
            if state == 'direct_contact':
                surface = candidate.get('expectedSurface')
            rows.append({'sampleId': sample_id, 'contactState': state,
                         'surface': surface, 'visible': visible})
    if not isinstance(rows, list):
        return None
    by_id = {}
    duplicate_ids = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('sampleId'), str):
            continue
        sample_id = row['sampleId']
        if sample_id in by_id:
            duplicate_ids.add(sample_id)
        by_id[sample_id] = row
    for sample_id in duplicate_ids:
        by_id.pop(sample_id, None)
    if not allow_partial and (len(rows) != len(expected) or set(by_id) != set(expected)):
        return None
    normalized = []
    for sample_id, candidate in expected.items():
        observed = by_id.get(sample_id)
        if observed is None:
            continue
        state, surface, visible = (observed.get('contactState'), observed.get('surface'),
                                   observed.get('visible'))
        landmark = candidate.get('landmark', 'foot')
        allowed_states = ({'direct_contact', 'no_contact', 'unknown'} if landmark in {'knee', 'joint', 'region'}
                          else _CONTACT_STATES - {'direct_contact', 'no_contact'})
        if state == 'direct_contact':
            expected_surface = candidate.get('expectedSurface')
            if surface not in (None, expected_surface):
                continue
            surface = expected_surface
        if state not in allowed_states or surface not in _CONTACT_SURFACES or type(visible) is not bool:
            continue
        if visible is False and state != 'unknown':
            continue
        if state in {'full_sole', 'forefoot', 'heel_only'}:
            if visible is not True or surface not in {'ground', 'raised_surface'}:
                continue
        elif state == 'airborne' and surface not in {'none', 'unknown'}:
            continue
        elif state == 'unknown' and surface not in {'none', 'unknown'}:
            continue
        elif state == 'direct_contact' and (landmark not in {'knee', 'joint', 'region'} or not visible
                                             or surface not in (_SUPPORT_SURFACES
                                                                | _HAND_SUPPORT_SURFACES
                                                                | _ANKLE_SUPPORT_SURFACES
                                                                | ({'raised_surface'} if landmark == 'region'
                                                                   and candidate.get('contactRegion') == 'foot'
                                                                   else set()))):
            continue
        elif state == 'no_contact' and (landmark not in {'knee', 'joint', 'region'} or not visible
                                         or surface not in {'none', 'unknown'}):
            continue
        normalized.append({
            'sampleId': sample_id,
            'sourceTimeSec': candidate['sourceTimeSec'],
            'side': candidate['side'],
            **({'landmark': 'region', 'contactRegion': candidate['contactRegion']}
               if landmark == 'region' else
               {'landmark': landmark, 'jointName': candidate['jointName']}
               if landmark in {'knee', 'joint'} else {}),
            **({'contactRegion': candidate.get('contactRegion')
                or _contact_region_for_locator(candidate['jointName'])}
               if landmark in {'knee', 'joint'} else {}),
            'contactState': state,
            'surface': surface,
            'visible': visible,
            'sourceTrackStationary': candidate.get('sourceTrackStationary', True),
            **({'reviewOnly': True} if candidate.get('reviewOnly') is True else {}),
            'sourcePoseFrameIndex': candidate['poseFrameIndex'],
            'sourceFrameIndex': candidate['sourceFrameIndex'],
            'sourceFps': candidate['sourceFps'],
        })
    if not allow_partial and len(normalized) != len(expected):
        return None
    return normalized


def _contact_timeline_batch_response(raw, batch, *, is_foot):
    """Strictly decode one persisted atlas response against its exact rows."""
    bound_response = raw
    if not is_foot:
        try:
            answer = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(answer, dict) or set(answer) != {'choice'}:
            return None
        bound_response = json.dumps({batch[0]['sampleId']: answer['choice']})
    rows = _validated_contact_timeline_response(bound_response, batch, allow_partial=False)
    if rows is None or {row['sampleId'] for row in rows} != {row['sampleId'] for row in batch}:
        return None
    return rows


def _contact_timeline_alias_prompt(batch, aliases):
    """Ask one structured question for each code-labeled non-foot panel."""
    lines = [
        'Inspect each panel in this 2-by-2 image independently. Shown panels have code-owned A-D labels.',
        'For each panel, decide only whether the marked body surface visibly touches its candidate surface.',
        'The marker locates anatomy; proximity and stationarity are not contact evidence.',
    ]
    for alias, candidate in zip(aliases, batch):
        region = str(candidate['contactRegion']).replace('_', ' ')
        target = region if region in {'upper back', 'pelvis', 'head'} else f"{candidate['side']} {region}"
        surface = str(candidate['expectedSurface']).replace('_', ' ')
        locator = candidate.get('jointName')
        locator_note = (f'The {locator} marker is an anatomical locator, not a contact point.'
                        if locator else 'The marked center is context only, not a contact point.')
        lines.append(
            f'{alias}: source frame {candidate["sourceFrameIndex"]}, {target}; '
            f'{locator_note} Test candidate surface category {surface}: '
            f'{_contact_surface_referent(candidate["expectedSurface"])}'
        )
    lines.append(
        'Return exactly one JSON property for every shown panel label, with value direct_contact, '
        'no_contact, or unresolved. Do not infer between frames.'
    )
    return ' '.join(lines)


def _contact_timeline_alias_schema(aliases):
    return {
        'type': 'object', 'additionalProperties': False,
        'required': list(aliases),
        'properties': {alias: {'type': 'string', 'enum': list(_NONFOOT_CONTACT_CHOICES)}
                       for alias in aliases},
    }


def _contact_timeline_alias_batch_response(raw, batch, alias_to_sample_id):
    """Bind alias-keyed answers back to exact code-owned sample identities."""
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if (not isinstance(answer, dict)
            or set(answer) != set(alias_to_sample_id)
            or len(answer) != len(alias_to_sample_id)):
        return None
    by_id = {alias_to_sample_id[alias]: choice for alias, choice in answer.items()}
    rows = _validated_contact_timeline_response(json.dumps(by_id), batch)
    if rows is None or {row['sampleId'] for row in rows} != {
            row['sampleId'] for row in batch}:
        return None
    return rows


def _label_contact_timeline_panel(cv2, tile, alias):
    """Add a code-owned alias header without covering source pixels."""
    header = 28
    labeled = np.full((tile.shape[0] + header, tile.shape[1], 3), 24, dtype=np.uint8)
    labeled[header:] = tile
    cv2.putText(labeled, alias, (8, 20), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, (255, 255, 255), 2, cv2.LINE_AA)
    return labeled


def _reuse_legacy_contact_timeline_batches(
        cache_dir, request_sha, digest, review_identity, candidates):
    """Reuse prior atlas responses only under their unchanged original identities."""
    foot_indexes = [index for index, row in enumerate(candidates)
                    if row.get('landmark', 'foot') == 'foot']
    foot_batches = [foot_indexes[index:index + _CONTACT_TIMELINE_FOOT_BATCH_SIZE]
                    for index in range(0, len(foot_indexes), _CONTACT_TIMELINE_FOOT_BATCH_SIZE)]
    old_batches = foot_batches + [[index] for index, row in enumerate(candidates)
                                  if row.get('landmark', 'foot') != 'foot']
    reused_rows = {}
    reused_responses = []
    for old_index, indexes in enumerate(old_batches):
        batch = [candidates[index] for index in indexes]
        if not batch:
            continue
        is_foot = batch[0].get('landmark', 'foot') == 'foot'
        atlas_path = Path(cache_dir) / f'{request_sha}-contact-{old_index}.png'
        if not atlas_path.is_file():
            continue
        if is_foot:
            prompt = ('Inspect the foot panels in this single PNG. Each panel pairs the source scene '
                      'with a sole close-up and a code-owned sample ID. Report visible sole state and '
                      'surface for each ID: full_sole only when heel and forefoot both touch, forefoot '
                      'when the heel is raised, heel_only when the forefoot is raised, airborne when no '
                      'shoe contact is visible, and unresolved when hidden or ambiguous. Judge each panel '
                      'independently; do not infer contact between samples or from stationary motion.')
            schema = _contact_timeline_response_schema(
                [row['sampleId'] for row in batch], candidates=batch)
            max_tokens = 600
        else:
            prompt = _nonfoot_contact_timeline_prompt(batch[0])
            schema = {'type': 'object', 'additionalProperties': False, 'required': ['choice'],
                      'properties': {'choice': {'type': 'string',
                                                'enum': list(_NONFOOT_CONTACT_CHOICES)}}}
            max_tokens = 160
        identity = {
            'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'requestSha256': request_sha, 'sourceVideoSha256': digest,
            'reviewIdentity': review_identity, 'batchIndex': old_index,
            'sampleIds': [row['sampleId'] for row in batch],
            'atlasSha256': hashlib.sha256(atlas_path.read_bytes()).hexdigest(),
            'promptSha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
            'responseSchemaSha256': hashlib.sha256(json.dumps(
                schema, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
            ).encode('utf-8')).hexdigest(),
            'maxTokens': max_tokens,
        }
        identity_sha = hashlib.sha256(json.dumps(
            identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        ).encode('utf-8')).hexdigest()
        batch_cache = Path(cache_dir) / f'{request_sha}-batch-{identity_sha}.json'
        try:
            cached = json.loads(batch_cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        raw = cached.get('rawResponse') if isinstance(cached, dict) else None
        if (not isinstance(cached, dict)
                or any(cached.get(key) != value for key, value in identity.items())
                or not isinstance(raw, str)
                or cached.get('responseSha256') != hashlib.sha256(raw.encode('utf-8')).hexdigest()):
            continue
        rows = _contact_timeline_batch_response(raw, batch, is_foot=is_foot)
        if rows is None:
            continue
        for row in rows:
            reused_rows[row['sampleId']] = row
        reused_responses.append({'sampleIds': identity['sampleIds'], 'rawResponse': raw,
                                 'cacheReuse': 'exact_legacy_batch'})
    return reused_rows, reused_responses


def _write_contact_timeline_batch(path, payload):
    """Atomically retain a batch response before the next request can fail."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=path.parent,
                prefix=f'.{path.name}.', suffix='.tmp', delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def validated_body_support_contact_timeline(observed, *, expected_video_sha256=None):
    """Return exact-video, code-timed contact rows; malformed or stale proof is absent."""
    if not isinstance(observed, dict):
        return None
    timeline = observed.get('contactTimeline', observed)
    if (not isinstance(timeline, dict)
            or timeline.get('schemaVersion') != 1
            or timeline.get('policyVersion') not in _SUPPORTED_CONTACT_TIMELINE_POLICY_VERSIONS
            or timeline.get('source') != 'exact_source_visual_contact_timeline'
            or timeline.get('sourceClock') != 'video_frame_zero_seconds'
            or timeline.get('status') != 'observed'
            or not isinstance(timeline.get('sourceVideoSha256'), str)
            or not timeline['sourceVideoSha256']):
        return None
    digest = timeline['sourceVideoSha256']
    if expected_video_sha256 is not None and digest != expected_video_sha256:
        return None
    if 'contactTimeline' in observed:
        if (observed.get('sourceVideoSha256') != digest
                or observed.get('status') != 'observed'
                or observed.get('source') != 'exact_source_visual_support_observation'):
            return None
    rows = timeline.get('samples')
    if not isinstance(rows, list):
        return None
    seen = set()
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        sample_id, side = row.get('sampleId'), row.get('side')
        landmark = row.get('landmark', 'foot')
        joint_name = row.get('jointName')
        state, surface, visible = row.get('contactState'), row.get('surface'), row.get('visible')
        try:
            source_time = float(row.get('sourceTimeSec'))
            source_fps = float(row.get('sourceFps'))
        except (TypeError, ValueError, OverflowError):
            return None
        source_frame_index = row.get('sourceFrameIndex')
        pose_frame_index = row.get('sourcePoseFrameIndex')
        if (not isinstance(sample_id, str) or not sample_id or sample_id in seen
                or side not in {'left', 'right', 'center'}
                or landmark not in {'foot', 'knee', 'joint', 'region'}
                or not np.isfinite(source_time)
                or type(source_frame_index) is not int or source_frame_index < 0
                or type(pose_frame_index) is not int or pose_frame_index < 0
                or not np.isfinite(source_fps) or source_fps <= 0.
                or abs(source_time - source_frame_index / source_fps) > 1e-6
                or state not in _CONTACT_STATES or surface not in _CONTACT_SURFACES
                or type(visible) is not bool
                or type(row.get('sourceTrackStationary')) is not bool
                or (row.get('sourceTrackStationary') is False
                    and not (landmark == 'joint'
                             and joint_name in {'left_shoulder', 'right_shoulder'}
                             and row.get('contactRegion') == 'upper_back')
                    and not (landmark == 'foot' and row.get('reviewOnly') is True)
                    and not (landmark == 'region' and row.get('contactRegion') in {'upper_back', 'foot'}))):
            return None
        if landmark == 'region':
            region = row.get('contactRegion')
            valid_region = (
                joint_name is None
                and ((region == 'upper_back' and side == 'center'
                      and timeline.get('policyVersion') in {6, CONTACT_TIMELINE_POLICY_VERSION})
                     or (region == 'foot' and side in {'left', 'right'}
                         and timeline.get('policyVersion') == CONTACT_TIMELINE_POLICY_VERSION))
            )
            if not valid_region:
                return None
        if landmark == 'knee' and joint_name != f'{side}_knee':
            return None
        if landmark == 'joint' and (not isinstance(joint_name, str)
                                    or joint_name not in {
                                        'pelvis', 'head', 'left_shoulder', 'right_shoulder',
                                        'left_wrist', 'right_wrist', 'left_ankle', 'right_ankle'}):
            return None
        if landmark == 'joint' and joint_name.startswith(('left_', 'right_')) \
                and side != joint_name.split('_', 1)[0]:
            return None
        if landmark == 'joint' and not joint_name.startswith(('left_', 'right_')) and side != 'center':
            return None
        if landmark == 'foot' and (joint_name is not None or row.get('contactRegion') is not None):
            return None
        if row.get('reviewOnly') is True and (
                landmark != 'foot' or row.get('sourceTrackStationary') is not False):
            return None
        if landmark in {'knee', 'joint'} and row.get(
                'contactRegion', _contact_region_for_locator(joint_name)) != _contact_region_for_locator(joint_name):
            return None
        if visible is False and state != 'unknown':
            return None
        if state in {'full_sole', 'forefoot', 'heel_only', 'airborne'} and landmark != 'foot':
            return None
        if state in {'full_sole', 'forefoot', 'heel_only'}:
            if visible is not True or surface not in {'ground', 'raised_surface'}:
                return None
        elif state == 'airborne' and surface not in {'none', 'unknown'}:
            return None
        elif state == 'unknown' and surface not in {'none', 'unknown'}:
            return None
        elif state == 'direct_contact':
            allowed_surfaces = (_SUPPORT_SURFACES | _HAND_SUPPORT_SURFACES
                                | _ANKLE_SUPPORT_SURFACES)
            if landmark == 'region' and row.get('contactRegion') == 'foot':
                allowed_surfaces = allowed_surfaces | {'raised_surface'}
            if (landmark not in {'knee', 'joint', 'region'} or not visible
                    or surface not in allowed_surfaces):
                return None
        elif state == 'no_contact' and (landmark not in {'knee', 'joint', 'region'} or not visible
                                         or surface not in {'none', 'unknown'}):
            return None
        seen.add(sample_id)
        normalized.append({**row, 'sourceTimeSec': source_time})
    return normalized


def _contact_timeline_request_fingerprint(rows, video_sha256, review_identity):
    identity = [CONTACT_TIMELINE_POLICY_VERSION, video_sha256, review_identity,
                {'cropPolicy': CONTACT_TIMELINE_CROP_POLICY, 'radiusX': .075,
                 'radiusYTop': .025, 'radiusYBottom': .13,
                 'bodyRadiusYTop': .13,
                 'minRadiusX': 16, 'minRadiusYTop': 8, 'minRadiusYBottom': 24,
                 'marker': 'foot-crosshair-body-header-tick-v2',
                 'label': 'padded-header-autosized-v1'},
                [(row['sampleId'], row['sourceTimeSec'], row['side'],
                  row.get('landmark', 'foot'), row.get('jointName'), row.get('contactRegion'),
                  row.get('regionPoints'), row.get('expectedSurface'),
                  row['poseFrameIndex'], row.get('point'), row.get('ankle'), row.get('heel'),
                  row.get('toe'), row.get('knee'),
                  row['stationaryStartTimeSec'], row['stationaryEndTimeSec'])
                 for row in rows]]
    moving_locators = [row['sampleId'] for row in rows
                       if row.get('sourceTrackStationary') is False]
    if moving_locators:
        identity.append({'nonstationaryLocators': moving_locators})
    return hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()


def observe_foot_contact_timeline(video_path, source_pose, source_foot_support_evidence,
                                  caption_images, cache_dir):
    """Visually label bounded pose-selected foot crops at exact source times.

    Vision owns only visible contact state for each code-selected target crop.
    Side, sample identity, source time, and source stationarity remain code-owned.
    Returned rows are point observations and never imply contact between samples.
    """
    video_path, cache_dir = Path(video_path), Path(cache_dir)
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    review_identity = _review_model_identity(caption_images)
    evidence = source_foot_support_evidence if isinstance(source_foot_support_evidence, dict) else {}
    pose_reference = source_pose if isinstance(source_pose, dict) else {}
    pose = pose_reference.get('pose') if isinstance(pose_reference.get('pose'), dict) else pose_reference
    patch = evidence.get('footPatchEvidence') or {}
    pose_origin = pose.get('sourceTimeOriginSec') if isinstance(pose, dict) else None
    patch_origin = patch.get('sourceTimeOriginSec')
    try:
        same_clock = (pose_origin is not None and patch_origin is not None
                      and abs(float(pose_origin) - float(patch_origin)) <= 1e-6)
    except (TypeError, ValueError, OverflowError):
        same_clock = False
    if (evidence.get('sourceVideoSha256') != digest
            or pose_reference.get('sourceVideoSha256') != digest):
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'source_contact_evidence_identity_mismatch',
                'samples': [], 'reviewIdentity': review_identity}
    candidates = _contact_timeline_candidates(
        pose, evidence if patch.get('sourceVideoSha256') == digest and same_clock else {
            **evidence, 'footPatchEvidence': {}, 'feet': {}})
    if not candidates:
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'no_bounded_unknown_stationary_contact_samples',
                'samples': [], 'reviewIdentity': review_identity}
    all_candidates = list(candidates)
    request_sha = _contact_timeline_request_fingerprint(candidates, digest, review_identity)
    cache = cache_dir / f'body-support-contact-timeline-{request_sha}.json'
    retained_rows = []
    retained_responses = []
    existing_observation = evidence.get('bodySupportObservation')
    existing = (existing_observation.get('contactTimeline')
                if isinstance(existing_observation, dict) else None)
    existing_rows = validated_body_support_contact_timeline(existing, expected_video_sha256=digest)
    if existing_rows and isinstance(existing, dict) and existing.get('reviewIdentity') == review_identity:
        existing_ids = {row['sampleId'] for row in existing_rows}
        existing_candidates = [row for row in candidates if row['sampleId'] in existing_ids]
        if (existing.get('requestSha256') == request_sha or
                len(existing_candidates) == len(existing_rows)
                and _contact_timeline_request_fingerprint(
                    existing_candidates, digest, review_identity) == existing.get('requestSha256')):
            retained_rows = existing_rows
            retained_responses = [*(existing.get('priorResponses') or []), existing.get('rawResponse')]
    cached = None
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cached = None
        if isinstance(cached, dict) and cached.get('requestSha256') == request_sha:
            if cached.get('reviewIdentity') != review_identity:
                cached = None
        if isinstance(cached, dict) and cached.get('requestSha256') == request_sha:
            if (cached.get('status') == 'unknown'
                    and cached.get('reason') != 'support_timeline_response_invalid'
                    and not retained_rows):
                return cached
            rows = validated_body_support_contact_timeline(cached, expected_video_sha256=digest)
            retained_by_id = {row['sampleId']: row for row in retained_rows}
            for row in rows or []:
                retained_by_id.setdefault(row['sampleId'], row)
            retained_rows = list(retained_by_id.values())
            expected = {(row['sampleId'], row['side']) for row in candidates}
            if rows is not None and {(row['sampleId'], row['side']) for row in rows} == expected:
                return cached

    retained_ids = {row['sampleId'] for row in retained_rows}
    import cv2
    source_fps = patch.get('sourceFps')
    try:
        source_fps = float(source_fps)
    except (TypeError, ValueError, OverflowError):
        source_fps = 0.
    if not np.isfinite(source_fps) or source_fps <= 0.:
        clock_capture = cv2.VideoCapture(str(video_path))
        try:
            source_fps = float(clock_capture.get(cv2.CAP_PROP_FPS))
        finally:
            clock_capture.release()
    if not np.isfinite(source_fps) or source_fps <= 0.:
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'support_timeline_video_clock_unavailable',
                'requestSha256': request_sha, 'samples': [],
                'reviewIdentity': review_identity}
    legacy_candidates = []
    for row in all_candidates:
        frame_index = int(round(float(row['sourceTimeSec']) * source_fps))
        legacy_candidates.append({**row, 'sourceFrameIndex': frame_index,
                                  'sourceFps': source_fps,
                                  'sourceTimeSec': frame_index / source_fps})
    legacy_rows, legacy_responses = _reuse_legacy_contact_timeline_batches(
        cache_dir, request_sha, digest, review_identity, legacy_candidates)
    legacy_rows = {sample_id: row for sample_id, row in legacy_rows.items()
                   if sample_id not in retained_ids}
    candidates = [row for row in all_candidates
                  if row['sampleId'] not in retained_ids | set(legacy_rows)]

    if candidates and caption_images is None:
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'support_timeline_observer_unavailable',
                'requestSha256': request_sha, 'samples': [],
                'reviewIdentity': review_identity}
    from .bake_and_rank import call_caption_images_json, callable_accepts_keyword
    if candidates and not callable_accepts_keyword(caption_images, 'response_schema'):
        return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                'source': 'exact_source_visual_contact_timeline',
                'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                'status': 'unknown', 'reason': 'structured_support_timeline_output_unavailable',
                'requestSha256': request_sha, 'samples': [],
                'reviewIdentity': review_identity}

    cache_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    tiles = []
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if not np.isfinite(fps) or fps <= 0. or frame_count <= 0:
            return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                    'source': 'exact_source_visual_contact_timeline',
                    'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                    'status': 'unknown', 'reason': 'support_timeline_video_clock_unavailable',
                    'requestSha256': request_sha, 'samples': [],
                    'reviewIdentity': review_identity}
        for candidate in candidates:
            frame_index = int(round(candidate['sourceTimeSec'] * fps))
            if frame_index < 0 or frame_index >= frame_count:
                return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                        'source': 'exact_source_visual_contact_timeline',
                        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                        'status': 'unknown', 'reason': 'support_timeline_frame_out_of_range',
                        'requestSha256': request_sha, 'samples': [],
                        'reviewIdentity': review_identity}
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                        'source': 'exact_source_visual_contact_timeline',
                        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                        'status': 'unknown', 'reason': 'support_timeline_frame_unavailable',
                        'requestSha256': request_sha, 'samples': [],
                        'reviewIdentity': review_identity}
            decoded_time = frame_index / fps
            if not (candidate['stationaryStartTimeSec'] <= decoded_time
                    <= candidate['stationaryEndTimeSec']):
                return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                        'source': 'exact_source_visual_contact_timeline',
                        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                        'status': 'unknown', 'reason': 'support_timeline_frame_outside_stationary_interval',
                        'requestSha256': request_sha, 'samples': [],
                        'reviewIdentity': review_identity}
            rendered = _render_contact_timeline_crop(
                cv2, frame, candidate, mark_target=candidate.get('landmark', 'foot') == 'foot')
            if rendered is None:
                return {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                        'source': 'exact_source_visual_contact_timeline',
                        'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                        'status': 'unknown', 'reason': 'support_timeline_crop_unavailable',
                        'requestSha256': request_sha, 'samples': [],
                        'reviewIdentity': review_identity}
            crop, marker, bounds, header_height = rendered
            # Surface identity needs the scene; contact state needs the close-up.
            scene = cv2.resize(frame, (crop.shape[1], max(1, round(
                frame.shape[0] * crop.shape[1] / frame.shape[1]))))
            tiles.append(cv2.vconcat([scene, crop]))
            candidate['cropMarkerXY'] = [marker[0], marker[1] + scene.shape[0]]
            candidate['cropBoundsXYXY'] = list(bounds)
            candidate['cropHeaderHeight'] = header_height
            candidate['sourceFrameIndex'] = frame_index
            candidate['sourceFps'] = fps
            candidate['sourceTimeSec'] = decoded_time
    finally:
        capture.release()

    tile_by_sample = {row['sampleId']: tile for row, tile in zip(candidates, tiles)}
    observations = list(legacy_rows.values())
    responses = list(legacy_responses)
    foot_candidates = [row for row in candidates if row.get('landmark', 'foot') == 'foot']
    foot_batches = [foot_candidates[index:index + _CONTACT_TIMELINE_FOOT_BATCH_SIZE]
                    for index in range(0, len(foot_candidates), _CONTACT_TIMELINE_FOOT_BATCH_SIZE)]
    for batch_index, batch in enumerate(foot_batches):
        atlas_data = _assemble_contact_timeline_atlas(
            [tile_by_sample[row['sampleId']] for row in batch],
            [row['sampleId'] for row in batch])
        if atlas_data is None:
            continue
        atlas, positions = atlas_data
        for candidate, position in zip(batch, positions):
            candidate['atlasPanelXYWH'] = list(position)
        atlas_path = cache_dir / f'{request_sha}-contact-{batch_index}.png'
        if not cv2.imwrite(str(atlas_path), atlas):
            raise OSError(f'Cannot write contact observation: {atlas_path}')
        prompt = ('Inspect the foot panels in this single PNG. Each panel pairs the source scene '
                  'with a sole close-up and a code-owned sample ID. Report visible sole state and '
                  'surface for each ID: full_sole only when heel and forefoot both touch, forefoot '
                  'when the heel is raised, heel_only when the forefoot is raised, airborne when no '
                  'shoe contact is visible, and unresolved when hidden or ambiguous. Judge each panel '
                  'independently; do not infer contact between samples or from stationary motion.')
        schema = _contact_timeline_response_schema(
            [row['sampleId'] for row in batch], candidates=batch)
        batch_identity = {
            'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'requestSha256': request_sha, 'sourceVideoSha256': digest,
            'reviewIdentity': review_identity, 'batchIndex': batch_index,
            'sampleIds': [row['sampleId'] for row in batch],
            'atlasSha256': hashlib.sha256(atlas_path.read_bytes()).hexdigest(),
            'promptSha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
            'responseSchemaSha256': hashlib.sha256(json.dumps(
                schema, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
            ).encode('utf-8')).hexdigest(),
            'maxTokens': 600,
        }
        identity_sha = hashlib.sha256(json.dumps(
            batch_identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        ).encode('utf-8')).hexdigest()
        batch_cache = cache_dir / f'{request_sha}-batch-{identity_sha}.json'
        try:
            cached_batch = json.loads(batch_cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cached_batch = None
        cached_raw = cached_batch.get('rawResponse') if isinstance(cached_batch, dict) else None
        cached_rows = None
        if (isinstance(cached_batch, dict)
                and all(cached_batch.get(key) == value for key, value in batch_identity.items())
                and isinstance(cached_raw, str)
                and cached_batch.get('responseSha256') == hashlib.sha256(
                    cached_raw.encode('utf-8')).hexdigest()):
            cached_rows = _contact_timeline_batch_response(cached_raw, batch, is_foot=True)
        if cached_rows is not None:
            responses.append({'sampleIds': batch_identity['sampleIds'], 'rawResponse': cached_raw})
            observations.extend(cached_rows)
            continue
        response = call_caption_images_json(
            caption_images, frame_paths=[atlas_path], prompt=prompt, max_tokens=600,
            json_response=True, response_schema=schema, disable_reasoning=True,
            temperature=0., top_p=1., top_k=1)
        raw_response = response if isinstance(response, str) else None
        checkpoint = {**batch_identity, 'rawResponse': raw_response,
                      'responseSha256': hashlib.sha256(
                          raw_response.encode('utf-8') if raw_response is not None
                          else repr(response).encode('utf-8')).hexdigest()}
        _write_contact_timeline_batch(batch_cache, checkpoint)
        responses.append({'sampleIds': batch_identity['sampleIds'], 'rawResponse': response})
        observations.extend(_contact_timeline_batch_response(raw_response, batch, is_foot=True) or [])

    nonfoot_candidates = [row for row in candidates if row.get('landmark', 'foot') != 'foot']
    nonfoot_batches = [nonfoot_candidates[index:index + 4]
                       for index in range(0, len(nonfoot_candidates), 4)]
    for batch_index, batch in enumerate(nonfoot_batches):
        aliases = [chr(ord('A') + index) for index in range(len(batch))]
        alias_to_sample_id = dict(zip(aliases, [row['sampleId'] for row in batch]))
        labeled_tiles = [_label_contact_timeline_panel(
            cv2, tile_by_sample[row['sampleId']], alias)
            for row, alias in zip(batch, aliases)]
        atlas_data = _assemble_contact_timeline_atlas(labeled_tiles, aliases, columns=2)
        if atlas_data is None:
            continue
        atlas, positions = atlas_data
        for candidate, position in zip(batch, positions):
            candidate['atlasPanelXYWH'] = list(position)
        atlas_path = cache_dir / f'{request_sha}-contact-alias-v1-{batch_index}.png'
        if not cv2.imwrite(str(atlas_path), atlas):
            raise OSError(f'Cannot write contact observation: {atlas_path}')
        prompt = _contact_timeline_alias_prompt(batch, aliases)
        schema = _contact_timeline_alias_schema(aliases)
        batch_identity = {
            'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'batchProtocolVersion': 'nonfoot_alias_panels_v1',
            'requestSha256': request_sha, 'sourceVideoSha256': digest,
            'reviewIdentity': review_identity, 'batchIndex': batch_index,
            'sampleIds': [row['sampleId'] for row in batch],
            'aliasToSampleId': alias_to_sample_id,
            'atlasSha256': hashlib.sha256(atlas_path.read_bytes()).hexdigest(),
            'promptSha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
            'responseSchemaSha256': hashlib.sha256(json.dumps(
                schema, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
            ).encode('utf-8')).hexdigest(),
            'maxTokens': 320,
        }
        identity_sha = hashlib.sha256(json.dumps(
            batch_identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        ).encode('utf-8')).hexdigest()
        batch_cache = cache_dir / f'{request_sha}-batch-{identity_sha}.json'
        try:
            cached_batch = json.loads(batch_cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cached_batch = None
        cached_raw = cached_batch.get('rawResponse') if isinstance(cached_batch, dict) else None
        cached_rows = None
        if (isinstance(cached_batch, dict)
                and all(cached_batch.get(key) == value for key, value in batch_identity.items())
                and isinstance(cached_raw, str)
                and cached_batch.get('responseSha256') == hashlib.sha256(
                    cached_raw.encode('utf-8')).hexdigest()):
            cached_rows = _contact_timeline_alias_batch_response(
                cached_raw, batch, alias_to_sample_id)
        if cached_rows is not None:
            responses.append({'sampleIds': batch_identity['sampleIds'], 'rawResponse': cached_raw,
                              'aliasToSampleId': alias_to_sample_id})
            observations.extend(cached_rows)
            continue
        response = call_caption_images_json(
            caption_images, frame_paths=[atlas_path], prompt=prompt, max_tokens=320,
            json_response=True, response_schema=schema, disable_reasoning=True,
            temperature=0., top_p=1., top_k=1)
        raw_response = response if isinstance(response, str) else None
        checkpoint = {**batch_identity, 'rawResponse': raw_response,
                      'responseSha256': hashlib.sha256(
                          raw_response.encode('utf-8') if raw_response is not None
                          else repr(response).encode('utf-8')).hexdigest()}
        _write_contact_timeline_batch(batch_cache, checkpoint)
        responses.append({'sampleIds': batch_identity['sampleIds'], 'rawResponse': response,
                          'aliasToSampleId': alias_to_sample_id})
        observations.extend(_contact_timeline_alias_batch_response(
            raw_response, batch, alias_to_sample_id) or [])
    raw = json.dumps(responses)
    rows_by_id = {}
    duplicate_ids = set()
    for row in [*retained_rows, *observations]:
        sample_id = row.get('sampleId')
        if sample_id in rows_by_id:
            duplicate_ids.add(sample_id)
        else:
            rows_by_id[sample_id] = row
    complete_ids = set(all_candidate['sampleId'] for all_candidate in all_candidates)
    complete = (not duplicate_ids and set(rows_by_id) == complete_ids)
    observations = [rows_by_id[row['sampleId']] for row in all_candidates
                    if row['sampleId'] in rows_by_id and row['sampleId'] not in duplicate_ids]
    if not observations:
        result = {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
                  'source': 'exact_source_visual_contact_timeline',
                  'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
                  'status': 'unknown', 'reason': 'support_timeline_response_invalid',
                  'requestSha256': request_sha, 'responseSha256': hashlib.sha256(
                      str(raw).encode()).hexdigest(), 'rawResponse': raw, 'samples': [],
                  'reviewIdentity': review_identity}
        cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    result = {'schemaVersion': 1, 'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
              'source': 'exact_source_visual_contact_timeline',
              'sourceVideoSha256': digest, 'sourceClock': 'video_frame_zero_seconds',
              'status': 'observed', 'requestSha256': request_sha,
              'responseSha256': hashlib.sha256(str(raw).encode()).hexdigest(),
              'samples': observations, 'rawResponse': raw,
              'retryable': not complete,
              'reviewIdentity': review_identity,
              'priorResponses': [*retained_responses,
                                *([*(cached.get('priorResponses') or []), cached.get('rawResponse')]
                                  if isinstance(cached, dict) else [])]}
    cache.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def materialize_timed_visual_contact_points(evidence, frames=None, joint_names=None, *,
                                           ground_contact_mode=None):
    """Add exact-time, visible contacts whose point geometry is representable."""
    if not isinstance(evidence, dict):
        return evidence
    if 'supportContacts' not in evidence:
        evidence['_fitGeneratedSupportContactsCollection'] = True
    contacts = evidence.setdefault('supportContacts', [])
    if not isinstance(contacts, list):
        contacts = []
        evidence['supportContacts'] = contacts
    # These rows are derived from the current timeline and fit clock. Never
    # carry them across a rematerialization when either input has changed.
    contacts[:] = [contact for contact in contacts
                   if not (isinstance(contact, dict)
                           and contact.get('supportKind') == 'exact_timed_visual_contact')]
    observed = evidence.get('bodySupportObservation') or {}
    rows = validated_body_support_contact_timeline(observed)
    if rows is None:
        return evidence
    digest = observed.get('sourceVideoSha256')
    mapping = evidence.get('motionSpaceMapping') or {}
    swapped = mapping.get('bilateralAssignment') == 'swapped'
    from .contact_constraints import (
        _body_timeline_parent_exposure_time,
        _indistinguishable_forefoot_patch_at_time,
        _neutral_pitch_forefoot_patch_at_time,
        _source_timeline_mapping_for_payload,
    )
    source_timeline_mapping = evidence.get('_fitSourceTimelineMapping')
    if source_timeline_mapping is None:
        source_timeline_mapping = _source_timeline_mapping_for_payload(evidence)
    names = set(joint_names or [])
    times = []
    for frame in frames or []:
        if not isinstance(frame, dict) or frame.get('syntheticLoopBridge'):
            times.append(None)
            continue
        try:
            time = float(frame.get('sourceTimeSec'))
        except (TypeError, ValueError, OverflowError):
            times.append(None)
        else:
            times.append(time if np.isfinite(time) else None)
    from .cleanup import ground_contact_mode_allows_floor_support
    allow_ground = ground_contact_mode_allows_floor_support(ground_contact_mode)
    for row in rows:
        # Raised forefoot points keep their source height; a full sole needs a measured plane.
        if (row['visible'] is not True
                or not row['sourceTrackStationary']
                or row.get('reviewOnly') is True
                or row['surface'] not in {'ground', 'raised_surface'}
                or (row['surface'] == 'ground' and not allow_ground)
                or (row['surface'] == 'raised_surface' and row['contactState'] != 'forefoot')
                or row['contactState'] not in {'full_sole', 'forefoot'}):
            continue
        source_side = row['side']
        parent_exposure_time = _body_timeline_parent_exposure_time(
            row, source_timeline_mapping, str(digest or '').casefold())
        if parent_exposure_time is None:
            continue
        rig_side = ('right' if source_side == 'left' else 'left') if swapped else source_side
        joint = f'{rig_side}_foot'
        if names and joint not in names:
            continue
        source_foot_patch = ((evidence.get('footPatchEvidence') or {}).get('feet') or {}).get(source_side) or {}
        heel_unobserved = source_foot_patch.get('pitchReferenceSource') == 'heel_unobserved'
        indistinguishable_forefoot = _indistinguishable_forefoot_patch_at_time(
            evidence, source_side, row.get('sourceTimeSec'))
        neutral_pitch_forefoot = _neutral_pitch_forefoot_patch_at_time(
            evidence, source_side, row.get('sourceTimeSec'))
        point = {
            'jointName': joint,
            'supportKind': 'exact_timed_visual_contact',
            'contactState': ('full_sole' if row['contactState'] == 'full_sole'
                             and not heel_unobserved and not indistinguishable_forefoot
                             and not neutral_pitch_forefoot
                             else 'toe_only'),
            'contactMotion': 'stationary',
            'surfaceKind': row['surface'],
            'verticalOnly': False,
            'sourceTimeSec': parent_exposure_time,
            'sourceTimeBasis': 'absolute_source_video',
            'contactTimelineSourceTimeSec': row['sourceTimeSec'],
            'contactTimelineParentExposureTimeSec': parent_exposure_time,
            'contactTimelineSourceClock': 'video_frame_zero_seconds',
            'contactTimelineSampleId': row['sampleId'],
            'contactTimelineSourceVideoSha256': digest,
        }
        if times:
            exact = [index for index, time in enumerate(times)
                     if time is not None and abs(time - point['sourceTimeSec']) <= 1e-6]
            if not exact:
                continue
            index = exact[0]
            point['_fitFrameBounds'] = [index, index]
            point['_fitFrameCount'] = len(times)
        contacts.append(point)
    return evidence


def _stance_has_conflicting_observations(evidence, side, *, allow_forefoot=False):
    patch = evidence.get('footPatchEvidence') or {}
    foot_patch = (patch.get('feet') or {}).get(side) or {}
    states = foot_patch.get('states') or []
    source_material = evidence.get('sourceMaterialStationarityEvidence') or {}
    patch_material = patch.get('materialStationarityEvidence') or {}
    material_rows = [
        (source_material, row) for row in source_material.get('episodes', [])
    ] + [
        (patch_material, row) for row in patch_material.get('episodes', [])
    ]
    from .source_support_tracking import material_episode_scene_registered

    def registered_source_conflict(container, row):
        if (not isinstance(row, dict) or row.get('side') != side
                or row.get('passed') is not False
                or not material_episode_scene_registered(row)):
            return False
        hashes = [value for value in (
            evidence.get('sourceVideoSha256'), patch.get('sourceVideoSha256'),
            container.get('sourceVideoSha256'), row.get('sourceVideoSha256'),
        ) if isinstance(value, str) and value]
        return len(set(hashes)) <= 1

    # ``toe_only`` normally means the patch observed the heel raised and must
    # block a full-sole stance review. Explicit unobserved-heel and neutral-
    # pitch/forefoot provenance preserve only the common forefoot constraint.
    heel_unobserved = foot_patch.get('pitchReferenceSource') == 'heel_unobserved'
    allowed = {'full_sole', 'unknown'} | (
        {'toe_only'} if allow_forefoot or heel_unobserved else set())
    if 'toe_only' in states and 'toe_only' not in allowed:
        from .contact_constraints import _neutral_pitch_forefoot_patch_at_time
        times = patch.get('sourceTimesSec') or []
        neutral_forefoot_only = (
            len(times) == len(states)
            and all(_neutral_pitch_forefoot_patch_at_time(evidence, side, times[index])
                    for index, state in enumerate(states)
                    if str(state).casefold() == 'toe_only')
            and any(str(state).casefold() == 'toe_only' for state in states)
        )
        if neutral_forefoot_only:
            allowed.add('toe_only')
    return (not states or not set(states).issubset(allowed)
            or any(registered_source_conflict(container, row)
                   for container, row in material_rows))


COARSE_STATIONARY_SOLE_REVIEW = 'coarse_stationary_sole'
UNRESOLVED_CONTINUOUS_GROUND_SOLE_REVIEW = 'unresolved_continuous_ground_sole'
_MOSTLY_UNKNOWN_PATCH_RATIO = .8


def _foot_patch_mostly_unknown(evidence, side):
    """Coarse patch labels are contact hypotheses, not calibration proof."""
    states = [str(state).casefold() for state in (
        ((evidence or {}).get('footPatchEvidence') or {}).get('feet', {}).get(side, {})
        .get('states') or [])]
    if not states or 'airborne' in states:
        return False
    return sum(state == 'unknown' for state in states) / len(states) >= _MOSTLY_UNKNOWN_PATCH_RATIO


def source_sole_review_side_eligibility(evidence, pose, side, *, ground_contact_mode=None):
    """Classify why a source side may enter bounded native-frame sole review.

    A stable source ankle track can only *propose* review: native-frame visual
    contact facts still own every anchor. Existing coarse stationary paths stay
    valid; a continuous-ground source whose patch is unresolved may now be
    reviewed even when the coarse foot label says moving, provided the source
    ground surface is positively visible.
    """
    evidence = evidence or {}
    if side not in {'left', 'right'}:
        return None
    digest = evidence.get('sourceVideoSha256')
    observed = evidence.get('bodySupportObservation') or {}
    patch = evidence.get('footPatchEvidence') or {}
    if (not digest or patch.get('available') is not True
            or patch.get('sourceVideoSha256') != digest
            or observed.get('sourceVideoSha256') != digest):
        return None
    answer = validated_body_support_answer(observed) or {}
    if answer.get(f'{side}FootSurface') != 'ground':
        return None
    foot = answer.get(f'{side}Foot')
    if foot in {'stationary_full_sole', 'stationary_forefoot'}:
        if (_stance_has_conflicting_observations(evidence, side, allow_forefoot=True)
                or not (foot == 'stationary_forefoot'
                        or stationary_source_track(pose, f'{side}_ankle'))):
            return None
        return COARSE_STATIONARY_SOLE_REVIEW
    if (foot in {'moving', 'unknown'}
            and ground_contact_mode == 'continuous'
            and not _stance_has_conflicting_observations(evidence, side, allow_forefoot=True)
            and _foot_patch_mostly_unknown(evidence, side)
            and stationary_source_track(pose, f'{side}_ankle')):
        return UNRESOLVED_CONTINUOUS_GROUND_SOLE_REVIEW
    return None


def _stance_from_frame_contacts(answer, sample_ids):
    motion_fields = {'heelMotion', 'forefootMotion'}
    if (not sample_ids or not isinstance(answer, dict)
            or set(answer) != set(sample_ids) | motion_fields
            or any(not isinstance(answer[field], str) or answer[field] not in _CONTACT_CHOICES
                   for field in sample_ids)
            or any(not isinstance(answer[field], str)
                   or answer[field] not in {'stationary', 'moving', 'not_visible'}
                   for field in motion_fields)):
        return None
    contacts = [answer[field] for field in sample_ids]
    if (answer['forefootMotion'] == 'moving'
            or any(value == 'airborne' or value.startswith('heel_only_') for value in contacts)):
        return 'moving_or_releasing'
    if (answer['forefootMotion'] != 'stationary'
            or any(value not in {'full_sole_ground', 'forefoot_ground'} for value in contacts)):
        return 'insufficient_evidence'
    return ('stationary_full_sole_ground' if all(value == 'full_sole_ground' for value in contacts)
            and answer['heelMotion'] == 'stationary'
            else 'stationary_forefoot_ground')


def _load_cached_stance_question(*, directory, name, prompt, frames, max_tokens,
                                 identity, reusable):
    """Read an exact-image question cache without counting a cache miss as a model call."""
    from .review_questions import (
        STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION, with_schema_choice_vocabulary,
    )
    from .stage_cache import cache_key, file_identity, load_stage, stage_lock

    prompt = with_schema_choice_vocabulary(
        prompt, identity.get('schema') if isinstance(identity, dict) else None)
    request = {'prompt': prompt, 'maxTokens': max_tokens,
               'structuredResponsePromptPolicyVersion': STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION}
    if identity is not None and all(Path(frame).is_file() for frame in frames):
        key = cache_key({**request, 'identity': identity,
                         'images': [file_identity(frame).get('sha256') for frame in frames]}, [])
    else:
        return None
    checkpoint = Path(directory) / name / key / 'checkpoint.json'
    with stage_lock(checkpoint):
        cached = load_stage(checkpoint, key)
    if cached is None or not reusable(cached.get('parsed')):
        return None
    return cached.get('raw'), cached.get('parsed')


def _source_frame_clock_proof(video_path, digest, frame_count):
    """Return a receipt identity only when the selected video has a verified cut clock."""
    from .source_frame_clock import load_verified_source_frame_clock, source_frame_clock_path_for_video

    receipt_path = source_frame_clock_path_for_video(video_path)
    try:
        receipt = load_verified_source_frame_clock(receipt_path, expected_video_path=video_path)
    except (OSError, ValueError, TypeError):
        return None, None
    try:
        output_fps = float(receipt.get('outputFps', 0.))
    except (TypeError, ValueError, OverflowError):
        return None, None
    try:
        source_fps = float(receipt.get('sourceFps', 0.))
    except (TypeError, ValueError, OverflowError):
        return None, None
    if (receipt.get('outputVideoSha256') != digest
            or receipt.get('outputFrameCount') != frame_count
            or not np.isfinite([output_fps, source_fps]).all()
            or output_fps <= 0. or source_fps <= 0.):
        return None, None
    return ({
        'receiptPath': str(receipt_path.resolve()),
        'receiptSha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        'sourceVideoSha256': receipt.get('sourceVideoSha256'),
        'sourceFrameCount': receipt.get('sourceFrameCount'),
        'sourceFps': receipt.get('sourceFps'),
        'outputVideoPath': str(Path(receipt['outputVideoPath']).resolve()),
        'outputVideoSha256': receipt.get('outputVideoSha256'),
        'outputFrameCount': receipt.get('outputFrameCount'),
        'outputFps': receipt.get('outputFps'),
    }, receipt)


def _verified_source_pose_track_proof(video_path, side, expected_digest):
    """Reopen the canonical pose receipt and recompute its source ankle track."""
    video_path = Path(video_path).expanduser().resolve()
    reference_path = (video_path.parent.parent / 'segment_detection'
                      / 'exact_source_pose_reference.json').resolve()
    try:
        from .bake_and_rank import load_verified_source_pose_reference
        reference = load_verified_source_pose_reference(reference_path, video_path)
        if (not isinstance(reference, dict)
                or reference.get('sourceVideoSha256') != expected_digest):
            return None, None
        pose = reference.get('pose') if isinstance(reference.get('pose'), dict) else reference
        frames = pose.get('frames') if isinstance(pose, dict) else None
        if not isinstance(frames, list) or not frames:
            return None, None
        rows = []
        for frame in frames:
            joints = frame.get('joints') or {}
            rows.append({
                'sourceTimeSec': float(frame.get('sourceTimeSec')),
                'joint': joints.get(f'{side}_ankle'),
                'confidence': (frame.get('jointConfidence') or {}).get(f'{side}_ankle'),
            })
        proof = {
            'sourceVideoSha256': expected_digest,
            'jointName': f'{side}_ankle',
            'stationary': stationary_source_track(pose, f'{side}_ankle'),
            'sourcePoseFrameCount': len(frames),
            'sourcePoseReferencePath': str(reference_path),
            'sourcePoseReferenceSha256': hashlib.sha256(reference_path.read_bytes()).hexdigest(),
            'sourcePoseTrackSha256': hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        }
        return proof, pose
    except (OSError, ValueError, TypeError, OverflowError, AttributeError):
        return None, None


def _dense_sole_review_timeline_rows(evidence, payload, review):
    """Map cached pixel labels to exact pose times, gated by the source ankle track."""
    digest = evidence.get('sourceVideoSha256')
    patch = evidence.get('footPatchEvidence') or {}
    proof = review.get('sourceFrameClockProof') or {}
    if (not digest or review.get('sourceVideoSha256') != digest
            or patch.get('sourceVideoSha256') != digest
            or review.get('sourceFrameCount') != patch.get('sourceFrameCount')):
        return []
    try:
        receipt_path = Path(proof['receiptPath']).expanduser().resolve()
        if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != proof.get('receiptSha256'):
            return []
        from .source_frame_clock import load_verified_source_frame_clock
        receipt = load_verified_source_frame_clock(
            receipt_path, expected_video_path=Path(proof['outputVideoPath']))
    except (KeyError, OSError, ValueError, TypeError):
        return []
    try:
        count = int(review['sourceFrameCount'])
        fps = float(receipt.get('outputFps', 0.))
        proof_fps = float(proof.get('outputFps', -1.))
    except (TypeError, ValueError, OverflowError):
        return []
    if count <= 0 or not np.isfinite([fps, proof_fps]).all():
        return []
    frames = receipt.get('frames') or []
    patch_times = patch.get('sourceTimesSec') or []
    try:
        patch_fps = float(patch.get('sourceFps', 0.))
    except (TypeError, ValueError, OverflowError):
        return []
    if (receipt.get('outputVideoSha256') != digest
            or receipt.get('outputFrameCount') != count
            or proof.get('outputVideoSha256') != digest
            or proof.get('outputFrameCount') != count
            or abs(fps - proof_fps) > .02
            or len(frames) != count or len(patch_times) != count
            or not np.isfinite(patch_fps) or abs(patch_fps - fps) > .02):
        return []

    pose_frames = payload.get('frames') or []
    rows = []
    existing_observation = evidence.get('bodySupportObservation') or {}
    if (existing_observation.get('sourceVideoSha256') != digest
            or existing_observation.get('source') != 'exact_source_visual_support_observation'
            or existing_observation.get('status') != 'observed'):
        return []
    existing_timeline = existing_observation.get('contactTimeline')
    if existing_timeline is not None and validated_body_support_contact_timeline(existing_observation) is None:
        return []

    for side in ('left', 'right'):
        finding = (review.get('feet') or {}).get(side) or {}
        track, verified_pose = _verified_source_pose_track_proof(
            receipt['outputVideoPath'], side, digest)
        declared_track = finding.get('sourcePoseTrackProof') or {}
        if (track is None or track.get('stationary') is not True
                or declared_track != track):
            continue
        verified_pose_frames = verified_pose.get('frames') or []
        for item in finding.get('frameObservations', []):
            if not isinstance(item, dict):
                continue
            output_index = item.get('outputFrameIndex')
            pose_index = item.get('sourcePoseFrameIndex')
            if (type(output_index) is not int or not 0 <= output_index < count
                    or type(pose_index) is not int or not 0 <= pose_index < len(verified_pose_frames)):
                continue
            pose_frame = verified_pose_frames[pose_index]
            try:
                pose_time = float(pose_frame.get('sourceTimeSec'))
                patch_time = float(patch_times[output_index])
                selected_time = float(item.get('sourceTimeSec'))
                selected_source_time = float(item.get('selectedSourceTimeSec'))
            except (TypeError, ValueError, OverflowError):
                continue
            if (not np.isfinite([pose_time, patch_time, selected_time, selected_source_time]).all()
                    or abs(patch_time - pose_time) > 1e-6
                    or abs(selected_time - output_index / fps) > 1e-6):
                continue
            clock_frame = frames[output_index]
            try:
                clock_source_time = float(clock_frame.get('sourceTimeSec'))
            except (TypeError, ValueError, OverflowError):
                continue
            if (item.get('sourceFrameIndex') != clock_frame.get('sourceFrameIndex')
                    or abs(selected_source_time - clock_source_time) > 1e-6
                    or item.get('sourceFrameClockSha256') != proof.get('receiptSha256')):
                continue
            label = item.get('contactState')
            if label not in {'full_sole_ground', 'forefoot_ground'}:
                continue
            if item.get('forefootMotion') != 'stationary':
                continue
            # A moving or unseen heel does not invalidate a planted forefoot.
            state = ('full_sole' if label == 'full_sole_ground'
                     and item.get('heelMotion') == 'stationary' else 'forefoot')
            rows.append({
                'sampleId': f'dense-sole-{digest[:12]}-{side}-{output_index}',
                'side': side,
                'landmark': 'foot',
                'jointName': None,
                'contactState': state,
                'surface': 'ground',
                'visible': True,
                'sourceTrackStationary': True,
                'sourcePoseFrameIndex': pose_index,
                'sourceFrameIndex': output_index,
                'sourceFps': fps,
                'sourceTimeSec': selected_time,
                'sourcePoseTimeSec': pose_time,
                'selectedSourceFrameIndex': clock_frame['sourceFrameIndex'],
                'selectedSourceTimeSec': clock_frame['sourceTimeSec'],
                'sourceFrameClockSha256': proof['receiptSha256'],
            })
    return rows


def _materialize_dense_sole_review_timeline(evidence, payload, review):
    rows = _dense_sole_review_timeline_rows(evidence, payload, review)
    if not rows:
        return
    observed = evidence['bodySupportObservation']
    timeline = observed.get('contactTimeline')
    if timeline is None:
        timeline = {
            'schemaVersion': 1,
            'policyVersion': CONTACT_TIMELINE_POLICY_VERSION,
            'source': 'exact_source_visual_contact_timeline',
            'sourceVideoSha256': evidence['sourceVideoSha256'],
            'sourceClock': 'video_frame_zero_seconds',
            'status': 'observed',
            'samples': [],
        }
        observed['contactTimeline'] = timeline
    existing_ids = {row.get('sampleId') for row in timeline.get('samples') or []
                    if isinstance(row, dict)}
    timeline.setdefault('samples', []).extend(
        row for row in rows if row['sampleId'] not in existing_ids)


def observe_stationary_sole_intervals(video_path, source_pose_reference, evidence, caption_images, cache_dir,
                                      *, ground_contact_mode=None):
    """Review every exposure of a measured stationary stance, using qualitative choices."""
    import cv2
    from .bake_and_rank import call_caption_images_json, extract_json_object, source_review_model_identity
    from .review_questions import answer_question

    video_path, cache_dir = Path(video_path), Path(cache_dir)
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    source_pose_reference = source_pose_reference or {}
    initial_proof, pose = _verified_source_pose_track_proof(video_path, 'left', digest)
    if initial_proof is None or not isinstance(pose, dict):
        return None
    patch = evidence.get('footPatchEvidence') or {}
    answer = validated_body_support_answer(evidence.get('bodySupportObservation')) or {}
    if (source_pose_reference.get('sourceVideoSha256') != digest
            or pose.get('coordinateSpace') != 'normalized_image_xy'
            or (evidence.get('bodySupportObservation') or {}).get('sourceVideoSha256') != digest
            or patch.get('sourceVideoSha256') != digest
            or patch.get('available') is not True):
        return None
    retained = {}
    sides = []
    for side in ('left', 'right'):
        if source_sole_review_side_eligibility(
                evidence, pose, side, ground_contact_mode=ground_contact_mode):
            sides.append(side)
    if not sides:
        return None
    count = int(patch.get('sourceFrameCount') or 0)
    if count <= 0:
        return None
    clock_proof, clock_receipt = _source_frame_clock_proof(video_path, digest, count)
    if (clock_receipt is not None
            and abs(float(clock_receipt.get('outputFps', 0.)) - float(patch.get('sourceFps', -1.))) > .02):
        clock_proof, clock_receipt = None, None
    patch_times = patch.get('sourceTimesSec') or []
    pose_frames = pose.get('frames') or []
    pose_origin = pose.get('sourceTimeOriginSec', 0.)
    patch_origin = patch.get('sourceTimeOriginSec', 0.)
    try:
        pose_origin, patch_origin = float(pose_origin), float(patch_origin)
    except (TypeError, ValueError, OverflowError):
        pose_origin = patch_origin = float('nan')
    pose_frame_by_output_index = {}
    if (clock_receipt is not None and len(patch_times) == count
            and np.isfinite([pose_origin, patch_origin]).all()
            and abs(pose_origin - patch_origin) <= 1e-6):
        for pose_index, pose_frame in enumerate(pose_frames):
            try:
                pose_time = float(pose_frame.get('sourceTimeSec'))
                output_index = int(round((pose_time - pose_origin) * float(clock_receipt['outputFps'])))
            except (TypeError, ValueError, OverflowError):
                continue
            if (0 <= output_index < count
                    and abs(pose_time - pose_origin - output_index / float(clock_receipt['outputFps'])) <= 1e-6
                    and abs(float(patch_times[output_index]) - pose_time) <= 1e-6):
                pose_frame_by_output_index[output_index] = pose_index
    centers = {side: np.median([
        (np.asarray(frame['joints'][f'{side}_heel'][:2])
         + np.asarray(frame['joints'][f'{side}_toe'][:2])) * .5
        for frame in pose.get('frames', [])
        if f'{side}_heel' in (frame.get('joints') or {})
        and f'{side}_toe' in (frame.get('joints') or {})
    ], axis=0).tolist() if any(
        f'{side}_heel' in (frame.get('joints') or {})
        and f'{side}_toe' in (frame.get('joints') or {})
        for frame in pose.get('frames', [])) else None for side in sides}
    for side in sides:
        if centers[side] is None:
            # Ankles locate the crop; only the pixel review establishes sole contact.
            ankles = []
            for frame in pose.get('frames', []):
                try:
                    point = np.asarray((frame.get('joints') or {}).get(f'{side}_ankle'), dtype=float)
                    confidence = float((frame.get('jointConfidence') or {}).get(f'{side}_ankle', 1.))
                except (TypeError, ValueError, OverflowError):
                    continue
                if (point.ndim == 1 and len(point) >= 2 and np.isfinite(point[:2]).all()
                        and np.all((point[:2] >= 0.) & (point[:2] <= 1.))
                        and np.isfinite(confidence) and confidence >= .5):
                    ankles.append(point[:2])
            if len(ankles) >= max(6, .7 * len(pose.get('frames', []))):
                centers[side] = np.median(ankles, axis=0).tolist()
    sides = [side for side in sides if centers[side] is not None]
    if not sides:
        return None
    knees = {side: np.median([
        frame['joints'][f'{side}_knee'][:2] for frame in pose.get('frames', [])
        if f'{side}_knee' in (frame.get('joints') or {})
    ], axis=0).tolist() if any(f'{side}_knee' in (frame.get('joints') or {})
        for frame in pose.get('frames', [])) else None for side in sides}
    cache_dir.mkdir(parents=True, exist_ok=True)
    sheets = {side: [] for side in sides}
    tiles = {side: [] for side in sides}
    sample_ids = []
    capture = cv2.VideoCapture(str(video_path))
    decoded_count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            sample_ids.append(str(decoded_count))
            for side in sides:
                rendered = _render_contact_timeline_crop(cv2, frame, {
                    'side': side, 'sampleId': str(decoded_count), 'point': centers[side],
                    'knee': knees[side]}, mark_target=False)
                if rendered is None:
                    return None
                tiles[side].append(rendered[0])
            decoded_count += 1
            if len(sample_ids) == _CONTACT_TIMELINE_FOOT_BATCH_SIZE or decoded_count == count:
                for side in sides:
                    atlas, _ = _assemble_contact_timeline_atlas(tiles[side], sample_ids)
                    pixels_sha = hashlib.sha256(atlas.tobytes()).hexdigest()[:12]
                    path = cache_dir / f'{digest}-{side}-stance-{len(sheets[side])}-{pixels_sha}.png'
                    if not cv2.imwrite(str(path), atlas):
                        raise OSError(f'Cannot write stance review image: {path}')
                    sheets[side].append(path)
                    tiles[side] = []
                sample_ids = []
    finally:
        capture.release()
    if decoded_count != count or sample_ids:
        return None
    choices = ['stationary_full_sole_ground', 'stationary_forefoot_ground',
               'moving_or_releasing', 'insufficient_evidence']
    settings = getattr(getattr(caption_images, '__self__', None), 'settings', None)
    model_identity = source_review_model_identity(settings)
    result = {'sourceVideoSha256': digest, 'sourceFrameCount': count,
              'framesPerChunk': _CONTACT_TIMELINE_FOOT_BATCH_SIZE,
              'sourceFrameClockProof': clock_proof, 'feet': retained}
    for side in sides:
        track_proof, verified_side_pose = _verified_source_pose_track_proof(
            video_path, side, digest)
        if track_proof is None or not isinstance(verified_side_pose, dict):
            return None
        conclusions = []
        frame_observations = []
        pages = []
        for chunk, sheet in enumerate(sheets[side]):
            sample_ids = [str(index) for index in range(chunk * _CONTACT_TIMELINE_FOOT_BATCH_SIZE,
                min((chunk + 1) * _CONTACT_TIMELINE_FOOT_BATCH_SIZE, count))]
            local_schema = _contact_timeline_response_schema(sample_ids)
            local_schema['properties'].update({field: {'type': 'string',
                'enum': ['stationary', 'moving', 'not_visible']}
                for field in ('heelMotion', 'forefootMotion')})
            local_schema['required'] += ['heelMotion', 'forefootMotion']
            local_prompt = ('Inspect the foot panels in this single PNG. Each panel has a sole close-up '
                            'and a code-owned sample ID. Report visible sole state and surface for each ID: '
                            'full_sole only when heel and forefoot both touch, forefoot when the heel is raised, '
                            'heel_only when the forefoot is raised, airborne when no shoe contact is visible, '
                            'and unresolved when hidden or ambiguous. Judge each panel independently; '
                            'do not infer contact between samples or from stationary motion. '
                            'Separately, report heelMotion and forefootMotion across these chronological '
                            'target-shoe panels: stationary if the region stays at the same ground location, '
                            'moving if it translates or rolls, and not_visible if hidden or ambiguous. '
                            'The yellow tick is an anatomical locator; source pixels are unmarked.')
            output_indexes = [int(sample_id) for sample_id in sample_ids]
            sampling = [{
                'sampleId': sample_id,
                'outputFrameIndex': output_index,
                'selectedSourceFrameIndex': (clock_receipt['frames'][output_index].get('sourceFrameIndex')
                                             if clock_receipt is not None else None),
                'selectedSourceTimeSec': (clock_receipt['frames'][output_index].get('sourceTimeSec')
                                          if clock_receipt is not None else None),
                'sourceTimeSec': (output_index / float(clock_receipt['outputFps'])
                                  if clock_receipt is not None else None),
                'sourcePoseFrameIndex': pose_frame_by_output_index.get(output_index),
                'sourcePoseTimeSec': (patch_times[output_index]
                                      if output_index < len(patch_times) else None),
            } for sample_id, output_index in zip(sample_ids, output_indexes)]
            legacy_identity = {'model': model_identity, 'sourceVideoSha256': digest,
                               'side': side, 'schema': local_schema}
            sourcebound_identity = {
                **legacy_identity,
                'sourcePoseTrackProof': track_proof,
                'sourceFrameClockProof': clock_proof,
                'sampling': sampling,
                'promptPolicy': _STATIONARY_SOLE_REVIEW_PROMPT_POLICY,
            }
            pages.append({
                'chunk': chunk, 'sheet': sheet, 'sampleIds': sample_ids,
                'legacySchema': local_schema, 'legacyPrompt': local_prompt,
                'legacyIdentity': legacy_identity,
                'sourceboundIdentity': sourcebound_identity,
                'parsed': None,
            })

        def is_reusable_page(page, value):
            return _stance_from_frame_contacts(value, page['sampleIds']) is not None

        def persist_page_cache(page, raw, parsed):
            reusable = lambda value: is_reusable_page(page, value)
            answer_question(directory=cache_dir / 'questions', name='stance-interval-sourcebound',
                prompt=page['legacyPrompt'], frames=[page['sheet']], max_tokens=600,
                identity=page['sourceboundIdentity'],
                operation=lambda: (raw, parsed), reusable=reusable)
            # Keep the exact legacy one-sheet cache usable by older consumers.
            answer_question(directory=cache_dir / 'questions', name='stance-interval',
                prompt=page['legacyPrompt'], frames=[page['sheet']], max_tokens=600,
                identity=page['legacyIdentity'],
                operation=lambda: (raw, parsed), reusable=reusable)

        missing_pages = []
        for page in pages:
            parsed = _load_cached_stance_question(
                directory=cache_dir / 'questions', name='stance-interval-sourcebound',
                prompt=page['legacyPrompt'], frames=[page['sheet']], max_tokens=600,
                identity=page['sourceboundIdentity'],
                reusable=lambda value, page=page: is_reusable_page(page, value))
            if parsed is None:
                parsed = _load_cached_stance_question(
                    directory=cache_dir / 'questions', name='stance-interval',
                    prompt=page['legacyPrompt'], frames=[page['sheet']], max_tokens=600,
                    identity=page['legacyIdentity'],
                    reusable=lambda value, page=page: is_reusable_page(page, value))
                if parsed is not None:
                    persist_page_cache(page, parsed[0], parsed[1])
            if parsed is None:
                missing_pages.append(page)
            else:
                page['parsed'] = parsed[1]

        for group_start in range(0, len(missing_pages), _STATIONARY_SOLE_REVIEW_IMAGES_PER_REQUEST):
            group = missing_pages[group_start:group_start + _STATIONARY_SOLE_REVIEW_IMAGES_PER_REQUEST]
            group_sample_ids = [sample_id for page in group for sample_id in page['sampleIds']]
            schema = _contact_timeline_response_schema(group_sample_ids)
            motion_names = []
            page_descriptions = []
            for group_index, page in enumerate(group):
                heel_field = f'heelMotion_image_{group_index}'
                forefoot_field = f'forefootMotion_image_{group_index}'
                page['batchMotionFields'] = (heel_field, forefoot_field)
                motion_names.extend((heel_field, forefoot_field))
                schema['properties'][heel_field] = {'type': 'string',
                    'enum': ['stationary', 'moving', 'not_visible']}
                schema['properties'][forefoot_field] = {'type': 'string',
                    'enum': ['stationary', 'moving', 'not_visible']}
                schema['required'].extend((heel_field, forefoot_field))
                page_descriptions.append(
                    f'Image {group_index + 1} contains sample IDs {", ".join(page["sampleIds"])}; '
                    f'report its heel and forefoot motion using {heel_field} and {forefoot_field}.')
            prompt = (
                'Inspect the supplied foot-panel images in input order. Each image contains six or fewer '
                'chronological panels, each with a sole close-up and a code-owned sample ID. '
                'For each sample ID report visible sole state and surface: full_sole only when heel and '
                'forefoot both touch, forefoot when the heel is raised, heel_only when the forefoot is '
                'raised, airborne when no shoe contact is visible, and unresolved when hidden or ambiguous. '
                'Judge each panel independently; do not infer contact between samples or from stationary motion. '
                + ' '.join(page_descriptions) + ' '
                + 'For each image, report motion separately: stationary if that image group\'s region stays '
                'at the same ground location, moving if it translates or rolls, and not_visible if hidden or '
                'ambiguous. The yellow tick is an anatomical locator; source pixels are unmarked.')
            group_identity = {
                'model': model_identity,
                'sourceVideoSha256': digest,
                'side': side,
                'schema': schema,
                'sourcePoseTrackProof': track_proof,
                'sourceFrameClockProof': clock_proof,
                'sampling': [sample for page in group for sample in page['sourceboundIdentity']['sampling']],
                'promptPolicy': _STATIONARY_SOLE_REVIEW_PROMPT_POLICY,
                'imageCount': len(group),
            }

            def group_reusable(value):
                if not isinstance(value, dict) or set(value) != set(schema['properties']):
                    return False
                return all(_stance_from_frame_contacts({
                    **{sample_id: value[sample_id] for sample_id in page['sampleIds']
                       if sample_id in value},
                    'heelMotion': value[page['batchMotionFields'][0]],
                    'forefootMotion': value[page['batchMotionFields'][1]],
                }, page['sampleIds']) is not None for page in group)

            def ask_group():
                raw = call_caption_images_json(
                    caption_images, frame_paths=[page['sheet'] for page in group],
                    prompt=prompt, max_tokens=600, disable_reasoning=True,
                    json_response=True, response_schema=schema,
                    temperature=0., top_p=1., top_k=1)
                return raw, extract_json_object(raw)

            raw, parsed = answer_question(
                directory=cache_dir / 'questions', name='stance-interval-batch-v2',
                prompt=prompt, frames=[page['sheet'] for page in group], max_tokens=600,
                identity=group_identity, operation=ask_group, reusable=group_reusable)
            for group_index, page in enumerate(group):
                if not isinstance(parsed, dict):
                    continue
                heel_field, forefoot_field = page['batchMotionFields']
                if not all(sample_id in parsed for sample_id in page['sampleIds']) \
                        or heel_field not in parsed or forefoot_field not in parsed:
                    continue
                page_answer = {
                    **{sample_id: parsed[sample_id] for sample_id in page['sampleIds']},
                    'heelMotion': parsed[heel_field],
                    'forefootMotion': parsed[forefoot_field],
                }
                if is_reusable_page(page, page_answer):
                    page_raw = json.dumps(page_answer, separators=(',', ':'))
                    persist_page_cache(page, page_raw, page_answer)
                    page['parsed'] = page_answer

        for page in pages:
            parsed = page['parsed']
            sample_ids = page['sampleIds']
            category = _stance_from_frame_contacts(parsed, sample_ids)
            conclusions.append(category)
            if isinstance(parsed, dict) and clock_receipt is not None:
                for sample_id in sample_ids:
                    output_index = int(sample_id)
                    clock_frame = clock_receipt['frames'][output_index]
                    frame_observations.append({
                        'outputFrameIndex': output_index,
                        'sourceFrameIndex': clock_frame['sourceFrameIndex'],
                        'selectedSourceTimeSec': clock_frame['sourceTimeSec'],
                        'sourceTimeSec': output_index / float(clock_receipt['outputFps']),
                        'sourcePoseTimeSec': patch_times[output_index],
                        'sourceFrameClockSha256': clock_proof['receiptSha256'],
                        'sourcePoseFrameIndex': pose_frame_by_output_index.get(output_index),
                        'contactState': parsed[sample_id],
                        'heelMotion': parsed['heelMotion'],
                        'forefootMotion': parsed['forefootMotion'],
                    })
        reviewed_frame_count = sum(
            len(page['sampleIds']) for page in pages
            if _stance_from_frame_contacts(page['parsed'], page['sampleIds']) is not None)
        result['feet'][side] = {'reviewedFrameCount': reviewed_frame_count,
            'confirmed': bool(conclusions) and all(value in choices[:2] for value in conclusions),
            'decisions': conclusions,
            'sourcePoseTrackProof': track_proof,
            'frameObservations': frame_observations}
    return result


def stationary_source_track(source_pose, joint, *, max_leading_gap_ratio=0.15):
    """Reject absent, sparse, moving, or low-confidence source observations."""
    from .bake_and_rank import (
        SOURCE_POSE_SUPPORT_STATIONARY_CHUNK_RANGE_RATIO_THRESHOLD,
        SOURCE_POSE_SUPPORT_STATIONARY_ENDPOINT_RATIO_THRESHOLD,
    )
    frames = (source_pose or {}).get('frames') or []
    if len(frames) < 6:
        return False
    key = 'nose' if joint == 'head' else joint
    tracks = []
    spans = []
    for index, frame in enumerate(frames):
        joints = frame.get('joints') or {}
        p = joints.get(key)
        confidence = (frame.get('jointConfidence') or {}).get(key, 1.)
        if (p is not None and confidence >= .5 and np.isfinite(p[:2]).all()
                and (source_pose.get('coordinateSpace') != 'normalized_image_xy'
                     or all(0. <= value <= 1. for value in p[:2]))):
            tracks.append((index, np.asarray(p[:2], dtype=float)))
        if joints:
            points = np.asarray(list(joints.values()), dtype=float)[:, :2]
            spans.append(np.linalg.norm(np.ptp(points, axis=0)))
    if len(tracks) < max(6, .7*len(frames)) or not spans:
        return False
    indexes, points = zip(*tracks)
    if (indexes[0] > max_leading_gap_ratio*len(frames)
            or indexes[-1] < .85*(len(frames)-1)):
        return False
    centers = np.asarray([np.median(chunk, axis=0) for chunk in np.array_split(points, 4)])
    scale = max(float(np.median(spans)), 1e-8)
    return bool(np.isfinite(centers).all()
                and np.linalg.norm(np.ptp(centers, axis=0))/scale
                <= SOURCE_POSE_SUPPORT_STATIONARY_CHUNK_RANGE_RATIO_THRESHOLD
                and np.linalg.norm(centers[-1]-centers[0])/scale
                <= SOURCE_POSE_SUPPORT_STATIONARY_ENDPOINT_RATIO_THRESHOLD)


def _has_timed_direct_contact(observed, joint, surface, source_pose=None, *, require_stationary=True):
    rows = validated_body_support_contact_timeline(observed) or []
    matching = [row for row in rows if row.get('jointName') == joint]
    if len(matching) < 2 or any(row.get('contactState') != 'direct_contact'
           or row.get('surface') != surface or row.get('visible') is not True
           or (require_stationary and row.get('sourceTrackStationary') is not True)
           for row in matching):
        return False
    if source_pose is not None:
        reference = source_pose if isinstance(source_pose, dict) else {}
        pose = (reference.get('pose') if isinstance(reference.get('pose'), dict) else reference)
        digest = reference.get('sourceVideoSha256') or pose.get('sourceVideoSha256')
        if not digest or digest != observed.get('sourceVideoSha256'):
            return False
        frames = (pose or {}).get('frames') or []
        if any(row['sourcePoseFrameIndex'] >= len(frames)
               or not isinstance(frames[row['sourcePoseFrameIndex']].get('sourceTimeSec'), (int, float))
               or not abs(float(frames[row['sourcePoseFrameIndex']]['sourceTimeSec'])
                          - row['sourceTimeSec']) <= 1e-6 for row in matching):
            return False
    return len({row['sourceTimeSec'] for row in matching}) >= 2


def _has_timed_regional_direct_contact(observed, region, surface, source_pose=None, *, side=None):
    """Require exact-time visible region contact, not an inferred joint anchor."""
    rows = validated_body_support_contact_timeline(observed) or []
    side = 'center' if region == 'upper_back' else side
    if region == 'foot' and side not in {'left', 'right'}:
        return False
    matching = [row for row in rows if row.get('landmark') == 'region'
                and row.get('contactRegion') == region
                and (side is None or row.get('side') == side)]
    minimum_samples = 3 if region == 'foot' else 2
    if (len(matching) < minimum_samples or any(
            row.get('contactState') != 'direct_contact'
            or row.get('surface') != surface or row.get('visible') is not True
            for row in matching)):
        return False
    if not isinstance(source_pose, dict):
        return False
    pose = source_pose.get('pose') if isinstance(source_pose.get('pose'), dict) else source_pose
    digest = source_pose.get('sourceVideoSha256') or (pose or {}).get('sourceVideoSha256')
    if not digest or digest != observed.get('sourceVideoSha256'):
        return False
    frames = (pose or {}).get('frames') or []
    if any(row['sourcePoseFrameIndex'] >= len(frames)
           or not isinstance(frames[row['sourcePoseFrameIndex']].get('sourceTimeSec'), (int, float))
           or abs(float(frames[row['sourcePoseFrameIndex']]['sourceTimeSec'])
                  - row['sourceTimeSec']) > 1e-6 for row in matching):
        return False
    return len({row['sourceTimeSec'] for row in matching}) >= minimum_samples


def observed_body_support_contact_claims(observed, source_pose=None):
    """Return only source-verified (joint locator, support surface) claims."""
    answer = validated_body_support_answer(observed)
    if answer is None:
        return {}
    contacts = {}
    for region, joints in (('pelvis', ('pelvis',)),
                           ('upperBack', ('left_shoulder', 'right_shoulder')),
                           ('head', ('head',))):
        surface = answer.get(f'{region}ContactSurface')
        if answer.get(region) == 'stationary_support':
            contacts.update({joint: surface for joint in joints
                             if _has_timed_direct_contact(observed, joint, surface, source_pose)})
    for side in ('left', 'right'):
        for region, joint_region in (('Hand', 'wrist'), ('Ankle', 'ankle'), ('Knee', 'knee')):
            field = f'{side}{region}'
            joint = f'{side}_{joint_region}'
            if (answer.get(field) == 'stationary_support'
                    and _has_timed_direct_contact(
                        observed, joint, answer.get(f'{field}ContactSurface'), source_pose)):
                contacts[joint] = answer.get(f'{field}ContactSurface')
    return contacts


def observed_body_support_contacts(observed, source_pose=None):
    """Only exact-time visible contact can authorize a persistent anchor."""
    return set(observed_body_support_contact_claims(observed, source_pose))


def remove_unobserved_torso_support(evidence):
    support = evidence.get('bodySupport') or {}
    if support.get('reason') == 'supported_reference_body_requires_observed_surface_geometry':
        evidence.pop('bodySupport', None)
    elif support.get('source') == 'exact_source_contacts_and_stationary_pose_tracks':
        observed = evidence.get('bodySupportObservation') or {}
        answer = validated_body_support_answer(observed)
        same_source = (
            answer is not None
            and support.get('sourceVideoSha256') == observed.get('sourceVideoSha256')
        )
        contacts = observed_body_support_contacts(observed) if same_source else set()
        if not set(BODY_SUPPORT_ANCHORS).issubset(contacts):
            contacts = set()
        removed = set(BODY_SUPPORT_ANCHORS) | {'head', 'neck', 'spine1', 'spine2', 'spine3'}
        if contacts:
            removed -= contacts | {'neck', 'spine1', 'spine2', 'spine3'}
        if not same_source:
            for side in ('left', 'right'):
                removed.update((f'{side}_ankle', f'{side}_foot'))
        _remove_materialized_support_joints(evidence, removed)


def materialize_body_support(payload, source_pose, contract=None):
    """Convert confirmed contacts to constraints in the baked coordinate frame.

    Stationary anchors respect the contract's primary movers (e.g. shoulders on
    a lying press). Readiness and plane pin use that filtered anchor set; the
    bench/normal direction may still be estimated from torso landmark medians.
    """
    source_reference = source_pose if isinstance(source_pose, dict) else {}
    source_pose = (source_reference.get('pose') if isinstance(source_reference.get('pose'), dict)
                   else source_reference)
    evidence = payload.get('sourceFootSupportEvidence') or {}
    remove_unobserved_torso_support(evidence)
    observed = evidence.get('bodySupportObservation') or {}
    anchors = list(body_support_required_anchors(
        contract, source_pose=source_reference, observed=observed))
    existing = evidence.get('bodySupport') or {}
    if (existing.get('status') == 'confirmed'
            and set(BODY_SUPPORT_ANCHORS).intersection(existing.get('stationaryJoints') or [])
            and set(anchors).issubset(existing.get('stationaryJoints') or [])):
        # Add foot anchors only when the temporal patch confirms full sole for
        # every selected frame; keep existing torso constraints intact.
        _augment_confirmed_ground_sole_support(payload, evidence, source_pose)
        return
    answer = validated_body_support_answer(observed)
    if answer is None:
        return
    contacts = observed_body_support_contacts(observed, source_reference)
    if not (set(BODY_SUPPORT_ANCHORS).issubset(contacts)
            and answer.get('pelvisAndUpperBackSameSurface') is True
            and answer.get('pelvis') == answer.get('upperBack') == 'stationary_support'
            and answer.get('torsoSurface') in {'horizontal', 'inclined', 'vertical'}
            and body_support_source_readiness(source_reference, contract, observed=observed)['ready']):
        return
    if not anchors:
        return
    names = payload.get('jointNames') or []
    plane_refs = [name for name in BODY_SUPPORT_ANCHORS if name in names]
    required = list(dict.fromkeys([*anchors, *plane_refs, 'neck', 'spine1', 'spine2', 'spine3']))
    if not set(required).issubset(names) or not payload.get('frames'):
        return
    medians = {n: np.median([f['joints'][n] for f in payload['frames']], axis=0) for n in names}
    normal = np.array([0., 1., 0.])
    if answer['torsoSurface'] != 'horizontal':
        side = medians['right_shoulder']-medians['left_shoulder']
        longitudinal = (medians['left_shoulder']+medians['right_shoulder'])*.5-medians['pelvis']
        normal = np.cross(side, longitudinal)
        if np.linalg.norm(normal) < 1e-8:
            return
        normal /= np.linalg.norm(normal)
        if normal[1] < 0:
            normal *= -1
    normal = normal.tolist()
    plane_offset = float(np.dot(medians[anchors[0]], normal))
    support = {'required': True, 'status': 'confirmed',
               'source': 'exact_source_contacts_and_stationary_pose_tracks',
               'sourceVideoSha256': observed['sourceVideoSha256'],
               'observation': deepcopy(answer), 'stationaryJoints': list(anchors),
               'coplanarGroups': [{'joints': list(anchors), 'normal': normal,
                                   'anchorJoint': anchors[0],
                                   'planeOffsetMeters': plane_offset}],
               'nonPenetrationChains': [{'endpoints': ['pelvis', 'neck'],
                                         'joints': ['spine1', 'spine2', 'spine3'], 'normal': normal}],
               'soleContacts': []}
    if 'head' in contacts and stationary_source_track(source_pose, 'head'):
        support['stationaryJoints'].append('head')
    sides = []
    for side in ('left', 'right'):
        if (answer.get(f'{side}Foot') != 'stationary_full_sole'
                or answer.get(f'{side}FootSurface') != 'ground'
                or not _has_uninterrupted_full_sole_patch(evidence, side)
                or not stationary_source_track(source_pose, f'{side}_ankle')):
            continue
        sides.append(side)
    add_ground_sole_contacts(payload, support, medians, sides, evidence=evidence)
    evidence['bodySupport'] = support


def _support_for_observed_contacts(evidence, observed):
    support = evidence.get('bodySupport') or {}
    if support.get('required') and support.get('status') != 'confirmed':
        return None  # Distal evidence cannot resolve an unknown torso support.
    return deepcopy(support) if support else {
        'required': True, 'status': 'confirmed',
        'source': 'exact_source_contacts_and_stationary_pose_tracks',
        'sourceVideoSha256': observed.get('sourceVideoSha256'),
        'stationaryJoints': [], 'coplanarGroups': [],
        'nonPenetrationChains': [], 'soleContacts': []}


def materialize_knee_support(payload, source_pose_reference):
    """Pin a stationary knee only when visible same-source timed contact confirms it."""
    evidence = payload.get('sourceFootSupportEvidence') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed) or {}
    reference = source_pose_reference or {}
    pose = reference.get('pose') or {}
    same_source = (bool(observed.get('sourceVideoSha256'))
                   and reference.get('sourceVideoSha256') == observed.get('sourceVideoSha256')
                   and observed.get('sourceClock') == 'video_frame_zero_seconds')
    times = [frame.get('sourceTimeSec') for frame in pose.get('frames') or []]
    valid_clock = (len(times) >= 6 and all(isinstance(t, (int, float)) and np.isfinite(t)
                                        and t >= 0 for t in times)
                   and all(b > a for a, b in zip(times, times[1:])))
    stationary = [f'{side}_knee' for side in ('left', 'right')
                  if same_source and valid_clock
                  and answer.get(f'{side}Knee') == 'stationary_support'
                  and answer.get(f'{side}KneeContactSurface') in _SUPPORT_SURFACES
                  and _has_timed_direct_contact(
                      observed, f'{side}_knee', answer.get(f'{side}KneeContactSurface'), reference)
                  and f'{side}_knee' in payload.get('jointNames', [])
                  and stationary_source_track(pose, f'{side}_knee')]
    _remove_materialized_support_joints(
        evidence, {'left_knee', 'right_knee'} - set(stationary))
    if not stationary:
        return
    support = _support_for_observed_contacts(evidence, observed)
    if support is None:
        return
    support['stationaryJoints'] = list(dict.fromkeys(support['stationaryJoints'] + stationary))
    support['observation'] = deepcopy(answer)
    evidence['bodySupport'] = support


NONFOOT_SUPPORT_RECEIPT_SCHEMA_VERSION = 1


def _nonfoot_support_receipts(observed, source_pose, joint, surface,
                              source_video_path, track_proof):
    """Create one source-time anchor per validated visible contact sample."""
    rows = [row for row in (validated_body_support_contact_timeline(observed) or [])
            if row.get('jointName') == joint]
    if (len(rows) < 2 or not source_video_path
            or not isinstance(track_proof, dict)
            or track_proof.get('stationary') is not True
            or any(row.get('contactState') != 'direct_contact'
                   or row.get('surface') != surface
                   or row.get('visible') is not True
                   or row.get('sourceTrackStationary') is not True
                   for row in rows)
            or len({float(row['sourceTimeSec']) for row in rows}) < 2):
        return None
    digest = str(observed.get('sourceVideoSha256') or '')
    pose = (source_pose.get('pose') if isinstance(source_pose, dict)
            and isinstance(source_pose.get('pose'), dict) else source_pose) or {}
    frames = pose.get('frames') or []
    facts = []
    for row in rows:
        pose_index = row.get('sourcePoseFrameIndex')
        if (type(pose_index) is not int or pose_index < 0 or pose_index >= len(frames)
                or not isinstance(frames[pose_index].get('sourceTimeSec'), (int, float))
                or abs(float(frames[pose_index]['sourceTimeSec'])
                       - float(row['sourceTimeSec'])) > 1e-6):
            return None
        facts.append({
            'sampleId': str(row['sampleId']),
            'side': row['side'],
            'jointName': row['jointName'],
            'contactState': row['contactState'],
            'surface': row['surface'],
            'visible': row['visible'],
            'sourceTrackStationary': row['sourceTrackStationary'],
            'sourceTimeSec': float(row['sourceTimeSec']),
            'sourceFrameIndex': int(row['sourceFrameIndex']),
            'sourcePoseFrameIndex': int(row['sourcePoseFrameIndex']),
            'sourceFps': float(row['sourceFps']),
        })
    receipts = []
    for fact in facts:
        timestamp = fact['sourceTimeSec']
        frame = frames[fact['sourcePoseFrameIndex']]
        if abs(float(frame['sourceTimeSec']) - timestamp) > 1e-6:
            return None
        receipts.append({
            'schemaVersion': NONFOOT_SUPPORT_RECEIPT_SCHEMA_VERSION,
            'source': 'verified_nonfoot_support_source_rows',
            'sourceVideoSha256': digest,
            'sourceClock': 'video_frame_zero_seconds',
            'jointName': joint,
            'surfaceKind': surface,
            'rowId': fact['sampleId'],
            'row': fact,
            'sourcePoseVideoPath': str(Path(source_video_path).expanduser().resolve()),
            'sourcePoseTrackProof': deepcopy(track_proof),
        })
    return receipts


def materialize_ankle_support(payload, source_pose, *, source_video_path=None):
    """Join visible external restraint with independent ankle stationarity.

    A restrained ankle is a point contact, not a sole or measured support plane.
    Its 3-D anchor estimate remains owned by the existing contact calibration.
    """
    source_reference = source_pose if isinstance(source_pose, dict) else {}
    source_pose = (source_reference.get('pose') if isinstance(source_reference.get('pose'), dict)
                   else source_reference)
    evidence = payload.get('sourceFootSupportEvidence') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed) or {}
    from .contact_constraints import motion_support_contacts
    previous = {row.get('jointName') for row in motion_support_contacts(evidence)
                if row.get('supportKind') == 'observed_stationary_ankle_restraint'}
    for key in ('contacts', 'supportContacts'):
        if isinstance(evidence.get(key), list):
            evidence[key][:] = [row for row in evidence[key]
                                if row.get('supportKind') != 'observed_stationary_ankle_restraint']
    contacts = evidence.setdefault('supportContacts', [])
    times = [frame.get('sourceTimeSec') for frame in (source_pose or {}).get('frames', [])]
    valid_clock = (len(times) >= 6
                   and all(isinstance(t, (int, float)) and np.isfinite(t) and t >= 0 for t in times)
                   and all(last > first for first, last in zip(times, times[1:])))
    same_source = (bool(observed.get('sourceVideoSha256'))
                   and source_reference.get('sourceVideoSha256', source_pose.get('sourceVideoSha256'))
                   == observed['sourceVideoSha256']
                   and observed.get('sourceClock') == 'video_frame_zero_seconds' and valid_clock)
    stationary = []
    for side in ('left', 'right'):
        name = f'{side}_ankle'
        if (not same_source or name not in payload.get('jointNames', [])
                or answer.get(f'{side}Ankle') != 'stationary_support'
                or answer.get(f'{side}AnkleContactSurface') not in _ANKLE_SUPPORT_SURFACES
                or not source_video_path):
            continue
        track_proof, verified_pose = _verified_source_pose_track_proof(
            source_video_path, side, observed['sourceVideoSha256'])
        if (track_proof is None or track_proof.get('stationary') is not True
                or not _has_timed_direct_contact(
                    observed, name, answer.get(f'{side}AnkleContactSurface'), verified_pose)):
            continue
        receipts = _nonfoot_support_receipts(
            observed, verified_pose, name, answer[f'{side}AnkleContactSurface'],
            source_video_path, track_proof)
        if not receipts:
            continue
        for receipt in receipts:
            timestamp = float(receipt['row']['sourceTimeSec'])
            contacts.append({'jointName': name,
                             'supportKind': 'observed_stationary_ankle_restraint',
                             'contactMotion': 'stationary', 'verticalOnly': False,
                             'surfaceKind': answer[f'{side}AnkleContactSurface'],
                             'anchorKind': 'ankle',
                             'sourceTimeBasis': 'absolute_source_video',
                             'sourceClock': 'video_frame_zero_seconds',
                             'sourcePoseStartTimeSec': timestamp,
                             'sourcePoseEndTimeSec': timestamp,
                             'startRatio': 0., 'endRatio': 1.,
                             'sourceVideoSha256': observed['sourceVideoSha256'],
                             'nonFootSupportReceipt': receipt})
        stationary.append(name)
    _remove_materialized_support_joints(evidence, previous - set(stationary))
    if stationary:
        support = _support_for_observed_contacts(evidence, observed)
        if support is not None:
            # Contact identity is observed; its estimated 3-D location must be
            # calibrated in the same fixed rig as the other stationary joints.
            support['stationaryJoints'] = list(dict.fromkeys(support['stationaryJoints'] + stationary))
            support['observation'] = deepcopy(answer)
            evidence['bodySupport'] = support


def materialize_hand_support(payload, source_pose):
    """Anchor physical hands using wrist tracks only as source locators."""
    source_reference = source_pose if isinstance(source_pose, dict) else {}
    source_pose = (source_reference.get('pose') if isinstance(source_reference.get('pose'), dict)
                   else source_reference)
    evidence = payload.get('sourceFootSupportEvidence') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed) or {}
    pixel_tracks = evidence.get('supportRelativePixelTracks') or {}
    pixel_contacts = (pixel_tracks.get('stationaryContactEvidence') or {}
                      if pixel_tracks.get('sourceVideoSha256') == observed.get('sourceVideoSha256')
                      else {})
    same_source = (bool(observed.get('sourceVideoSha256'))
                   and source_reference.get('sourceVideoSha256', source_pose.get('sourceVideoSha256'))
                   == observed.get('sourceVideoSha256'))
    names = set(payload.get('jointNames', []))
    stationary = [f'{side}_hand' if f'{side}_hand' in names else f'{side}_wrist'
                  for side in ('left', 'right')
                  if same_source and answer.get(f'{side}Hand') == 'stationary_support'
                  and f'{side}_wrist' in names
                  and _has_timed_direct_contact(
                      observed, f'{side}_wrist', answer.get(f'{side}HandContactSurface'), source_pose)
                  and (pixel_contacts.get(f'{side}_wrist') or {}).get('movesWithBody') is not True
                  and stationary_source_track(source_pose, f'{side}_wrist')]
    support = evidence.get('bodySupport') or {}
    hand_joints = {f'{side}_{joint}' for side in ('left', 'right') for joint in ('wrist', 'hand')}
    stale = hand_joints - set(stationary)
    if support.get('source') == 'exact_source_contacts_and_stationary_pose_tracks':
        _remove_materialized_support_joints(evidence, stale)
    if not stationary:
        return
    support = _support_for_observed_contacts(evidence, observed)
    if support is None:
        return
    support['stationaryJoints'] = list(dict.fromkeys(support['stationaryJoints'] + stationary))
    group = {'joints': stationary, 'normal': [0., 1., 0.]}
    if (len(stationary) == 2 and answer.get('handsSameHorizontalSurface') is True
            and group not in support['coplanarGroups']):
        support['coplanarGroups'].append(group)
    evidence['bodySupport'] = support

def materialize_observed_ground_contacts(payload, source_pose):
    """Full sole and forefoot observations can establish a planted toe.

    Temporal patch evidence must corroborate a full-clip anchor; partial source
    contacts remain interval constraints. This deliberately says nothing about
    heel height or shoe pitch, which require independent heel/toe geometry.
    """
    evidence = payload.get('sourceFootSupportEvidence') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed)
    if answer is None:
        return
    floor = payload.get('renderFloorY')
    patch = evidence.get('footPatchEvidence') or {}
    temporal_patch_available = patch.get('available') is True
    source_confirmed_sides = _augment_confirmed_ground_sole_support(
        payload, evidence, source_pose)
    if temporal_patch_available:
        patch_contact_count = len(payload.get('frames') or [])
        full_cycle_sides = {
            side for side in ('left', 'right')
            if _has_full_cycle_stationary_sole(evidence, side, patch_contact_count)
        }
        full_cycle_sides.update(source_confirmed_sides)
        _remove_unverified_materialized_foot_support(evidence, full_cycle_sides)
    # A few support-review frames cannot establish an uninterrupted ground
    # anchor when the movement permits release. First remove stale cached
    # full-clip anchors using temporal evidence, then retain only timed contacts.
    if payload.get('groundContactMode') in {'intermittent', 'none'}:
        return
    if (observed.get('status') != 'observed' or not isinstance(floor, (int, float))
            or not np.isfinite(floor)):
        return
    contacts = []
    for side in ('left', 'right'):
        states = ((evidence.get('footPatchEvidence') or {}).get('feet', {}).get(side) or {}).get('states', [])
        if (answer.get(f'{side}Foot') in {'stationary_full_sole', 'stationary_forefoot'}
                and answer.get(f'{side}FootSurface') == 'ground'
                and f'{side}_foot' in payload.get('jointNames', [])
                and stationary_source_track(source_pose, f'{side}_ankle')
                and not any(state in {'airborne', 'heel_only'} for state in states)):
            if temporal_patch_available and side not in full_cycle_sides:
                continue
            contacts.append(f'{side}_foot')
    if not contacts:
        return
    support = _support_for_observed_contacts(evidence, observed)
    if support is None:
        return
    # Existing calibrated full-sole geometry already owns these toe heights.
    contacts = [name for name in contacts if name not in support['stationaryJoints']]
    if not contacts:
        return
    support['stationaryJoints'].extend(contacts)
    support['coplanarGroups'].append({'joints': contacts, 'normal': [0., 1., 0.],
                                     'planeOffsetMeters': float(floor)})
    evidence['bodySupport'] = support


def add_ground_sole_contacts(payload, support, medians, sides, *, evidence):
    """Use the same shoe dimensions for every explicitly observed ground contact."""
    camera_reference = payload.get('sourcePoseCameraReference') or {}
    camera = camera_reference.get('camera') or {}
    source_labels_swapped = (
        camera.get('bilateralAssignment') == 'swapped'
        and not isinstance(evidence.get('motionSpaceMapping'), dict)
    )
    for side in sides:
        ankle, foot, knee = [f'{side}_{part}' for part in ('ankle', 'foot', 'knee')]
        if not {ankle, foot, knee}.issubset(medians):
            continue
        # Canonical source labels can name the opposite baked rig side. Keep
        # constraint labels canonical, but measure geometry on their rig side.
        geometry_side = ('right' if side == 'left' else 'left') if source_labels_swapped else side
        geometry_ankle, geometry_foot = (f'{geometry_side}_{part}' for part in ('ankle', 'foot'))
        if not {geometry_ankle, geometry_foot}.issubset(medians):
            continue
        for joint in (ankle, foot):
            if joint not in support['stationaryJoints']:
                support['stationaryJoints'].append(joint)
        # `foot` is the renderer's forefoot pivot and the lowest material-sole
        # vertices lie on its calibrated ground plane. Do not add a shoe-height
        # offset here: that creates a visible gap at the anchor and fails the
        # rendered full-sole contact check.
        plane_height = float(payload.get('renderFloorY') or 0.)
        existing_planes = [group for group in support['coplanarGroups']
                           if set(group['joints']) in ({foot}, {ankle, foot})
                           and np.allclose(group['normal'], [0., 1., 0.])]
        if existing_planes:
            # Confirmed ground contact belongs to today's floor and shoe geometry,
            # not a cached per-foot height from another placement or bake. The
            # forefoot is the observed sole anchor; ankle-to-toe pitch belongs
            # to the calibrated shoe geometry below, not a horizontal bone rule.
            for group in existing_planes:
                group['joints'] = [foot]
                group.pop('anchorJoint', None)
                group['planeOffsetMeters'] = plane_height
        else:
            support['coplanarGroups'].append({'joints': [foot], 'normal': [0, 1, 0],
                                             'planeOffsetMeters': plane_height})
        if not any(contact['joints'] == [knee, ankle, foot] for contact in support['soleContacts']):
            support['soleContacts'].append({'joints': [knee, ankle, foot], 'normal': [0, 1, 0]})
    canonical_planes = []
    seen_feet = set()
    for group in support['coplanarGroups']:
        joints = group.get('joints') or []
        side = (joints[0].removesuffix('_foot')
                if len(joints) == 1 and joints[0].endswith('_foot') else None)
        if (side in sides and np.allclose(group.get('normal'), [0., 1., 0.])):
            if side in seen_feet:
                continue
            seen_feet.add(side)
        canonical_planes.append(group)
    support['coplanarGroups'] = canonical_planes
    _remove_superseded_ground_sole_planes(support, sides)


def _confirmed_observed_ground_sole_sides(evidence, source_pose, joint_names):
    """Return foot sides backed by the same confirmed video and stable source tracks."""
    support = evidence.get('bodySupport') or {}
    observed = evidence.get('bodySupportObservation') or {}
    video_digest = observed.get('sourceVideoSha256')
    if (support.get('status') != 'confirmed'
            or not isinstance(video_digest, str) or not video_digest
            or support.get('sourceVideoSha256') != video_digest
            or validated_body_support_answer(observed) is None):
        return set()

    answer = validated_body_support_answer(observed)
    names = set(joint_names or [])
    mapping = evidence.get('motionSpaceMapping') or {}
    swapped = mapping.get('bilateralAssignment') == 'swapped'
    confirmed = set()
    for side in ('left', 'right'):
        if not {f'{side}_ankle', f'{side}_foot', f'{side}_knee'}.issubset(names):
            continue
        if (answer.get(f'{side}Foot') != 'stationary_full_sole'
                or answer.get(f'{side}FootSurface') != 'ground'):
            continue
        # Sparse visual review and unknown patch samples cannot establish a
        # whole-clip full-sole anchor; timed contacts remain available below.
        if not _has_uninterrupted_full_sole_patch(evidence, side):
            continue
        source_side = ('right' if side == 'left' else 'left') if swapped else side
        # An exact-video observation can confirm that a foot remains planted
        # while the source pose tracker briefly loses it at the clip start.
        # Keep the usual 70% sample, endpoint, and displacement checks; relax
        # only the leading-coverage guard for this hash- and patch-gated path.
        if stationary_source_track(
                source_pose, f'{source_side}_ankle', max_leading_gap_ratio=.30):
            confirmed.add(side)
    return confirmed


def _body_support_has_complete_ground_sole(support, side):
    ankle, foot, knee = (f'{side}_ankle', f'{side}_foot', f'{side}_knee')
    stationary = set(support.get('stationaryJoints') or [])
    has_plane = any(
        list(group.get('joints') or []) == [foot]
        and isinstance(group.get('planeOffsetMeters'), (int, float))
        and np.isfinite(group.get('planeOffsetMeters'))
        for group in support.get('coplanarGroups') or []
    )
    has_sole = any(
        {knee, ankle, foot}.issubset(set(contact.get('joints') or []))
        for contact in support.get('soleContacts') or []
    )
    return {ankle, foot}.issubset(stationary) and has_plane and has_sole


def _remove_superseded_ground_sole_planes(support, sides):
    """A calibrated full sole replaces earlier ground-point plane estimates."""
    complete = [side for side in sides if _body_support_has_complete_ground_sole(support, side)]
    groups = []
    for group in support.get('coplanarGroups', []):
        joints = list(group['joints'])
        for side in complete:
            sole = {f'{side}_ankle', f'{side}_foot'}
            if sole.issubset(group['joints']):
                joints = [name for name in joints if name not in sole]
        if len(joints) < (1 if 'planeOffsetMeters' in group else 2):
            continue
        updated = {**group, 'joints': joints}
        if 'anchorJoint' in updated and updated['anchorJoint'] not in joints:
            updated['anchorJoint'] = joints[0]
        groups.append(updated)
    support['coplanarGroups'] = groups


def _augment_confirmed_ground_sole_support(payload, evidence, source_pose, *, sides=None):
    support = evidence.get('bodySupport') or {}
    if (support.get('status') != 'confirmed'
            or payload.get('groundContactMode') in {'intermittent', 'none'}):
        return set()
    confirmed_sides = (_confirmed_observed_ground_sole_sides(
        evidence, source_pose, payload.get('jointNames'))
        if sides is None else set(sides))
    _remove_superseded_ground_sole_planes(support, confirmed_sides)
    frames = payload.get('frames') or []
    names = payload.get('jointNames') or []
    if not confirmed_sides or not frames or not set(names).issubset(
            set(frames[0].get('joints') or {})):
        return confirmed_sides
    medians = {
        name: np.median([frame['joints'][name] for frame in frames], axis=0)
        for name in names
    }
    add_ground_sole_contacts(payload, support, medians, sorted(confirmed_sides), evidence=evidence)
    return confirmed_sides


def observed_stationary_sole_contacts(evidence):
    from .contact_constraints import motion_support_contacts
    return [c for c in motion_support_contacts(evidence)
            if c.get('contactState') == 'full_sole' and c.get('contactMotion') == 'stationary'
            and c.get('verticalOnly') is not True]


def _has_uninterrupted_full_sole_patch(evidence, side):
    patch = evidence.get('footPatchEvidence') or {}
    states = ((patch.get('feet') or {}).get(side) or {}).get('states') or []
    contact_intervals = patch.get('contacts') or []
    return bool(patch.get('available') is True and states
                and all(str(state).casefold() == 'full_sole' for state in states)
                and any(contact.get('jointName') == f'{side}_foot'
                        and contact.get('contactState') == 'full_sole'
                        and contact.get('contactMotion') == 'stationary'
                        and contact.get('startRatio') == 0.
                        and contact.get('endRatio') == 1.
                        for contact in contact_intervals))


def corroborated_stationary_sole(evidence, side):
    """Require frame-complete full-sole patches before bridging ankle evidence."""
    if evidence.get('temporalResolutionSufficient') is not True:
        return False
    if not _has_uninterrupted_full_sole_patch(evidence, side):
        return False
    # These ratios describe the full source, so this evidence also covers any
    # selected subinterval. Partial ankle tracks cannot fill missing contacts.
    return any(c.get('jointName') == f'{side}_ankle'
               and c.get('contactMotion') == 'stationary'
               and c.get('startRatio') == 0. and c.get('endRatio') == 1.
               for c in evidence.get('footContactCandidates') or [])


def _has_full_cycle_stationary_sole(evidence, side, frame_count):
    if not _has_uninterrupted_full_sole_patch(evidence, side):
        return False
    if frame_count > 1:
        from .contact_constraints import contact_frame_bounds
        if any(
            ('startRatio' in contact or 'startFrame' in contact)
            and ('endRatio' in contact or 'endFrame' in contact)
            and contact_frame_bounds(contact, frame_count) == (0, frame_count - 1)
            for contact in observed_stationary_sole_contacts(evidence)
            if contact.get('jointName') == f'{side}_foot'
        ):
            return True
    return corroborated_stationary_sole(evidence, side)


def _remove_unverified_materialized_foot_support(evidence, corroborated_sides):
    support = evidence.get('bodySupport')
    if not isinstance(support, dict) or support.get('source') not in {
        'exact_source_contacts_and_stationary_pose_tracks',
        'observed_full_cycle_ground_sole_contacts',
    }:
        return

    removed_joints = {
        f'{side}_{joint}'
        for side in ('left', 'right') if side not in corroborated_sides
        for joint in ('ankle', 'foot')
    }
    _remove_materialized_support_joints(evidence, removed_joints)


def _remove_materialized_support_joints(evidence, removed_joints):
    from .contact_constraints import motion_support_contacts
    support = evidence.get('bodySupport') or {}
    digest = (evidence.get('bodySupportObservation') or {}).get('sourceVideoSha256')
    restrained = {row.get('jointName') for row in motion_support_contacts(evidence)
                  if row.get('supportKind') == 'observed_stationary_ankle_restraint'
                  and digest and row.get('sourceVideoSha256') == digest == support.get('sourceVideoSha256')}
    removed_joints = set(removed_joints) - restrained
    if not removed_joints.intersection(support.get('stationaryJoints') or []):
        return

    support['stationaryJoints'] = [
        joint for joint in support.get('stationaryJoints') or []
        if joint not in removed_joints
    ]
    groups = []
    for group in support.get('coplanarGroups') or []:
        joints = [joint for joint in group.get('joints') or [] if joint not in removed_joints]
        minimum_count = 1 if 'planeOffsetMeters' in group else 2
        if len(joints) < minimum_count:
            continue
        updated_group = {**group, 'joints': joints}
        if ('anchorJoint' in updated_group
                and updated_group['anchorJoint'] not in joints):
            updated_group['anchorJoint'] = joints[0]
        groups.append(updated_group)
    support['coplanarGroups'] = groups
    support['soleContacts'] = [
        contact for contact in support.get('soleContacts') or []
        if not removed_joints.intersection(contact.get('joints') or [])
    ]
    support['nonPenetrationChains'] = [
        chain for chain in support.get('nonPenetrationChains') or []
        if not removed_joints.intersection(
            [*(chain.get('joints') or []), *(chain.get('endpoints') or [])])
    ]

    if (not support['stationaryJoints'] and not support['coplanarGroups']
            and not support.get('nonPenetrationChains') and not support['soleContacts']):
        evidence.pop('bodySupport', None)


def calibrate_material_sole_floor(payload, *, ground_contact_up=None,
                                  ground_contact_points=None, contact_masks=None,
                                  surface_kind='ground'):
    """Re-estimate a floor for verified same-floor shoe contacts.

    An explicit finite floor keeps its existing authority. When no floor exists,
    verified ground-contact material tracks may supply a registered up axis and
    anchors; the resulting height is labelled an inferred scene gauge, never an
    observed metric floor. Missing or ambiguous inputs leave the payload as-is.
    """
    floor = payload.get('renderFloorY')
    if not (isinstance(floor, (int, float)) and np.isfinite(floor)):
        return _place_inferred_ground_contact_floor(
            payload, up=ground_contact_up, points=ground_contact_points,
            masks=contact_masks, surface_kind=surface_kind)
    if (payload.get('renderFloorSource') != 'motion_contact_authoritative'
            or payload.get('groundContactMode') != 'continuous'):
        return payload
    evidence = materialize_stationary_sole_support(payload)
    body = evidence.get('bodySupport') or {}
    answer = validated_body_support_answer(evidence.get('bodySupportObservation') or {})
    feet = {'left_foot', 'right_foot'}
    if (not answer or answer.get('pelvis') != 'stationary_support'
            or body.get('status') != 'confirmed'
            or not body.get('sourceVideoSha256')
            or body['sourceVideoSha256'] != evidence.get('sourceVideoSha256')
            or not {'pelvis', *feet}.issubset(body.get('stationaryJoints') or [])
            or {row['joints'][-1] for row in body.get('soleContacts', [])} != feet
            or any(answer.get(f'{side}FootSurface') != 'ground'
                   or answer.get(f'{side}Foot') != 'stationary_full_sole'
                   for side in ('left', 'right'))):
        return payload
    frames = [frame for frame in payload.get('frames', []) if not frame.get('syntheticLoopBridge')]
    try:
        samples = np.asarray([[frame['sourceJoints'][joint] for joint in sorted(feet)]
                              for frame in frames], dtype=float)
    except (KeyError, TypeError, ValueError):
        return payload
    if samples.shape != (len(frames), 2, 3) or not np.isfinite(samples).all():
        return payload
    material_floor = float(np.median(samples[:, :, 1]))
    result = deepcopy(payload)
    result['renderFloorY'] = material_floor
    result['renderFloorSource'] = 'verified_forefoot_pivots'
    # Preserve canonical labels; the calibrated height is the same for both sides.
    for group in (result.get('sourceFootSupportEvidence', {}).get('bodySupport') or {}).get('coplanarGroups', []):
        if set(group['joints']) in ({'left_foot'}, {'right_foot'}) and group.get('planeOffsetMeters') == floor:
            group['planeOffsetMeters'] = material_floor
    return result


def _place_inferred_ground_contact_floor(payload, *, up, points, masks, surface_kind):
    """Attach an inferred scene gauge without inventing observed floor facts."""
    if up is None or points is None:
        return payload
    from .ground_contact_plane import infer_ground_contact_plane
    plane = infer_ground_contact_plane(points, up=up, contact_masks=masks,
                                       surface_kind=surface_kind)
    if not plane.get('resolved'):
        return payload
    result = deepcopy(payload)
    result['renderFloorY'] = plane['offsetMeters']
    result['renderFloorSource'] = plane['provenance']
    result['renderFloorProvenance'] = {
        'authority': plane['authority'],
        'provenance': plane['provenance'],
        'observedFloorHeight': False,
        'surfaceKind': plane['surfaceKind'],
        'pointCount': plane['pointCount'],
        'normal': plane['normal'],
    }
    return result


def materialize_stationary_sole_support(payload):
    """Return rig-side evidence with eligible full-cycle sole support materialized."""
    from .contact_constraints import (
        contact_frame_bounds,
        motion_space_support_evidence,
    )
    evidence = deepcopy(motion_space_support_evidence(payload))
    _materialize_dense_sole_review_timeline(
        evidence, payload, evidence.get('stationarySoleIntervalReview') or {})
    materialize_timed_visual_contact_points(
        evidence, payload.get('frames'), payload.get('jointNames'),
        ground_contact_mode=payload.get('groundContactMode'))
    review = evidence.get('stationarySoleIntervalReview') or {}
    patch = evidence.get('footPatchEvidence') or {}
    frames_per_chunk = review.get('framesPerChunk')
    if (review.get('sourceVideoSha256')
            and review.get('sourceVideoSha256') == evidence.get('sourceVideoSha256') == patch.get('sourceVideoSha256')
            and review.get('sourceFrameCount', 0) > 0
            and review.get('sourceFrameCount') == patch.get('sourceFrameCount')
            and type(frames_per_chunk) is int and frames_per_chunk == _CONTACT_TIMELINE_FOOT_BATCH_SIZE):
        from .contact_constraints import _contiguous_runs
        for side, finding in (review.get('feet') or {}).items():
            review_has_forefoot = 'stationary_forefoot_ground' in finding.get('decisions', [])
            patch_side = ((patch.get('feet') or {}).get(side) or {})
            heel_unobserved = patch_side.get('pitchReferenceSource') == 'heel_unobserved'
            neutral_forefoot_only = False
            if not (review_has_forefoot or heel_unobserved):
                from .contact_constraints import _neutral_pitch_forefoot_patch_at_time
                times = patch.get('sourceTimesSec') or []
                states = patch_side.get('states') or []
                neutral_forefoot_only = (
                    len(times) == len(states)
                    and any(str(state).casefold() == 'toe_only'
                            and _neutral_pitch_forefoot_patch_at_time(evidence, side, times[index])
                            for index, state in enumerate(states))
                )
            # A full-sole review still establishes forefoot support when the
            # pose track cannot calibrate heel height. Preserve that support
            # without turning it into a full-sole constraint or heel plane.
            forefoot_only = review_has_forefoot or heel_unobserved or neutral_forefoot_only
            if (side not in {'left', 'right'} or finding.get('confirmed') is not True
                    or finding.get('reviewedFrameCount') != review['sourceFrameCount']
                    or not finding.get('decisions')
                    or len(finding['decisions']) != (review['sourceFrameCount'] + frames_per_chunk - 1) // frames_per_chunk
                    or any(value not in {'stationary_full_sole_ground', 'stationary_forefoot_ground'}
                           for value in finding['decisions'])
                    or _stance_has_conflicting_observations(evidence, side, allow_forefoot=forefoot_only)):
                continue
            for key in ('contacts', 'supportContacts'):
                evidence[key] = [contact for contact in evidence.get(key, [])
                                 if (contact.get('supportKind') == 'observed_stationary_ankle_restraint'
                                     or contact.get('jointName') not in {f'{side}_ankle', f'{side}_foot'})]
            contact = {'jointName': f'{side}_foot', 'contactState': 'toe_only' if forefoot_only else 'full_sole',
                       'contactMotion': 'stationary', 'surfaceKind': 'ground',
                       'verticalOnly': False,
                       'supportKind': 'observed_source_stance_interval',
                       'sourceVideoSha256': review['sourceVideoSha256'],
                       'sourceFrameCount': review['sourceFrameCount'],
                       'sourceFrameBounds': [0, review['sourceFrameCount'] - 1],
                       'startRatio': 0., 'endRatio': 1.,
                       'anchorGroupId': f'{side}:reviewed-stance:toe',
                       'ankleAnchorGroupId': f'{side}:reviewed-stance:ankle'}
            mapped = evidence.get('_fitFrameStateIndices')
            if isinstance(mapped, list):
                contact['_fitFrameRuns'] = _contiguous_runs([
                    0 <= index < review['sourceFrameCount'] for index in mapped])
                contact['_fitFrameCount'] = len(mapped)
            evidence.setdefault('contacts', []).append(contact)
            if review_has_forefoot and not heel_unobserved and not neutral_forefoot_only:
                for chunk, decision in enumerate(finding['decisions']):
                    if decision != 'stationary_full_sole_ground':
                        continue
                    first, last = chunk * frames_per_chunk, min((chunk + 1) * frames_per_chunk, review['sourceFrameCount']) - 1
                    flat_contact = {**contact, 'contactState': 'full_sole',
                                    'sourceFrameBounds': [first, last],
                                    'startRatio': first / max(1, review['sourceFrameCount'] - 1),
                                    'endRatio': last / max(1, review['sourceFrameCount'] - 1)}
                    if isinstance(mapped, list):
                        flat_contact['_fitFrameRuns'] = _contiguous_runs([
                            first <= index <= last for index in mapped])
                    evidence['contacts'].append(flat_contact)
            if forefoot_only:
                observed = evidence.get('bodySupportObservation') or {}
                if isinstance(observed.get('observation'), dict):
                    observed['observation'][f'{side}Foot'] = 'stationary_forefoot'
    remove_unobserved_torso_support(evidence)
    existing = evidence.get('bodySupport') or {}
    if existing.get('required') and existing.get('status') != 'confirmed':
        return evidence  # New foot evidence cannot resolve missing torso observations.
    count = len(payload.get('frames') or [])
    names = payload.get('jointNames') or []
    patch = evidence.get('footPatchEvidence') or {}
    source_pose_reference = payload.get('sourcePoseCameraReference') or {}
    source_pose = source_pose_reference.get('sourcePose') or {}
    source_confirmed_sides = set()
    if payload.get('groundContactMode') not in {'intermittent', 'none'}:
        source_confirmed_sides = _confirmed_observed_ground_sole_sides(
            evidence, source_pose, names)
    if patch.get('available') is True:
        corroborated_sides = {
            side for side in ('left', 'right')
            if _has_full_cycle_stationary_sole(evidence, side, count)
        }
        corroborated_sides.update(source_confirmed_sides)
        # Retained source evidence may carry bodySupport anchors materialized by
        # an older cache policy. Recheck them in the fit's motion-space view so
        # direct fitting and source digests cannot bypass the temporal patch
        # gate used by the normal source-preparation path.
        _remove_unverified_materialized_foot_support(evidence, corroborated_sides)
    existing = evidence.get('bodySupport') or {}
    _augment_confirmed_ground_sole_support(
        payload, evidence, source_pose, sides=source_confirmed_sides)
    existing = evidence.get('bodySupport') or {}
    observed = evidence.get('bodySupportObservation') or {}
    answer = validated_body_support_answer(observed)
    if answer is None:
        return evidence
    if count < 7 or not {'left_hip', 'right_hip', 'left_shoulder', 'right_shoulder'}.issubset(names):
        return evidence
    floor = payload.get('renderFloorY')
    if not isinstance(floor, (int, float)) or not np.isfinite(floor):
        return evidence
    sides = []
    existing_soles = {c['joints'][2] for c in existing.get('soleContacts', [])}
    for side in ('left', 'right'):
        if side in source_confirmed_sides:
            if not _body_support_has_complete_ground_sole(existing, side):
                sides.append(side)
            continue
        if f'{side}_foot' in existing_soles:
            continue
        if answer.get(f'{side}Foot') != 'stationary_full_sole' or answer.get(f'{side}FootSurface') != 'ground':
            continue
        contacts = [c for c in observed_stationary_sole_contacts(evidence)
                    if c.get('jointName') == f'{side}_foot']
        if any(('startRatio' in c or 'startFrame' in c) and ('endRatio' in c or 'endFrame' in c)
               and contact_frame_bounds(c, count) == (0, count-1)
               for c in contacts) or (contacts and corroborated_stationary_sole(evidence, side)):
            sides.append(side)
    if not sides:
        return evidence
    medians = {n: np.median([f['joints'][n] for f in payload['frames']], axis=0) for n in names}
    support = deepcopy(existing) if existing else {'required': True, 'status': 'confirmed',
               'source': 'observed_full_cycle_ground_sole_contacts',
               'sourceVideoSha256': observed.get('sourceVideoSha256'),
               'stationaryJoints': [], 'coplanarGroups': [], 'nonPenetrationChains': [], 'soleContacts': []}
    for field in ('stationaryJoints', 'coplanarGroups', 'nonPenetrationChains', 'soleContacts'):
        support.setdefault(field, [])
    affected = {f'{side}_{part}' for side in sides for part in ('ankle', 'foot')}
    groups = []
    for group in support['coplanarGroups']:
        joints = [name for name in group['joints'] if name not in affected]
        if joints:
            groups.append({**group, 'joints': joints})
    support['coplanarGroups'] = groups
    add_ground_sole_contacts(payload, support, medians, sides, evidence=evidence)
    if support['soleContacts']:
        evidence['bodySupport'] = support
    return evidence


def body_support_source_readiness(source_pose, contract=None, *, observed=None):
    """Expose the fitter's existing evidence prerequisites before reconstruction."""
    source_reference = source_pose if isinstance(source_pose, dict) else {}
    source_pose = (source_reference.get('pose') if isinstance(source_reference.get('pose'), dict)
                   else source_reference)
    anchors = body_support_required_anchors(contract, source_pose=source_reference, observed=observed)
    if not anchors:
        return {'required': True, 'ready': True, 'unresolvedAnchors': [],
                'reason': 'no_stationary_body_support_anchors_required',
                'requiredAnchors': []}
    unresolved = [name for name in anchors
                  if not stationary_source_track(source_pose, name)]
    return {'required': True, 'ready': not unresolved, 'unresolvedAnchors': unresolved,
            'requiredAnchors': list(anchors),
            'reason': 'stationary_support_anchors_observed' if not unresolved
                      else 'supported_body_stationarity_unresolved'}
