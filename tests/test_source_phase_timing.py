import hashlib
import json

from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.source_evidence import (
    evidence_inventory,
    temporal_evidence_covers_candidate,
    temporal_observation_bins,
)


def _sheet(tmp_path, timestamps):
    sheet = tmp_path / "contact_sheet_01.jpg"
    sheet.write_bytes(b"candidate tiles")
    (tmp_path / "contact_sheet_evidence.json").write_text(json.dumps({"sheets": {
        sheet.name: {
            "sha256": hashlib.sha256(sheet.read_bytes()).hexdigest(),
            "frames": [
                {"number": index + 1, "timestampSeconds": timestamp}
                for index, timestamp in enumerate(timestamps)
            ],
        }
    }}))
    return sheet


def test_phase_timing_uses_hash_verified_sample_bins_and_requires_full_bin_coverage(tmp_path):
    sheet = _sheet(tmp_path, [0.0, 0.2, 0.4, 0.6])
    inventory = evidence_inventory({"A": [sheet]})
    timing = temporal_observation_bins(
        [
            {"phaseId": "lower", "visible": True, "evidenceFrameIds": ["A:1", "A:2"]},
            {"phaseId": "rise", "visible": True, "evidenceFrameIds": ["A:3", "A:4"]},
        ],
        ["lower", "rise"],
        inventory,
        id_field="phaseId",
        source_time_offset_seconds=2.0,
        require_visible=True,
    )

    assert timing["status"] == "sampled"
    assert timing["continuousCoverage"] == "unresolved"
    assert timing["sampleBinsById"]["lower"]["sampleBins"][0]["sourceBinEndSeconds"] == 2.1
    assert timing["sampleBinsById"]["rise"]["sampleBins"][0]["sourceBinStartSeconds"] == 2.3
    assert all(item["sheetSha256"] == inventory[0]["sheetSha256"]
               for row in timing["sampleBinsById"].values() for item in row["sampleBins"])
    assert temporal_evidence_covers_candidate(timing, start_seconds=2.0, end_seconds=2.6)["eligible"]
    assert not temporal_evidence_covers_candidate(timing, start_seconds=2.15, end_seconds=2.6)["eligible"]


def test_missing_legacy_phase_refs_and_wide_gaps_remain_unresolved():
    frames = [
        {"id": "A:1", "timestampSeconds": 0.0},
        {"id": "A:2", "timestampSeconds": 2.0},
    ]
    missing_refs = temporal_observation_bins(
        [{"phaseId": "p1", "visible": True, "evidenceFrameIds": []}],
        ["p1"],
        frames,
        id_field="phaseId",
        require_visible=True,
    )
    wide_gap = temporal_observation_bins(
        [{"phaseId": "p1", "visible": True, "evidenceFrameIds": ["A:1"]}],
        ["p1"],
        frames,
        id_field="phaseId",
        require_visible=True,
    )
    hidden = temporal_observation_bins(
        [{"phaseId": "p1", "visible": False, "evidenceFrameIds": ["A:1"]}],
        ["p1"],
        frames,
        id_field="phaseId",
        require_visible=True,
    )

    assert missing_refs["status"] == "unresolved"
    assert wide_gap["status"] == "unresolved"
    assert "sample_gap_too_large_for_timing" in wide_gap["errors"]
    assert hidden["status"] == "unresolved"


def test_equipment_timing_rows_can_overlap_in_time():
    frames = [
        {"id": "A:1", "timestampSeconds": 0.0},
        {"id": "A:2", "timestampSeconds": 0.2},
    ]
    timing = temporal_observation_bins(
        [
            {"requirementId": "equipment_1", "evidenceFrameIds": ["A:1"]},
            {"requirementId": "equipment_2", "evidenceFrameIds": ["A:1"]},
        ],
        ["equipment_1", "equipment_2"],
        frames,
        id_field="requirementId",
        ordered=False,
    )
    assert timing["status"] == "sampled"


def test_candidate_must_cover_every_cited_bin_and_duplicate_times_are_allowed():
    frames = [
        {"id": "uniform:1", "timestampSeconds": 0.0},
        {"id": "motion:1", "timestampSeconds": 0.0},
        {"id": "motion:2", "timestampSeconds": 0.2},
    ]
    timing = temporal_observation_bins(
        [{"phaseId": "p1", "visible": True,
          "evidenceFrameIds": ["uniform:1", "motion:1", "motion:2"]}],
        ["p1"],
        frames,
        id_field="phaseId",
        require_visible=True,
    )

    assert timing["status"] == "sampled"
    assert temporal_evidence_covers_candidate(
        timing, start_seconds=-0.1, end_seconds=0.1
    ) == {
        "eligible": False,
        "reason": "candidate_does_not_cover_evidence_bins",
        "missingIds": ["p1"],
    }
    assert temporal_evidence_covers_candidate(
        timing, start_seconds=-0.1, end_seconds=0.3
    )["eligible"]


def test_missing_timing_ids_keep_hard_gated_topology_unresolved():
    topology = {
        "completionMode": "distinct_end_state",
        "phaseEvidenceHardGate": True,
        "endpointEvidenceRequired": True,
        "boundaryStateHardGate": False,
        "startState": {"id": "start", "label": "start"},
        "endState": {"id": "end", "label": "end"},
        "phases": [{"id": "p1", "label": "phase"}],
    }
    evidence, reasons, _ = bake.topology_evidence_rejection_reasons(
        {
            "startStateMatch": "match",
            "endStateMatch": "match",
            "phaseEvidence": [{
                "phaseId": "p1", "visible": True, "position": 0.5,
                "evidence": "visible action phase",
            }],
        },
        topology,
        frame_inventory=[],
    )
    assert reasons == ["source_cut_contract_phase_timing_unresolved"]
    assert evidence["actionPhaseEvidenceComplete"] is True
    assert evidence["phaseTimingEvidence"]["status"] == "unresolved"


def test_single_whole_action_evidence_cannot_approve_a_four_phase_transition():
    topology = {
        "completionMode": "distinct_end_state",
        "phaseEvidenceHardGate": True,
        "endpointEvidenceRequired": True,
        "boundaryStateHardGate": False,
        "startState": {"id": "start", "label": "plank"},
        "endState": {"id": "end", "label": "overhead press"},
        "phases": [
            {"id": "phase_01", "label": "push-up"},
            {"id": "phase_02", "label": "row on each side"},
            {"id": "phase_03", "label": "squat clean"},
            {"id": "phase_04", "label": "overhead press"},
        ],
    }
    evidence, reasons, _ = bake.topology_evidence_rejection_reasons(
        {
            "startStateMatch": "match",
            "endStateMatch": "match",
            "phaseEvidence": [{
                "phaseId": "phase_01", "visible": True, "position": 0.5,
                "evidence": "One broad sentence claims the whole sequence is visible.",
                "evidenceFrameIds": [],
            }],
        },
        topology,
        frame_inventory=[],
    )

    assert evidence["observedPhaseIds"] == ["phase_01"]
    assert evidence["phaseTimingEvidence"]["status"] == "unresolved"
    assert "source_cut_contract_phase_sequence_mismatch" in reasons
    assert "source_cut_contract_phase_timing_unresolved" in reasons


def test_ordered_phases_can_share_a_transition_frame_but_need_distinct_timed_evidence():
    frames = [
        {"id": f"A:{index + 1}", "timestampSeconds": index * 0.2}
        for index in range(4)
    ]
    shared_boundary = temporal_observation_bins(
        [
            {"phaseId": "p1", "visible": True, "evidenceFrameIds": ["A:1", "A:2"]},
            {"phaseId": "p2", "visible": True, "evidenceFrameIds": ["A:2", "A:3"]},
        ],
        ["p1", "p2"], frames, id_field="phaseId", require_visible=True,
    )
    same_evidence = temporal_observation_bins(
        [
            {"phaseId": "p1", "visible": True, "evidenceFrameIds": ["A:2"]},
            {"phaseId": "p2", "visible": True, "evidenceFrameIds": ["A:2"]},
        ],
        ["p1", "p2"], frames, id_field="phaseId", require_visible=True,
    )

    assert shared_boundary["status"] == "sampled"
    assert same_evidence["status"] == "unresolved"
    assert "observation_order_not_established" in same_evidence["errors"]


def test_scorecard_persists_exact_phase_and_equipment_bins_without_changing_approval(tmp_path):
    sheet = _sheet(tmp_path, [0.0, 0.2, 0.4, 0.6])
    candidate = bake.SourceCutCandidate(
        "A", bake.DetectionWindow(0, 0.0, 0.6), [sheet]
    )
    contract = {
        "completionMode": "distinct_end_state",
        "actionDefinitionAuthority": "structured_definition",
        "actionDefinitionStatus": "defined",
        "definingAction": "Raise the loaded bar through the prescribed action.",
        "movementTopology": {
            "completionMode": "distinct_end_state",
            "startState": {"id": "start", "label": "start"},
            "phases": [{"id": "phase_01", "label": "raise"}],
            "endState": {"id": "end", "label": "finish"},
            "endpointEvidenceRequired": True,
        },
    }
    scorecard = {
        "id": "A", "approved": True, "confidence": 0.95, "completeMovement": True,
        "startBoundaryClean": True, "finishBoundaryClean": True, "setupOrFiller": False,
        "namedEquipmentEngagedStatus": "engaged", "reject": [], "note": "clear complete action",
        "identityMatch": "match", "identityEvidence": "the requested loaded bar action is visible",
        "boundaryEvidence": "", "qualityEvidence": "clear real footage",
        "startStateMatch": "match", "endStateMatch": "match",
        "phaseEvidence": [{
            "phaseId": "phase_01", "visible": True, "position": 0.5,
            "evidence": "bar is raised", "evidenceFrameIds": ["A:3"],
        }],
        "equipmentEvidence": [
            {"requirementId": "equipment_1", "evidenceFrameIds": ["A:2"]},
            {"requirementId": "equipment_2", "evidenceFrameIds": ["A:2"]},
        ],
    }
    ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [scorecard]}), [candidate],
        exercise_motion_contract=contract, required_equipment="barbell",
        require_identity_evidence=True,
        equipment_timing_requirement_ids=["equipment_1", "equipment_2"],
        source_time_offset_seconds=5.0,
    )

    assert bake.source_cut_ranking_has_vlm_approval(ranking)
    row = ranking.payload["selectedScorecard"]
    phase = row["movementTopologyEvidence"]["phaseTimingEvidence"]
    assert phase["status"] == "sampled"
    assert phase["sampleBinsById"]["phase_01"]["sampleBins"][0]["sourceTimestampSeconds"] == 5.4
    assert phase["sampleBinsById"]["phase_01"]["sampleBins"][0]["sheetSha256"]
    equipment = row["equipmentTimingEvidence"]
    assert equipment["status"] == "sampled"
    assert equipment["sampleBinsById"]["equipment_1"]["sampleBins"][0]["sourceTimestampSeconds"] == 5.2

    scorecard["phaseEvidence"][0].pop("evidenceFrameIds")
    legacy_ranking = bake.parse_source_cut_candidate_choice(
        json.dumps({"candidates": [scorecard]}), [candidate],
        exercise_motion_contract=contract, required_equipment="barbell",
        require_identity_evidence=True,
        equipment_timing_requirement_ids=["equipment_1", "equipment_2"],
        source_time_offset_seconds=5.0,
    )
    assert not bake.source_cut_ranking_has_vlm_approval(legacy_ranking)
    rejected_row = legacy_ranking.payload["sourceCutScorecardCandidates"][0]
    assert "source_cut_contract_phase_timing_unresolved" in rejected_row["rejectionReasons"]
    assert rejected_row["movementTopologyEvidence"][
        "phaseTimingEvidence"]["status"] == "unresolved"


def test_prompt_supplies_only_manifest_ids_not_inferred_timestamps(tmp_path):
    sheet = _sheet(tmp_path, [1.0, 1.2])
    candidate = bake.SourceCutCandidate(
        "B", bake.DetectionWindow(0, 1.0, 1.2), [sheet]
    )
    prompt = bake.build_source_cut_candidate_choice_prompt(
        exercise_name="Loaded Bar Exercise",
        candidate_title="candidate B",
        candidate=candidate,
        exercise_motion_contract={
            "completionMode": "distinct_end_state",
            "definingAction": "Move the loaded bar through the prescribed action.",
            "requiredPhases": ["raise the bar"],
            "actionDefinitionAuthority": "structured_definition",
            "actionDefinitionStatus": "defined",
            "requiredAccessories": [],
        },
    )
    assert '"id":"B:1"' in prompt
    assert '"id":"B:2"' in prompt
    assert "do not return or infer timestamps" in prompt
    assert '"evidenceFrameIds":["candidateId:tileNumber"]' in prompt
    assert '"timestampSeconds"' not in prompt
