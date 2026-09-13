"""C1 fixed-rig interpolation, mirrored by browser and Android playback."""
import numpy as np

LEGACY_INTERPOLATION = 'limited_quaternion_hermite_v1'
INTERPOLATION = 'limited_quaternion_hermite_v2'


def frame_boundary_velocity_jump(sample, knots, fps):
    """Compare one-sided knot derivatives without counting smooth curvature."""
    epsilon = 1e-4
    offsets = np.array([-2., -1., 0., 1., 2.])*epsilon
    cursors = np.asarray(knots)[:, None]+offsets
    points = sample(cursors.ravel())
    points = points.reshape((len(knots), 5)+points.shape[1:])
    before_two, before, centers, after, after_two = np.moveaxis(points, 1, 0)
    incoming = 3.*centers-4.*before+before_two
    outgoing = -3.*centers+4.*after-after_two
    difference = (outgoing-incoming)*fps/(2.*epsilon)
    return float(np.max(np.linalg.norm(difference, axis=-1), initial=0.))


def limited_tangents(values, *, wrap, quaternion=False, smooth_limiter=True):
    previous, following = np.roll(values, 1, axis=0), np.roll(values, -1, axis=0)
    if not wrap:
        previous[0], following[-1] = values[0], values[-1]
    if quaternion:
        previous *= np.where(np.sum(previous*values, axis=-1, keepdims=True) < 0., -1., 1.)
        following *= np.where(np.sum(following*values, axis=-1, keepdims=True) < 0., -1., 1.)
    incoming, outgoing = values-previous, following-values
    if quaternion:
        incoming -= values*np.sum(incoming*values, axis=-1, keepdims=True)
        outgoing -= values*np.sum(outgoing*values, axis=-1, keepdims=True)
    tangent = (incoming+outgoing)*.5
    limit = 2.*np.minimum(np.linalg.norm(incoming, axis=-1, keepdims=True),
                         np.linalg.norm(outgoing, axis=-1, keepdims=True))
    tangent *= np.minimum(1., limit/np.maximum(np.linalg.norm(tangent, axis=-1, keepdims=True), 1e-12))
    alignment = np.sum(incoming*outgoing, axis=-1, keepdims=True)
    if smooth_limiter:
        # The old binary direction test jumped by a finite tangent at 90
        # degrees. Fade to zero continuously so fitting keyframes does not
        # introduce a discontinuous change in the between-frame path.
        alignment = np.maximum(alignment, 0.) / np.maximum(
            np.linalg.norm(incoming, axis=-1, keepdims=True)
            * np.linalg.norm(outgoing, axis=-1, keepdims=True), 1e-12)
        return tangent * np.minimum(alignment, 1.)
    return np.where(alignment > 0., tangent, 0.)


def hermite_samples(values, first, last, alpha, *, wrap, quaternion=False, smooth_limiter=True):
    tangents = limited_tangents(values, wrap=wrap, quaternion=quaternion, smooth_limiter=smooth_limiter)
    a, b, ma, mb = values[first], values[last], tangents[first], tangents[last]
    if quaternion:
        sign = np.where(np.sum(a*b, axis=-1, keepdims=True) < 0., -1., 1.)
        b, mb = b*sign, mb*sign
    t = alpha.reshape((-1,)+(1,)*(values.ndim-1))
    result = (2*t**3-3*t**2+1)*a + (t**3-2*t**2+t)*ma + (-2*t**3+3*t**2)*b + (t**3-t**2)*mb
    if quaternion:
        result /= np.maximum(np.linalg.norm(result, axis=-1, keepdims=True), 1e-12)
    return result
