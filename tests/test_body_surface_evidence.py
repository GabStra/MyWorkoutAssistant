from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from nonfoot_support_fixture import build_nonfoot_support_fixture, FPS

from exercise_motion_pkg.bake_and_rank import load_verified_source_pose_reference
from exercise_motion_pkg import bake_and_rank as bake
from exercise_motion_pkg.body_surface_evidence import (
    adjudicate_root_visual_interface_visibility,
    review_body_surface_contact_samples, verify_body_surface_contact_evidence,
)
from exercise_motion_pkg import body_surface_evidence as surface_evidence
from exercise_motion_pkg.body_support_observation import POLICY_VERSION
from exercise_motion_pkg.pose_fidelity import _canonical_source_pose_sha256
from exercise_motion_pkg.source_frame_clock import (
    build_source_frame_clock, source_frame_clock_path_for_video, write_source_frame_clock,
)


def _case(tmp_path, *, name="shoulder", side="left", sample_frames=(0, 6), surface="bench-top"):
    video, _reference_path, pose_reference, _payload = build_nonfoot_support_fixture(
        tmp_path, sides=(side,), frame_count=12)
    clock = build_source_frame_clock(
        source_video_path=video, output_video_path=video,
        crop_start_seconds=0.0, output_fps=FPS)
    clock_path = write_source_frame_clock(
        clock, output_path=source_frame_clock_path_for_video(video))
    video_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    clock_sha = hashlib.sha256(clock_path.read_bytes()).hexdigest()
    record = {
        "schemaVersion": 1,
        "contactId": f"{name}-{side}-bench-contact",
        "bodyRegion": {"name": name, "side": side},
        "contactMode": "sliding" if name == "shin" else "stationary",
        "sourceEvidence": {
            "sourceVideoSha256": video_sha,
            "sourcePosePayloadSha256": _canonical_source_pose_sha256(pose_reference),
            "sourceFrameClockReceiptSha256": clock_sha,
            "observations": [{
                "sampleId": f"{name}-{index}",
                "sourceTimeSec": index / FPS,
                "sourcePoseFrameIndex": index,
                "sourceFrameIndex": index,
                "sourceFps": FPS,
                "contactState": "direct_contact",
                "visible": True,
                "surfaceId": surface,
            } for index in sample_frames],
        },
        "patchBinding": None,
        "surfaceEstimate": None,
        "geometryProvenance": None,
    }
    return video, pose_reference, record


def _run_review(tmp_path, video, pose, record, choices=("direct_contact", "direct_contact")):
    remaining = iter(choices)

    def caption_images(*, frame_paths, prompt, response_schema, **_kwargs):
        assert len(frame_paths) == 1 and frame_paths[0].suffix == ".png"
        assert "full source-frame" in prompt and "named candidate surface" in prompt
        return json.dumps({alias: next(remaining) for alias in response_schema["properties"]})

    return review_body_surface_contact_samples(
        record, video, pose, caption_images=caption_images,
        receipt_directory=tmp_path / "receipts",
        review_identity={"model": "fixture", "policyVersion": 1})


@pytest.mark.parametrize(("name", "side"), [("shoulder", "left"), ("shin", "right")])
def test_verifies_generic_region_samples_without_promoting_sparse_points(tmp_path, name, side):
    video, pose, record = _case(tmp_path, name=name, side=side)
    reviewed = _run_review(tmp_path, video, pose, record)
    result = verify_body_surface_contact_evidence(
        reviewed["record"], video, pose, review_receipt_path=reviewed["receiptPath"],
        review_receipt_sha256=reviewed["receiptSha256"])
    assert result["status"] == "verified_samples"
    assert [sample["bodyRegion"] for sample in result["samples"]] == [
        {"name": name, "side": side}, {"name": name, "side": side}]
    assert result["coverage"]["observedPoseFrameCount"] == 2
    assert result["coverage"]["unobservedPoseFrameCount"] == 10
    assert result["coverage"]["allCanonicalPoseFramesObserved"] is False
    assert result["coverage"]["intervalContactInferred"] is False
    assert result["coverage"]["xyzPinsCreated"] is False
    assert result["sourceApproval"] is False


def test_nested_materialized_video_uses_explicit_pose_receipt_and_rejects_wrong_sha(tmp_path):
    video, pose, record = _case(tmp_path, name="upper_back", side="center")
    workspace = video.parent.parent
    receipt = workspace / "segment_detection" / "exact_source_pose_reference.json"
    nested_video = (
        workspace / "segment_detection" / "pre_reconstruction_source_candidates"
        / "deterministic_confirmation" / "source_candidate_J-TRIM-1" / "selected_segment.mp4"
    )


def _atlas_refs_for_review(video, receipt_path, output_dir):
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    samples = receipt["requestBinding"]["samples"]
    output_dir.mkdir(parents=True, exist_ok=True)
    refs = []
    with tempfile.TemporaryDirectory(prefix="test-body-surface-atlas-") as temp_dir:
        temp_root = Path(temp_dir)
        for batch_index, start in enumerate(range(0, len(samples), 4)):
            batch = samples[start:start + 4]
            paths = []
            mapped = []
            for panel_index, bound in enumerate(batch):
                frame_path = temp_root / f"frame-{batch_index}-{panel_index}.png"
                assert surface_evidence._source_frame_png(
                    Path(video), bound["sourceFrameIndex"], frame_path) == bound["imageSha256"]
                paths.append(frame_path)
                mapped.append({
                    "alias": chr(ord("A") + panel_index),
                    "sampleId": bound["sampleId"],
                    "sourcePoseFrameIndex": bound["sourcePoseFrameIndex"],
                    "sourceFrameIndex": bound["sourceFrameIndex"],
                    "sourceTimeSec": bound["sourceTimeSec"],
                })
            atlas_path = output_dir / f"atlas-{batch_index:03d}.png"
            atlas_sha = surface_evidence._contact_batch_atlas(paths, atlas_path)
            refs.append({"batchIndex": batch_index, "path": str(atlas_path),
                         "sha256": atlas_sha, "samples": mapped})
    return refs
    nested_video.parent.mkdir(parents=True)
    shutil.copyfile(video, nested_video)
    clock_path = write_source_frame_clock(
        build_source_frame_clock(
            source_video_path=nested_video, output_video_path=nested_video,
            crop_start_seconds=0.0, output_fps=FPS,
        ),
        output_path=source_frame_clock_path_for_video(nested_video),
    )
    record["sourceEvidence"]["sourceFrameClockReceiptSha256"] = hashlib.sha256(
        clock_path.read_bytes()).hexdigest()
    receipt_sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
    legacy_guessed_path = nested_video.parent.parent / "segment_detection" / "exact_source_pose_reference.json"
    assert not legacy_guessed_path.exists()

    choices = iter(("direct_contact", "direct_contact"))
    def nested_callback(*, response_schema, **_kwargs):
        return json.dumps({alias: next(choices) for alias in response_schema["properties"]})

    reviewed = review_body_surface_contact_samples(
        record, nested_video, pose,
        caption_images=nested_callback,
        receipt_directory=tmp_path / "nested-receipts",
        review_identity={"model": "fixture", "policyVersion": 1},
        source_pose_reference_path=receipt,
        source_pose_reference_sha256=receipt_sha,
    )
    verified = verify_body_surface_contact_evidence(
        reviewed["record"], nested_video, pose,
        review_receipt_path=reviewed["receiptPath"],
        review_receipt_sha256=reviewed["receiptSha256"],
        source_pose_reference_path=receipt,
        source_pose_reference_sha256=receipt_sha,
    )
    assert verified["status"] == "verified_samples"

    callback_called = False

    def forbidden_callback(**_kwargs):
        nonlocal callback_called
        callback_called = True
        raise AssertionError("wrong receipt digest must fail before visual callback")

    with pytest.raises(ValueError, match="explicit canonical source pose receipt SHA256 mismatch"):
        review_body_surface_contact_samples(
            record, nested_video, pose, caption_images=forbidden_callback,
            receipt_directory=tmp_path / "wrong-sha-receipts",
            review_identity={"model": "fixture", "policyVersion": 1},
            source_pose_reference_path=receipt,
            source_pose_reference_sha256="0" * 64,
        )
    assert callback_called is False


def test_required_legacy_head_uses_verified_full_frame_regional_evidence(tmp_path):
    video, pose, record = _case(
        tmp_path, name="head", side="left", sample_frames=tuple(range(12)), surface="bench-top",
    )
    reviewed = _run_review(tmp_path, video, pose, record, choices=("direct_contact",) * 12)
    video_sha = record["sourceEvidence"]["sourceVideoSha256"]
    evidence = {
        "sourceVideoSha256": video_sha,
        "bodySupportObservation": {
            "status": "observed",
            "source": "exact_source_visual_support_observation",
            "sourceVideoSha256": video_sha,
            "policyVersion": POLICY_VERSION,
            "sourceClock": "video_frame_zero_seconds",
            "observation": {"head": "unknown"},
        },
        "bodySurfaceContactEvidence": {
            "sourceVideoSha256": video_sha,
            "reviews": [{
                "requirement": {
                    "disposition": "required", "region": "head",
                    "declaredSide": "left", "side": "left",
                    "surface": "bench-top", "contactMode": "stationary",
                },
                "record": reviewed["record"],
                "receiptPath": reviewed["receiptPath"],
                "receiptSha256": reviewed["receiptSha256"],
            }],
        },
    }
    contract = {"bodySupportRequirements": {"required": [
        {"region": "head", "side": "left", "surface": "bench-top"},
    ]}}

    assert bake.body_support_contract_evidence_status(
        contract, evidence, source_pose=pose, selected_video_path=video,
    )["status"] == "passed"


@pytest.mark.parametrize("failure", ["video_hash", "pose_hash", "clock_hash", "clock", "pose_gap"])
def test_rejects_stale_or_misaligned_contact_receipts(tmp_path, failure):
    video, pose, record = _case(tmp_path)
    candidate = copy.deepcopy(record)
    reviewed = _run_review(tmp_path, video, pose, candidate)
    if failure == "video_hash":
        candidate["sourceEvidence"]["sourceVideoSha256"] = "0" * 64
    elif failure == "pose_hash":
        candidate["sourceEvidence"]["sourcePosePayloadSha256"] = "0" * 64
    elif failure == "clock_hash":
        candidate["sourceEvidence"]["sourceFrameClockReceiptSha256"] = "0" * 64
    elif failure == "clock":
        candidate["sourceEvidence"]["observations"][0]["sourceFrameIndex"] += 1
    else:
        candidate["sourceEvidence"]["observations"][0]["sourcePoseFrameIndex"] = 99
    with pytest.raises(ValueError):
        verify_body_surface_contact_evidence(
            candidate, video, pose, review_receipt_path=reviewed["receiptPath"],
            review_receipt_sha256=reviewed["receiptSha256"])


def test_rejects_mutated_source_pose_reference_even_when_video_hash_matches(tmp_path):
    video, pose, record = _case(tmp_path)
    mutated = copy.deepcopy(pose)
    mutated["frames"][0]["sourceTimeSec"] += 0.01
    with pytest.raises(ValueError):
        verify_body_surface_contact_evidence(record, video, mutated)


@pytest.mark.parametrize("mutation", ["region", "side", "mode", "surface", "contact", "pixels"])
def test_review_receipt_rejects_changed_contact_question_or_reply(tmp_path, mutation):
    video, pose, record = _case(tmp_path)
    reviewed = _run_review(tmp_path, video, pose, record)
    candidate = copy.deepcopy(record)
    receipt_path = Path(reviewed["receiptPath"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "region":
        candidate["bodyRegion"]["name"] = "elbow"
    elif mutation == "side":
        candidate["bodyRegion"]["side"] = "right"
    elif mutation == "mode":
        candidate["contactMode"] = "sliding"
    elif mutation == "surface":
        candidate["sourceEvidence"]["observations"][0]["surfaceId"] = "floor"
    elif mutation == "contact":
        candidate["sourceEvidence"]["observations"][0]["contactState"] = "no_contact"
    else:
        receipt["requestBinding"]["samples"][0]["imageSha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        reviewed["receiptSha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        verify_body_surface_contact_evidence(
            candidate if mutation != "pixels" else reviewed["record"], video, pose,
            review_receipt_path=receipt_path, review_receipt_sha256=reviewed["receiptSha256"])


def test_review_producer_derives_contact_and_visibility_only_from_enum_choice(tmp_path):
    video, pose, record = _case(tmp_path)
    result = _run_review(tmp_path, video, pose, record, choices=("no_contact", "unresolved"))
    rows = result["record"]["sourceEvidence"]["observations"]
    assert [(row["contactState"], row["visible"]) for row in rows] == [
        ("no_contact", True), ("unknown", False)]
    receipt = json.loads(Path(result["receiptPath"]).read_text(encoding="utf-8"))
    assert set(json.loads(receipt["rawResponses"][rows[0]["sampleId"]])) == {"choice"}
    assert "visible" not in receipt["requestBinding"]["samples"][0]
    assert receipt["requestBinding"]["samples"][0]["imageSha256"]


def test_root_visual_adjudication_is_separate_bound_and_stays_unresolved(tmp_path):
    video, pose, record = _case(
        tmp_path, name="upper_back", side="center", sample_frames=tuple(range(12)),
        surface="bench",
    )
    reviewed = _run_review(
        tmp_path, video, pose, record,
        choices=("direct_contact",) * 4 + ("no_contact",) * 4 + ("unresolved",) * 4,
    )
    original_receipt_bytes = Path(reviewed["receiptPath"]).read_bytes()
    atlas_refs = _atlas_refs_for_review(
        video, reviewed["receiptPath"], tmp_path / "root-reviewed-atlases")
    adjudicated = adjudicate_root_visual_interface_visibility(
        reviewed["record"], video, pose,
        review_receipt_path=reviewed["receiptPath"],
        review_receipt_sha256=reviewed["receiptSha256"],
        source_pose_reference_path=None, source_pose_reference_sha256=None,
        atlas_refs=atlas_refs,
        sample_ids=[row["sampleId"] for row in reviewed["record"]["sourceEvidence"]["observations"]],
        interface_visibility="occluded_or_ambiguous",
        receipt_directory=tmp_path / "root-review-receipts",
    )
    assert Path(reviewed["receiptPath"]).read_bytes() == original_receipt_bytes
    assert [(row["contactState"], row["visible"])
            for row in adjudicated["record"]["sourceEvidence"]["observations"]] == [
        ("direct_contact", True)] * 4 + [("no_contact", True)] * 4 + [("unknown", False)] * 4
    assert adjudicated["record"]["visibilityAdjudication"]["receiptSha256"] == adjudicated["receiptSha256"]

    verified = verify_body_surface_contact_evidence(
        adjudicated["record"], video, pose,
        review_receipt_path=reviewed["receiptPath"],
        review_receipt_sha256=reviewed["receiptSha256"],
    )
    assert [row["contactState"] for row in verified["samples"]] == ["unknown"] * 12
    assert [row["rawContactState"] for row in verified["samples"]] == [
        "direct_contact"] * 4 + ["no_contact"] * 4 + ["unknown"] * 4
    assert all(row["effectiveVisibility"] == "occluded_or_ambiguous"
               for row in verified["samples"])
    assert verified["sourceApproval"] is False
    assert verified["visibilityAdjudication"]["authority"] == "ROOT_VISUAL_REVIEW"

    evidence = {
        "sourceVideoSha256": record["sourceEvidence"]["sourceVideoSha256"],
        "bodySupportObservation": {
            "status": "observed", "source": "exact_source_visual_support_observation",
            "sourceVideoSha256": record["sourceEvidence"]["sourceVideoSha256"],
            "policyVersion": POLICY_VERSION, "sourceClock": "video_frame_zero_seconds",
            "observation": {"upperBack": "unknown"},
        },
        "bodySurfaceContactEvidence": {
            "sourceVideoSha256": record["sourceEvidence"]["sourceVideoSha256"],
            "reviews": [{
                "contactId": adjudicated["record"]["contactId"],
                "requirement": {
                    "disposition": "required", "region": "upper_back",
                    "declaredSide": "center", "side": "center",
                    "surface": "bench", "contactMode": "stationary",
                },
                "record": adjudicated["record"],
                "receiptPath": reviewed["receiptPath"],
                "receiptSha256": reviewed["receiptSha256"],
            }],
        },
    }
    contract = {"bodySupportRequirements": {"required": [
        {"region": "upper_back", "side": "center", "surface": "bench"},
    ]}}
    status = bake.body_support_contract_evidence_status(
        contract, evidence, source_pose=pose, selected_video_path=video)
    assert status["status"] != "passed"
    assert "required_upper_back_center_support_unobserved" in status["failures"]

    with pytest.raises(ValueError, match="already has a visibility adjudication"):
        adjudicate_root_visual_interface_visibility(
            adjudicated["record"], video, pose,
            review_receipt_path=reviewed["receiptPath"],
            review_receipt_sha256=reviewed["receiptSha256"],
            source_pose_reference_path=None, source_pose_reference_sha256=None,
            atlas_refs=atlas_refs,
            sample_ids=[row["sampleId"] for row in reviewed["record"]["sourceEvidence"]["observations"]],
            interface_visibility="occluded_or_ambiguous",
            receipt_directory=tmp_path / "root-review-receipts",
        )


def test_root_visual_adjudication_rejects_mismatched_atlas_and_sample_set(tmp_path):
    video, pose, record = _case(
        tmp_path, name="upper_back", side="center", sample_frames=tuple(range(8)),
        surface="bench",
    )
    reviewed = _run_review(tmp_path, video, pose, record, choices=("no_contact",) * 8)
    atlas_refs = _atlas_refs_for_review(
        video, reviewed["receiptPath"], tmp_path / "atlas-binding")
    kwargs = {
        "record": reviewed["record"], "selected_video": video,
        "source_pose_reference": pose,
        "review_receipt_path": reviewed["receiptPath"],
        "review_receipt_sha256": reviewed["receiptSha256"],
        "source_pose_reference_path": None, "source_pose_reference_sha256": None,
        "interface_visibility": "occluded_or_ambiguous",
        "receipt_directory": tmp_path / "adjudication-binding",
    }
    with pytest.raises(ValueError, match="atlas mapping differs"):
        adjudicate_root_visual_interface_visibility(
            **kwargs, atlas_refs=atlas_refs,
            sample_ids=[row["sampleId"] for row in reviewed["record"]["sourceEvidence"]["observations"][:-1]],
        )
    atlas_path = Path(atlas_refs[0]["path"])
    atlas_path.write_bytes(atlas_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="atlas bytes do not match"):
        adjudicate_root_visual_interface_visibility(
            **kwargs, atlas_refs=atlas_refs,
            sample_ids=[row["sampleId"] for row in reviewed["record"]["sourceEvidence"]["observations"]],
        )


def test_generic_source_contract_requires_exact_full_frame_region_receipts(tmp_path):
    video, pose, record = _case(
        tmp_path, sample_frames=tuple(range(12)), surface="bench")
    reviewed = _run_review(
        tmp_path, video, pose, record, choices=("direct_contact",) * 12)
    requirement = {
        "disposition": "required", "declaredSide": "left", "region": "shoulder",
        "side": "left", "surface": "bench", "contactMode": "stationary",
    }
    review = {
        "contactId": reviewed["record"]["contactId"], "requirement": requirement,
        "record": reviewed["record"], "receiptPath": reviewed["receiptPath"],
        "receiptSha256": reviewed["receiptSha256"],
    }
    evidence = {
        "sourceVideoSha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "bodySurfaceContactEvidence": {
            "sourceVideoSha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            "reviews": [review],
        },
    }
    contract = {"bodySupportRequirements": {"required": [
        {"region": "shoulder", "side": "left", "surface": "bench"}], "prohibited": []}}
    result = bake.body_support_contract_evidence_status(
        contract, evidence, source_pose=pose, selected_video_path=video)
    assert result == {"status": "passed", "failures": []}
    assert "geometryApproval" not in result and "sourceApproval" not in result

    gapped = copy.deepcopy(evidence)
    gapped["bodySurfaceContactEvidence"]["reviews"][0]["record"][
        "sourceEvidence"]["observations"].pop()
    rejected = bake.body_support_contract_evidence_status(
        contract, gapped, source_pose=pose, selected_video_path=video)
    assert rejected["status"] == "insufficient_evidence"
    assert rejected["failures"] == ["required_shoulder_left_support_unobserved"]


def test_batched_review_checkpoints_resume_and_bind_exact_samples(tmp_path):
    video, pose, record = _case(
        tmp_path, name="upper_back", side="center", sample_frames=tuple(range(12)),
        surface="bench-top",
    )
    receipt_dir = tmp_path / "resume-receipts"
    calls = []

    def interrupted_callback(*, frame_paths, response_schema, **_kwargs):
        calls.append(tuple(response_schema["properties"]))
        if len(calls) == 2:
            raise RuntimeError("simulated interruption after first durable batch")
        return json.dumps({alias: "direct_contact" for alias in response_schema["properties"]})

    with pytest.raises(RuntimeError, match="simulated interruption"):
        review_body_surface_contact_samples(
            record, video, pose, caption_images=interrupted_callback,
            receipt_directory=receipt_dir, review_identity={"model": "fixture", "policyVersion": 1},
        )
    assert calls == [("A", "B", "C", "D"), ("A", "B", "C", "D")]
    cache_files = list((receipt_dir / "batch-cache").glob("body-surface-batch-*.json"))
    assert len(cache_files) == 1
    checkpoint = json.loads(cache_files[0].read_text(encoding="utf-8"))
    first_attempt = checkpoint["attempts"][0]
    assert first_attempt["responseSha256"] == hashlib.sha256(
        first_attempt["rawResponse"].encode("utf-8")).hexdigest()
    first_map = checkpoint["identity"]["batch"]
    assert [row["sampleId"] for row in first_map] == [f"upper_back-{i}" for i in range(4)]
    assert [row["sourceFrameIndex"] for row in first_map] == list(range(4))

    resumed_calls = []

    def resume_callback(*, response_schema, **_kwargs):
        resumed_calls.append(tuple(response_schema["properties"]))
        return json.dumps({alias: "direct_contact" for alias in response_schema["properties"]})

    reviewed = review_body_surface_contact_samples(
        record, video, pose, caption_images=resume_callback,
        receipt_directory=receipt_dir, review_identity={"model": "fixture", "policyVersion": 1},
    )
    assert resumed_calls == [("A", "B", "C", "D"), ("A", "B", "C", "D")]
    verified = verify_body_surface_contact_evidence(
        reviewed["record"], video, pose, review_receipt_path=reviewed["receiptPath"],
        review_receipt_sha256=reviewed["receiptSha256"],
    )
    assert [row["sourceFrameIndex"] for row in verified["samples"]] == list(range(12))
    assert [row["sourceTimeSec"] for row in verified["samples"]] == [i / FPS for i in range(12)]
    receipt = json.loads(Path(reviewed["receiptPath"]).read_text(encoding="utf-8"))
    assert [row["batchIndex"] for row in receipt["batchResponses"]] == [0, 1, 2]
    assert [row["sampleId"] for row in receipt["batchResponses"][0]["aliases"]] == [
        f"upper_back-{i}" for i in range(4)]


def test_batched_review_rejects_missing_alias_and_tampered_cache(tmp_path):
    video, pose, record = _case(
        tmp_path, name="upper_back", side="center", sample_frames=(0, 1, 2, 3),
        surface="bench-top",
    )
    receipt_dir = tmp_path / "invalid-receipts"
    calls = 0

    def missing_alias(*, response_schema, **_kwargs):
        nonlocal calls
        calls += 1
        aliases = list(response_schema["properties"])
        if calls == 1:
            return json.dumps({alias: "direct_contact" for alias in aliases[:-1]})
        return json.dumps({alias: "direct_contact" for alias in aliases})

    with pytest.raises(ValueError, match="exactly aliases"):
        review_body_surface_contact_samples(
            record, video, pose, caption_images=missing_alias,
            receipt_directory=receipt_dir, review_identity={"model": "fixture", "policyVersion": 1},
        )
    assert not list(receipt_dir.glob("body-surface-review-*.json"))
    cache_file = next((receipt_dir / "batch-cache").glob("body-surface-batch-*.json"))
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    for attempt in payload["attempts"]:
        attempt["rawResponse"] = json.dumps({"X": "direct_contact"})
        attempt["responseSha256"] = hashlib.sha256(
            attempt["rawResponse"].encode("utf-8")).hexdigest()
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    # The tampered-but-rehashed response still fails strict alias validation and is not reused.
    resumed = review_body_surface_contact_samples(
        record, video, pose, caption_images=missing_alias,
        receipt_directory=receipt_dir, review_identity={"model": "fixture", "policyVersion": 1},
    )
    assert resumed["verifiedEvidence"]["status"] == "verified_samples"
    assert calls == 2
