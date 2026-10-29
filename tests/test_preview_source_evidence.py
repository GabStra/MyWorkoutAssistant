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
  sourceVideoSha256: "a".repeat(64),
  contacts: [
    {{ jointName: "left_foot", startRatio: 0.1, endRatio: 0.2, continuousSupport: true }},
    {{ jointName: "left_foot", startRatio: 0.5, endRatio: 0.7 }},
    {{ jointName: "left_foot", startRatio: 0.8, endRatio: 0.9 }},
  ],
  footPatchEvidence: {{
    available: true,
    sourceVideoSha256: "a".repeat(64),
    sourceFps: 10,
    sourceTimesSec: Array.from({{ length: 11 }}, (_, index) => index / 10),
    contacts: [{{ jointName: "left_foot", startRatio: 0.1, endRatio: 0.7 }}],
    feet: {{ left: {{ states: ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"] }} }},
  }},
}};
const selectedFrameLineage = Array.from({{ length: 11 }}, (_, index) => ({{
  selectedFrameIndex: index,
  selectedFrameTimeSec: index / 10,
  parentSourceFrameIndex: 62 + index * 3,
  parentSourceTimeSec: (62 + index * 3) / 29.97,
}}));
let payload = {{
  frames: selectedFrameLineage.map((row) => ({{
    sourceFrameIndex: row.parentSourceFrameIndex,
    sourceTimeSec: row.parentSourceTimeSec,
  }})),
  bakedWearPayload: {{ sourcePoseCameraReference: {{ sourceTimelineMapping: {{
    schemaVersion: 1,
    verified: true,
    mappingKind: "selected_segment_to_parent_source",
    selectedStartSeconds: 2.0,
    selectedSegmentSha256: "a".repeat(64),
    parentSourceSha256: "b".repeat(64),
    selectedFrameClockReceiptSha256: "c".repeat(64),
    selectedOutputFps: 10,
    parentSourceFps: 29.97,
    selectedFrameCount: 11,
    selectedFrameLineage,
  }} }} }},
}};
let motionSpaceSupportEvidence = {{
  sourceVideoSha256: "b".repeat(64),
  supportContacts: [
    {{ jointName: "right_foot", startRatio: 0, endRatio: 1, continuousSupport: true }},
  ],
  footPatchEvidence: {{
    sourceVideoSha256: "b".repeat(64),
    sourceFps: 29.97,
    sourceTimesSec: selectedFrameLineage.map((row) => row.parentSourceTimeSec),
  }},
  motionSpaceMapping: {{ bilateralAssignment: "swapped", sourceEvidenceSha256: "source-digest" }},
}};
{helper}
const original = JSON.stringify(sourceFootSupportEvidence);
const mappedOriginal = JSON.stringify(motionSpaceSupportEvidence);
const active = rebaseSourceFootSupportEvidence(2, 6, 11);
assert.deepEqual(active.contacts, [
  {{ jointName: "left_foot", startRatio: 0, endRatio: 0, continuousSupport: false, startFrame: 0, endFrame: 0,
    sourceStartTimeSec: 62 / 29.97 + 0.1 * (30 / 29.97),
    sourceEndTimeSec: 62 / 29.97 + 0.2 * (30 / 29.97) }},
  {{ jointName: "left_foot", startRatio: 0.75, endRatio: 1, startFrame: 3, endFrame: 4,
    sourceStartTimeSec: 62 / 29.97 + 0.5 * (30 / 29.97),
    sourceEndTimeSec: 62 / 29.97 + 0.7 * (30 / 29.97) }},
]);
assert.deepEqual(active.footPatchEvidence.feet.left.states, ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]);
assert.equal(active.footPatchEvidence.contacts[0].startFrame, undefined);
assert.equal(active.footPatchEvidence.contacts[0].endFrame, undefined);
const activeMotion = activeSupportEvidenceForRange(2, 6, 11);
assert.equal(activeMotion.supportContacts[0].jointName, "right_foot");
assert.equal(activeMotion.supportContacts[0].startFrame, 0);
assert.equal(activeMotion.supportContacts[0].endFrame, 4);
const exportedSource = rebaseSourceFootSupportEvidence(2, 6, 11, sourceFootSupportEvidence);
assert.equal(exportedSource.contacts[0].jointName, "left_foot");
assert.equal(JSON.stringify(sourceFootSupportEvidence), original);
assert.equal(JSON.stringify(motionSpaceSupportEvidence), mappedOriginal);
const invalidMapping = JSON.parse(JSON.stringify(payload));
delete invalidMapping.bakedWearPayload.sourcePoseCameraReference.sourceTimelineMapping.selectedFrameLineage;
payload = invalidMapping;
const invalidExport = rebaseSourceFootSupportEvidence(2, 6, 11, sourceFootSupportEvidence);
assert.deepEqual(invalidExport.contacts, []);
assert.deepEqual(invalidExport.footPatchEvidence, sourceFootSupportEvidence.footPatchEvidence);
"""
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
