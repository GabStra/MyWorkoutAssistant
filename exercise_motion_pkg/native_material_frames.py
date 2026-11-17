"""Versioned immutable calibration for native full-FK material frames."""
import numpy as np
from scipy.spatial.transform import Rotation


def world_rotations(rig, coordinates):
    values = np.asarray(coordinates, dtype=float).reshape(-1, len(rig['coordinates'][0]))
    names = rig['jointNames']
    slots = {names.index(name): index for index, name in enumerate(rig['rotationJointNames'])}
    local = Rotation.from_rotvec(values[:, 3:].reshape(-1, 3)).as_matrix().reshape(len(values), -1, 3, 3)
    identity = np.broadcast_to(np.eye(3), (len(values), 3, 3))
    result = {}
    for joint in rig['order']:
        matrix = local[:, slots[joint]] if joint in slots else identity
        parent = rig['parents'][joint]
        result[joint] = matrix if parent < 0 else result[parent] @ matrix
    return result


def validate_material_frames(rig):
    if 'materialFrames' not in rig:
        return None
    binding = rig['materialFrames']
    if not isinstance(binding, dict) or type(binding.get('version')) is not int or binding.get('version') != 1:
        raise ValueError('unsupported native materialFrames version')
    current = np.asarray(rig['coordinates'], dtype=float)
    reference = np.asarray(binding.get('referenceCoordinates'), dtype=float)
    if reference.shape != current.shape or reference.ndim != 2 or not np.isfinite(reference).all():
        raise ValueError('materialFrames referenceCoordinates must match the complete rig clock')
    sides = binding.get('referenceBoneSides')
    if not isinstance(sides, dict) or not sides:
        raise ValueError('materialFrames referenceBoneSides missing')
    allowed = {f'{side}_ankle->{side}_foot' for side in ('left', 'right')}
    if set(sides) != allowed:
        raise ValueError('materialFrames requires both native foot reference sides')
    count = len(reference)
    rotations = world_rotations(rig, reference)
    for key, vectors in sides.items():
        ankle, foot = key.split('->')
        if ankle not in rig['jointNames'] or foot not in rig['jointNames']:
            raise ValueError('materialFrames foot chain missing')
        axis = np.asarray(vectors, dtype=float)
        if axis.shape != (count, 3) or not np.isfinite(axis).all():
            raise ValueError('materialFrames reference side shape invalid')
        joint = rig['jointNames'].index(foot)
        direction = np.einsum('fij,j->fi', rotations[joint], rig['offsets'][joint])
        direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-12)
        if np.any(np.linalg.norm(axis - direction * np.sum(axis*direction, axis=1, keepdims=True), axis=1) < 1e-8):
            raise ValueError('materialFrames reference side is degenerate')
    stationary = binding.get('stationaryLocalBindings', {})
    if not isinstance(stationary, dict) or not set(stationary) <= allowed:
        raise ValueError('materialFrames stationaryLocalBindings invalid')
    for key, episodes in stationary.items():
        if not isinstance(episodes, list):
            raise ValueError('materialFrames stationary bindings must be a list')
        occupied = set()
        for episode in episodes:
            if not isinstance(episode, dict):
                raise ValueError('materialFrames stationary binding must be an object')
            start, end = episode.get('startFrame'), episode.get('endFrame')
            frames = episode.get('activeFrames')
            axis = np.asarray(episode.get('localSideAxis'), dtype=float)
            if (type(start) is not int or type(end) is not int or not 0 <= start <= end < count
                    or not isinstance(frames, list) or len(frames) < 2
                    or any(type(i) is not int or not start <= i <= end for i in frames)
                    or frames != sorted(set(frames)) or occupied.intersection(frames)
                    or axis.shape != (3,) or not np.isfinite(axis).all() or np.linalg.norm(axis) < 1e-8):
                raise ValueError('materialFrames stationary local binding invalid')
            offset = np.asarray(rig['offsets'][rig['jointNames'].index(key.split('->')[1])])
            direction = offset / max(np.linalg.norm(offset), 1e-12)
            if np.linalg.norm(axis-direction*np.dot(axis,direction)) < 1e-8:
                raise ValueError('materialFrames stationary local side is degenerate')
            occupied.update(frames)
    return binding


def material_axes(rig, cursors, *, wrap=False, coordinates=None):
    """Full current foot rotation transports immutable reference material axes."""
    from .rig_playback import sample_rig_coordinates
    from .rig_interpolation import INTERPOLATION, LEGACY_INTERPOLATION, hermite_samples
    binding = validate_material_frames(rig)
    if binding is None:
        return None
    reference = np.asarray(binding['referenceCoordinates'], dtype=float)
    positions = np.asarray(cursors, dtype=float).reshape(-1)
    positions = np.mod(positions, len(reference)) if wrap else np.clip(positions, 0., len(reference)-1.)
    first = np.floor(positions).astype(int)
    last = (first+1) % len(reference) if wrap else np.minimum(first+1, len(reference)-1)
    alpha = positions-first
    current = sample_rig_coordinates(rig, positions, wrap=wrap) if coordinates is None else np.asarray(coordinates)
    if current.shape != (len(positions), reference.shape[1]):
        raise ValueError('materialFrames sampled coordinates do not match cursor count')
    ref = sample_rig_coordinates({**rig, 'coordinates': reference}, positions, wrap=wrap)
    current_world, reference_world = world_rotations(rig, current), world_rotations(rig, ref)
    result = {}
    for key, source in binding['referenceBoneSides'].items():
        side = key.split('_')[0]
        foot = rig['jointNames'].index(f'{side}_foot')
        source = np.asarray(source, dtype=float)
        sampled = (hermite_samples(source, first, last, alpha, wrap=wrap,
                    smooth_limiter=rig.get('interpolation') == INTERPOLATION)
                   if rig.get('interpolation') in (INTERPOLATION, LEGACY_INTERPOLATION)
                   else source[first]*(1.-alpha[:,None])+source[last]*alpha[:,None])
        local = np.einsum('fji,fj->fi', reference_world[foot], sampled)
        for episode in binding.get('stationaryLocalBindings', {}).get(key, []):
            active = np.zeros(len(reference), dtype=bool)
            active[episode['activeFrames']] = True
            eligible = ((positions >= episode['startFrame']) & (positions <= episode['endFrame'])
                        & active[first] & (active[last] | (alpha == 0.)))
            local[eligible] = episode['localSideAxis']
        axis = np.einsum('fij,fj->fi', current_world[foot], local)
        forward = np.einsum('fij,j->fi', current_world[foot], rig['offsets'][foot])
        forward /= np.maximum(np.linalg.norm(forward, axis=1, keepdims=True), 1e-12)
        axis -= forward*np.sum(axis*forward, axis=1, keepdims=True)
        length = np.linalg.norm(axis, axis=1, keepdims=True)
        if np.any(length < 1e-8):
            raise ValueError('materialFrames sampled side is degenerate')
        result[side] = axis/length
    return result


def freeze_material_frames(rig, tracks, source_axes):
    """Freeze existing native calibration once; never reselect using current q."""
    from .support_geometry import _native_side_axes_for_coordinates
    reference = np.asarray(rig.material_reference_coordinates, dtype=float)
    calibrated = _native_side_axes_for_coordinates(
        rig, reference, {'_nativeFootMaterialTracks': tracks}, publication=False) or {}
    rotations = rig.global_rotations(reference)
    binding = {'version': 1, 'referenceCoordinates': reference.tolist(),
               'referenceBoneSides': {}, 'stationaryLocalBindings': {}}
    for side in ('left', 'right'):
        key = f'{side}_ankle->{side}_foot'
        track = tracks.get(side) or {}
        binding['referenceBoneSides'][key] = np.asarray(track.get('sideAxes', source_axes[side]), dtype=float).tolist()
        active = np.asarray(track.get('active', np.zeros(len(reference))), dtype=bool)
        ids = np.asarray(track.get('anchorIds', [None]*len(reference)), dtype=object)
        occupied = set()
        for episode in track.get('episodes', []):
            if episode.get('mode') != 'stationary' or episode.get('regionRole') != 'full_sole':
                continue
            start, end = int(episode['startFrame']), int(episode['endFrame'])
            rows = np.flatnonzero(active & (np.arange(len(reference)) >= start) & (np.arange(len(reference)) <= end))
            anchor = episode.get('anchorId')
            if anchor is not None:
                rows = rows[ids[rows] == anchor]
            if len(rows) < 2 or occupied.intersection(rows.tolist()):
                continue
            foot = rig.names.index(f'{side}_foot')
            local = rotations[foot][rows[0]].T @ calibrated[side][rows[0]]
            binding['stationaryLocalBindings'].setdefault(key, []).append({
                'startFrame': start, 'endFrame': end, 'anchorId': anchor,
                'activeFrames': rows.tolist(), 'localSideAxis': local.tolist()})
            occupied.update(rows.tolist())
    return binding


def publish_material_frames(payload):
    """Write the physical native frame without point-only orientation overrides."""
    rig = payload['fixedRig']
    axes = material_axes(rig, np.arange(len(rig['coordinates'])))
    if axes is None:
        return
    for index, frame in enumerate(payload['frames']):
        for side, values in axes.items():
            key = f'{side}_ankle->{side}_foot'
            frame.setdefault('boneSides', {})[key] = values[index].tolist()
            forward = np.asarray(frame['joints'][f'{side}_foot']) - frame['joints'][f'{side}_ankle']
            forward /= np.linalg.norm(forward)
            frame.setdefault('shoeOrientation', {})[side] = {
                'forward': forward.tolist(), 'side': values[index].tolist()}


def place_material_frames(rig, rotation, origin):
    """Transform world reference gauge together with the current rig gauge."""
    from copy import deepcopy
    binding = validate_material_frames(rig)
    if binding is None:
        return
    binding = deepcopy(binding)
    values = np.asarray(binding['referenceCoordinates'], dtype=float)
    values[:, :3] = rotation.apply(values[:, :3]) - origin
    root = rig['jointNames'][rig['parents'].index(-1)]
    slot = 3 + 3*rig['rotationJointNames'].index(root)
    values[:, slot:slot+3] = (rotation*Rotation.from_rotvec(values[:, slot:slot+3])).as_rotvec()
    binding['referenceCoordinates'] = values.tolist()
    binding['referenceBoneSides'] = {key: rotation.apply(axis).tolist()
                                      for key, axis in binding['referenceBoneSides'].items()}
    rig['materialFrames'] = binding
