import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from exercise_motion_pkg.render_geometry import upper_back_material_quads


def test_upper_back_region_matches_native_bent_rolled_surface_without_fixed_contact_point():
    fixture = json.loads((Path(__file__).parent/'fixtures/native_upper_back_region.json').read_text())
    points = np.asarray(fixture['points'])
    original = points.copy()
    axes = np.asarray(fixture['bodyAxes'])
    region = upper_back_material_quads(points, fixture['names'],
        binding=fixture['binding'], body_axes=axes)
    np.testing.assert_allclose(region, fixture['expectedQuads'], atol=3e-14, rtol=0.)
    # A roll changes the material witness, not the character's dimensions or
    # the selected scapular point. Every facet must remain available to contact.
    rotation = Rotation.from_euler('xyz', [23., -41., 17.], degrees=True).as_matrix()
    translation = np.asarray([.3, -.2, .5])
    rolled = upper_back_material_quads(points@rotation.T+translation, fixture['names'],
        binding=fixture['binding'], body_axes=axes@rotation.T)
    np.testing.assert_allclose(rolled, region@rotation.T+translation, atol=3e-14, rtol=0.)
    assert len(set(np.argmin(region[:,:,:,1].reshape(len(region), -1), axis=1))) > 1
    np.testing.assert_array_equal(points, original)
