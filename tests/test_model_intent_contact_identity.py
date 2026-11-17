import numpy as np
import pytest
from exercise_motion_pkg.contact_constraints import interpolated_contact_mask
from exercise_motion_pkg.sequence_stabilization import model_intent_contact_mask


def test_model_stance_survives_source_identity_change_without_reviving_other_contacts():
    names = ["left_foot", "right_foot", "left_ankle"]
    payload = {"groundContactMode": "continuous", "canonicalExecution": {"stance": "stationary_bilateral"}}
    model = model_intent_contact_mask(payload, names, 2, support_evidence={})
    pinned = np.ones((2, 3), dtype=bool)
    identities = np.array([["toe:0", "toe:1", "ankle:0"], [None, "toe:1", "ankle:1"]], dtype=object)
    assert interpolated_contact_mask(pinned, 0, 1, identities).tolist() == [False, True, False]
    assert interpolated_contact_mask(pinned, 0, 1, identities, model_pinned=model).tolist() == [True, True, False]
    assert identities[1, 0] is None


@pytest.mark.parametrize("payload,evidence", [
    ({"groundContactMode": "continuous"}, {}),
    ({"groundContactMode": "intermittent", "canonicalExecution": {"stance": "stationary_bilateral"}}, {}),
    ({"groundContactMode": "continuous", "canonicalExecution": {"stance": "stationary_bilateral"}},
     {"footPatchEvidence": {"feet": {"left": {"states": ["airborne", "unknown"]}}}}),
])
def test_absent_or_contradicted_stance_gains_no_model_pins(payload, evidence):
    assert not model_intent_contact_mask(payload, ["left_foot", "right_foot"], 2, support_evidence=evidence).any()
