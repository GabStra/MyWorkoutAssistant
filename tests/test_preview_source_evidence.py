from __future__ import annotations

import shutil
import subprocess

import pytest

from exercise_motion_pkg.preview import _build_html


@pytest.mark.skipif(shutil.which("node") is None, reason="Preview contact crop test executes the generated JavaScript helper")
def test_preview_crop_rebases_contacts_and_keeps_release_gaps():
    html = _build_html({"title": "contact evidence crop"})
    helper_start = html.index("function rebaseSourceFootSupportEvidence(")
    helper_end = html.index("\n\n    function applyActiveRange", helper_start)
    helper = html[helper_start:helper_end]
    script = f"""
const assert = require("node:assert/strict");
let sourceFootSupportEvidence = {{
  contacts: [
    {{ jointName: "left_foot", startRatio: 0.1, endRatio: 0.2, continuousSupport: true }},
    {{ jointName: "left_foot", startRatio: 0.5, endRatio: 0.7 }},
    {{ jointName: "left_foot", startRatio: 0.8, endRatio: 0.9 }},
  ],
  footPatchEvidence: {{
    available: true,
    contacts: [{{ jointName: "left_foot", startRatio: 0.1, endRatio: 0.7 }}],
    feet: {{ left: {{ states: ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"] }} }},
  }},
}};
let motionSpaceSupportEvidence = {{
  supportContacts: [
    {{ jointName: "right_foot", startRatio: 0, endRatio: 1, continuousSupport: true }},
  ],
  motionSpaceMapping: {{ bilateralAssignment: "swapped", sourceEvidenceSha256: "source-digest" }},
}};
{helper}
const original = JSON.stringify(sourceFootSupportEvidence);
const mappedOriginal = JSON.stringify(motionSpaceSupportEvidence);
const active = rebaseSourceFootSupportEvidence(2, 6, 11);
assert.deepEqual(active.contacts, [
  {{ jointName: "left_foot", startRatio: 0, endRatio: 0, continuousSupport: false, startFrame: 0, endFrame: 0 }},
  {{ jointName: "left_foot", startRatio: 0.75, endRatio: 1, startFrame: 3, endFrame: 4 }},
]);
assert.deepEqual(active.footPatchEvidence.feet.left.states, ["2", "3", "4", "5", "6"]);
assert.deepEqual(active.footPatchEvidence.contacts[0].startFrame, 0);
assert.deepEqual(active.footPatchEvidence.contacts[0].endFrame, 4);
const activeMotion = activeSupportEvidenceForRange(2, 6, 11);
assert.equal(activeMotion.supportContacts[0].jointName, "right_foot");
assert.equal(activeMotion.supportContacts[0].startFrame, 0);
assert.equal(activeMotion.supportContacts[0].endFrame, 4);
const exportedSource = rebaseSourceFootSupportEvidence(2, 6, 11, sourceFootSupportEvidence);
assert.equal(exportedSource.contacts[0].jointName, "left_foot");
assert.equal(JSON.stringify(sourceFootSupportEvidence), original);
assert.equal(JSON.stringify(motionSpaceSupportEvidence), mappedOriginal);
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
