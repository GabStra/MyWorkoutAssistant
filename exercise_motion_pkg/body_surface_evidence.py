"""Exact-source visual receipts for generic body-surface contact observations."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_frame_png(video: Path, frame_index: int, output: Path) -> str:
    import cv2

    capture = cv2.VideoCapture(str(video))
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok or frame is None or not cv2.imwrite(str(output), frame):
        raise ValueError("review frame cannot be decoded and written from selected video")
    return _sha256(output)


def _reopen_source_identity(
    record, video, source_pose_reference, *,
    source_pose_reference_path=None, source_pose_reference_sha256=None,
):
    from .body_surface_contacts import normalize_body_surface_contact
    from .bake_and_rank import load_verified_source_pose_reference
    from .pose_fidelity import _canonical_source_pose_sha256
    from .source_frame_clock import load_verified_source_frame_clock, source_frame_clock_path_for_video

    contact = normalize_body_surface_contact(record)
    video = Path(video).expanduser().resolve()
    video_sha = _sha256(video)
    source = contact["sourceEvidence"]
    if source["sourceVideoSha256"] != video_sha:
        raise ValueError("body surface contact belongs to different video bytes")
    if source_pose_reference_path is not None or source_pose_reference_sha256 is not None:
        if source_pose_reference_path is None or not source_pose_reference_sha256:
            raise ValueError("explicit canonical source pose receipt requires both path and SHA256")
        pose_path = Path(source_pose_reference_path).expanduser().resolve()
        if not pose_path.is_file() or _sha256(pose_path) != source_pose_reference_sha256:
            raise ValueError("explicit canonical source pose receipt SHA256 mismatch")
    else:
        # Legacy fixed-layout callers may still resolve the canonical receipt
        # relative to a workspace-root video. Nested materialized source cuts
        # must supply their exact phase-bound receipt explicitly.
        pose_path = video.parent.parent / "segment_detection" / "exact_source_pose_reference.json"
    verified_pose = load_verified_source_pose_reference(pose_path, video)
    if not isinstance(verified_pose, dict) or verified_pose.get("sourceVideoSha256") != video_sha:
        raise ValueError("canonical source pose receipt is missing or does not match video")
    pose_sha = _canonical_source_pose_sha256(verified_pose)
    if (source["sourcePosePayloadSha256"] != pose_sha
            or not isinstance(source_pose_reference, dict)
            or source_pose_reference.get("sourceVideoSha256") != video_sha
            or _canonical_source_pose_sha256(source_pose_reference) != pose_sha):
        raise ValueError("contact record or supplied pose differs from canonical source pose")
    clock_path = source_frame_clock_path_for_video(video)
    clock_sha = _sha256(clock_path)
    if source["sourceFrameClockReceiptSha256"] != clock_sha:
        raise ValueError("body surface contact belongs to different frame-clock receipt")
    clock = load_verified_source_frame_clock(clock_path, expected_video_path=video)
    frames, clock_frames = verified_pose.get("frames") or [], clock.get("frames") or []
    fps = float(clock.get("outputFps", 0.0))
    if (not frames or len(clock_frames) != int(clock.get("outputFrameCount", -1))
            or not math.isfinite(fps) or fps <= 0.0 or clock.get("outputVideoSha256") != video_sha):
        raise ValueError("verified source pose or selected-video frame clock is incomplete")
    for row in source["observations"]:
        pi, fi = row["sourcePoseFrameIndex"], row["sourceFrameIndex"]
        if pi >= len(frames) or fi >= len(clock_frames):
            raise ValueError("body surface contact sample is outside verified source frames")
        source_time = float(row["sourceTimeSec"])
        pose_time = float(frames[pi].get("sourceTimeSec", float("nan")))
        if (not math.isfinite(source_time) or not math.isfinite(pose_time)
                or abs(float(row["sourceFps"]) - fps) > .02
                or clock_frames[fi].get("outputFrameIndex") != fi
                or abs(source_time - pose_time) > 1e-6
                or abs(source_time - fi / fps) > 1e-6):
            raise ValueError("body surface contact sample does not match exact source frame clock")
    return contact, video, video_sha, pose_sha, clock_sha, verified_pose, clock, fps


def _contact_prompt(region: dict[str, str], surface_id: str) -> str:
    target = f"{region['side']} {region['name']}" if region["side"] != "center" else region["name"]
    return (
        f"Inspect the full source frame. Is the {target} body surface visibly touching "
        f"the named candidate surface {surface_id!r}? Judge physical body-region contact, "
        "not joint-center proximity or inferred geometry. Return exactly one JSON object "
        'with choice equal to "direct_contact", "no_contact", or "unresolved". '
        "Use no_contact only for visible separation; use unresolved if the interface is "
        "hidden, cropped, ambiguous, or cannot be seen."
    )


def _contact_batch_prompt(body_region: dict[str, str], surface_id: str,
                          batch: list[dict[str, Any]]) -> str:
    target = (f"{body_region['side']} {body_region['name']}"
              if body_region['side'] != 'center' else body_region['name'])
    panels = "\n".join(
        f"{chr(65 + index)}: exact source time {row['sourceTimeSec']:.6f}s."
        for index, row in enumerate(batch)
    )
    return (
        f"Inspect each full source-frame panel independently. Is the {target} body surface "
        f"visibly touching the named candidate surface {surface_id!r}?\n{panels}\n"
        "Judge the named body region itself, not a joint-center marker, posture, or proximity. "
        "For upper_back, assess the posterior upper trunk where it may meet the support; do not "
        "substitute the chest, shirt front, or shoulder point for hidden posterior contact. "
        "Use direct_contact only when touching is visible, no_contact only when separation is visible, "
        "and unresolved when the interface is occluded, ambiguous, or cannot be seen. "
        "Do not infer contact from an exercise name or from another panel. Return exactly one JSON "
        "object with one choice for every alias shown in this batch."
    )


def _contact_batch_atlas(frame_paths: list[Path], output_path: Path) -> str:
    """Build a labeled 2x2 sheet without rescaling or cropping source frames."""
    import cv2
    import numpy as np

    panels = []
    for index, path in enumerate(frame_paths):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("source frame image could not be reopened for body-surface atlas")
        header = np.zeros((30, image.shape[1], 3), dtype=np.uint8)
        cv2.putText(header, chr(65 + index), (10, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    .7, (255, 255, 255), 2, cv2.LINE_AA)
        panels.append(cv2.vconcat((header, image)))
    cell_height = max(panel.shape[0] for panel in panels)
    cell_width = max(panel.shape[1] for panel in panels)
    padded = []
    for panel in panels:
        canvas = np.zeros((cell_height, cell_width, 3), dtype=np.uint8)
        canvas[:panel.shape[0], :panel.shape[1]] = panel
        padded.append(canvas)
    while len(padded) < 4:
        padded.append(np.zeros_like(padded[0]))
    atlas = cv2.vconcat((cv2.hconcat(padded[:2]), cv2.hconcat(padded[2:])))
    if not cv2.imwrite(str(output_path), atlas):
        raise OSError("body-surface batch atlas could not be written")
    return _sha256(output_path)


def _parse_contact_batch_response(raw: Any, aliases: list[str]) -> dict[str, str] | None:
    try:
        answer = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(answer, dict) or set(answer) != set(aliases):
        return None
    if any(choice not in {"direct_contact", "no_contact", "unresolved"}
           for choice in answer.values()):
        return None
    return {alias: answer[alias] for alias in aliases}


def _write_body_surface_batch_cache(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary_path = Path(stream.name)
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def adjudicate_root_visual_interface_visibility(
    record: dict[str, Any], selected_video: str | Path,
    source_pose_reference: dict[str, Any], *,
    review_receipt_path: str | Path, review_receipt_sha256: str,
    source_pose_reference_path: str | Path | None,
    source_pose_reference_sha256: str | None,
    atlas_refs: list[dict[str, Any]], sample_ids: list[str],
    interface_visibility: str, receipt_directory: str | Path,
) -> dict[str, Any]:
    """Persist a separate, source-bound root visual adjudication of visibility.

    This path only records an explicit ambiguous/occluded finding. It never
    edits model answers or turns an unresolved contact requirement into a pass.
    """
    from .body_surface_contacts import normalize_body_surface_contact

    contact = normalize_body_surface_contact(record)
    if "visibilityAdjudication" in contact:
        raise ValueError("contact already has a visibility adjudication")
    if interface_visibility != "occluded_or_ambiguous":
        raise ValueError("root visual overlay only supports occluded_or_ambiguous")
    if not isinstance(sample_ids, list) or not sample_ids or any(
            not isinstance(value, str) or not value for value in sample_ids):
        raise ValueError("root visual adjudication requires explicit sample IDs")
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("root visual adjudication sample IDs must be unique")

    verified = verify_body_surface_contact_evidence(
        contact, selected_video, source_pose_reference,
        review_receipt_path=review_receipt_path,
        review_receipt_sha256=review_receipt_sha256,
        source_pose_reference_path=source_pose_reference_path,
        source_pose_reference_sha256=source_pose_reference_sha256,
    )
    original_path = Path(review_receipt_path).expanduser().resolve()
    original = json.loads(original_path.read_text(encoding="utf-8"))
    binding_samples = original["requestBinding"]["samples"]
    binding_by_id = {row["sampleId"]: row for row in binding_samples}
    verified_by_id = {row["sampleId"]: row for row in verified["samples"]}
    if not set(sample_ids).issubset(binding_by_id):
        raise ValueError("root visual adjudication references an unreviewed sample")

    atlas_rows = []
    atlas_sample_ids: set[str] = set()
    video_path = Path(selected_video).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="body-surface-adjudication-") as temp_dir:
        temp_root = Path(temp_dir)
        for atlas_index, atlas_ref in enumerate(atlas_refs):
            if not isinstance(atlas_ref, dict):
                raise ValueError("atlas reference must be an object")
            if atlas_ref.get("batchIndex") != atlas_index:
                raise ValueError("root visual atlas batch order differs from original review")
            atlas_path = Path(atlas_ref.get("path", "")).expanduser().resolve()
            expected_sha = atlas_ref.get("sha256")
            if not atlas_path.is_file() or not isinstance(expected_sha, str):
                raise ValueError("root visual atlas reference is incomplete")
            if _sha256(atlas_path) != expected_sha:
                raise ValueError("root visual atlas bytes do not match supplied SHA256")
            atlas_samples = atlas_ref.get("samples")
            if not isinstance(atlas_samples, list) or not atlas_samples:
                raise ValueError("root visual atlas must list its reviewed samples")
            expected_batch = binding_samples[atlas_index * 4:(atlas_index + 1) * 4]
            if len(expected_batch) != len(atlas_samples):
                raise ValueError("root visual atlas sample count differs from review batch")
            frame_paths = []
            normalized_atlas_samples = []
            for alias_index, (item, bound) in enumerate(zip(atlas_samples, expected_batch)):
                if not isinstance(item, dict):
                    raise ValueError("root visual atlas sample mapping is malformed")
                alias = chr(ord("A") + alias_index)
                sample_id = item.get("sampleId")
                if (item.get("alias") != alias or sample_id != bound["sampleId"]
                        or sample_id not in sample_ids
                        or sample_id in atlas_sample_ids
                        or any(item.get(key) != bound.get(key) for key in (
                            "sourcePoseFrameIndex", "sourceFrameIndex", "sourceTimeSec"))):
                    raise ValueError("root visual atlas mapping differs from exact review samples")
                atlas_sample_ids.add(sample_id)
                frame_path = temp_root / f"frame-{atlas_index:03d}-{alias}.png"
                actual_image_sha = _source_frame_png(
                    video_path, int(bound["sourceFrameIndex"]), frame_path)
                if actual_image_sha != bound.get("imageSha256"):
                    raise ValueError("root visual atlas sample differs from reviewed source frame")
                frame_paths.append(frame_path)
                normalized_atlas_samples.append({
                    "alias": alias, "sampleId": sample_id,
                    "sourcePoseFrameIndex": bound["sourcePoseFrameIndex"],
                    "sourceFrameIndex": bound["sourceFrameIndex"],
                    "sourceTimeSec": bound["sourceTimeSec"],
                    "imageSha256": bound["imageSha256"],
                })
            rebuilt_path = temp_root / f"atlas-{atlas_index:03d}.png"
            rebuilt_sha = _contact_batch_atlas(frame_paths, rebuilt_path)
            if rebuilt_sha != expected_sha:
                raise ValueError("root visual atlas is not the exact reviewed source-frame sheet")
            atlas_rows.append({
                "batchIndex": atlas_index, "path": str(atlas_path), "sha256": expected_sha,
                "samples": normalized_atlas_samples,
            })
    if atlas_sample_ids != set(sample_ids):
        raise ValueError("root visual adjudication samples must match the reviewed atlas panels")

    adjudication = {
        "schemaVersion": 1,
        "authority": "ROOT_VISUAL_REVIEW",
        "interfaceVisibility": interface_visibility,
        "effectiveVisibility": "unknown",
        "effectiveContactState": "unknown",
        "sourceApproval": False,
        "contactId": contact["contactId"],
        "bodyRegion": contact["bodyRegion"],
        "contactMode": contact["contactMode"],
        "sourceVideoSha256": verified["sourceVideoSha256"],
        "sourcePosePayloadSha256": verified["sourcePosePayloadSha256"],
        "sourceFrameClockReceiptSha256": verified["sourceFrameClockReceiptSha256"],
        "originalReviewReceiptSha256": verified["reviewReceiptSha256"],
        "sampleIds": sorted(sample_ids, key=lambda item: binding_by_id[item]["sourcePoseFrameIndex"]),
        "samples": [{
            "sampleId": sample_id,
            "sourceTimeSec": binding_by_id[sample_id]["sourceTimeSec"],
            "sourcePoseFrameIndex": binding_by_id[sample_id]["sourcePoseFrameIndex"],
            "sourceFrameIndex": binding_by_id[sample_id]["sourceFrameIndex"],
            "originalContactState": verified_by_id[sample_id]["contactState"],
            "effectiveContactState": "unknown",
        } for sample_id in sorted(
            sample_ids, key=lambda item: binding_by_id[item]["sourcePoseFrameIndex"])],
        "atlases": atlas_rows,
    }
    receipt_dir = Path(receipt_directory).expanduser().resolve()
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_bytes = json.dumps(
        adjudication, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_path = receipt_dir / f"root-visual-visibility-{receipt_sha}.json"
    if receipt_path.exists() and receipt_path.read_bytes() != receipt_bytes:
        raise ValueError("content-addressed root visual receipt path contains different bytes")
    if not receipt_path.exists():
        receipt_path.write_bytes(receipt_bytes)
    linked_record = dict(contact)
    linked_record["visibilityAdjudication"] = {
        "receiptPath": str(receipt_path), "receiptSha256": receipt_sha,
    }
    return {"record": linked_record, "receiptPath": str(receipt_path),
            "receiptSha256": receipt_sha, "adjudication": adjudication}


def review_body_surface_contact_samples(
    record: dict[str, Any], selected_video: str | Path,
    source_pose_reference: dict[str, Any], *,
    caption_images: Callable[..., str], receipt_directory: str | Path,
    review_identity: dict[str, Any], prompt_policy_version: str = "generic-body-region-full-frame-batched-v2",
    source_pose_reference_path: str | Path | None = None,
    source_pose_reference_sha256: str | None = None,
) -> dict[str, Any]:
    """Ask for enum-only visual choices on exact full frames and persist a content-addressed receipt."""
    from .body_surface_contacts import normalize_body_surface_contact
    from .bake_and_rank import call_caption_images_json

    contact = normalize_body_surface_contact(record)
    if not callable(caption_images) or not isinstance(review_identity, dict) or not review_identity:
        raise ValueError("caption callable and nonempty review identity are required")
    contact, video, video_sha, pose_sha, clock_sha, _pose, _clock, _fps = _reopen_source_identity(
        contact, selected_video, source_pose_reference,
        source_pose_reference_path=source_pose_reference_path,
        source_pose_reference_sha256=source_pose_reference_sha256)
    source = contact["sourceEvidence"]
    output_rows = []
    raw_responses: dict[str, str] = {}
    batch_responses = []
    sample_bindings = []
    receipt_dir = Path(receipt_directory).expanduser().resolve()
    batch_cache_dir = receipt_dir / "batch-cache"
    with tempfile.TemporaryDirectory(prefix="body-surface-review-") as temp_dir:
        temp_root = Path(temp_dir)
        frame_paths = {}
        for index, row in enumerate(source["observations"]):
            path = temp_root / f"sample-{index:04d}.png"
            image_sha = _source_frame_png(video, row["sourceFrameIndex"], path)
            frame_paths[row["sampleId"]] = path
            sample_bindings.append({
                "sampleId": row["sampleId"], "sourceTimeSec": row["sourceTimeSec"],
                "sourcePoseFrameIndex": row["sourcePoseFrameIndex"],
                "sourceFrameIndex": row["sourceFrameIndex"], "sourceFps": row["sourceFps"],
                "surfaceId": row["surfaceId"], "imageSha256": image_sha,
            })
        request_binding = {
            "policyVersion": prompt_policy_version, "reviewIdentity": review_identity,
            "contactId": contact["contactId"], "bodyRegion": contact["bodyRegion"],
            "contactMode": contact["contactMode"], "surfaceId": source["observations"][0]["surfaceId"],
            "sourceVideoSha256": video_sha, "sourcePosePayloadSha256": pose_sha,
            "sourceFrameClockReceiptSha256": clock_sha, "samples": sample_bindings,
        }
        if any(row["surfaceId"] != request_binding["surfaceId"] for row in source["observations"]):
            raise ValueError("one visual review may query only one named contact surface")
        request_sha = _canonical_sha256(request_binding)
        bindings_by_id = {binding["sampleId"]: binding for binding in sample_bindings}
        for batch_index, start in enumerate(range(0, len(source["observations"]), 4)):
            batch = source["observations"][start:start + 4]
            aliases = [chr(65 + index) for index in range(len(batch))]
            batch_map = [{
                "alias": alias,
                **bindings_by_id[row["sampleId"]],
            } for alias, row in zip(aliases, batch)]
            batch_paths = [frame_paths[row["sampleId"]] for row in batch]
            atlas_path = temp_root / f"batch-{batch_index:03d}.png"
            atlas_sha = _contact_batch_atlas(batch_paths, atlas_path)
            prompt = _contact_batch_prompt(
                contact["bodyRegion"], request_binding["surfaceId"], batch)
            schema = {
                "type": "object", "additionalProperties": False,
                "required": aliases,
                "properties": {alias: {"type": "string", "enum": [
                    "direct_contact", "no_contact", "unresolved"]} for alias in aliases},
            }
            max_tokens = 80 * len(batch)
            batch_identity = {
                "requestSha256": request_sha,
                "reviewIdentity": review_identity,
                "batchIndex": batch_index,
                "batch": batch_map,
                "atlasSha256": atlas_sha,
                "promptSha256": _canonical_sha256(prompt),
                "responseSchemaSha256": _canonical_sha256(schema),
                "maxTokens": max_tokens,
            }
            batch_identity_sha = _canonical_sha256(batch_identity)
            batch_cache_path = batch_cache_dir / f"body-surface-batch-{batch_identity_sha}.json"
            cached_payload = None
            try:
                cached_payload = json.loads(batch_cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            attempts = (
                cached_payload.get("attempts")
                if isinstance(cached_payload, dict)
                and cached_payload.get("identity") == batch_identity
                else None
            )
            choices = None
            selected_raw = None
            if isinstance(attempts, list):
                for attempt in reversed(attempts):
                    raw = attempt.get("rawResponse") if isinstance(attempt, dict) else None
                    if (not isinstance(raw, str)
                            or attempt.get("responseSha256")
                            != hashlib.sha256(raw.encode("utf-8")).hexdigest()):
                        continue
                    parsed = _parse_contact_batch_response(raw, aliases)
                    if parsed is not None:
                        selected_raw, choices = raw, parsed
                        break
            if choices is None:
                raw = call_caption_images_json(
                    caption_images, frame_paths=[atlas_path], prompt=prompt,
                    max_tokens=max_tokens, json_response=True,
                    response_schema=schema, disable_reasoning=True,
                    temperature=0., top_p=1., top_k=1)
                raw_response = raw if isinstance(raw, str) else None
                attempt = {
                    "rawResponse": raw_response,
                    "responseSha256": hashlib.sha256(
                        raw_response.encode("utf-8") if raw_response is not None
                        else repr(raw).encode("utf-8")).hexdigest(),
                }
                retained_attempts = list(attempts) if isinstance(attempts, list) else []
                retained_attempts.append(attempt)
                _write_body_surface_batch_cache(batch_cache_path, {
                    "schemaVersion": 1,
                    "identity": batch_identity,
                    "identitySha256": batch_identity_sha,
                    "attempts": retained_attempts,
                })
                choices = _parse_contact_batch_response(raw_response, aliases)
                if choices is None:
                    raise ValueError(
                        f"contact review response for batch {batch_index} must contain exactly aliases {aliases}")
                selected_raw = raw_response
            assert selected_raw is not None and choices is not None
            batch_responses.append({
                "batchIndex": batch_index,
                "aliases": batch_map,
                "rawResponse": selected_raw,
                "responseSha256": hashlib.sha256(selected_raw.encode("utf-8")).hexdigest(),
            })
            for alias, row in zip(aliases, batch):
                choice = choices[alias]
                raw_responses[row["sampleId"]] = json.dumps(
                    {"choice": choice}, sort_keys=True, separators=(",", ":"))
                output_rows.append({
                    **row,
                    "contactState": "unknown" if choice == "unresolved" else choice,
                    "visible": choice != "unresolved",
                })

    reviewed_record = {**contact, "sourceEvidence": {**source, "observations": output_rows}}
    receipt = {
        "schemaVersion": 1, "requestBinding": request_binding, "requestSha256": request_sha,
        "reviewIdentity": review_identity, "promptPolicyVersion": prompt_policy_version,
        "rawResponses": raw_responses, "batchResponses": batch_responses,
    }
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_bytes = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_path = receipt_dir / f"body-surface-review-{receipt_sha}.json"
    if receipt_path.exists() and receipt_path.read_bytes() != receipt_bytes:
        raise ValueError("content-addressed review receipt path contains different bytes")
    if not receipt_path.exists():
        receipt_path.write_bytes(receipt_bytes)
    verified = verify_body_surface_contact_evidence(
        reviewed_record, video, source_pose_reference,
        review_receipt_path=receipt_path, review_receipt_sha256=receipt_sha,
        source_pose_reference_path=source_pose_reference_path,
        source_pose_reference_sha256=source_pose_reference_sha256)
    return {"record": reviewed_record, "receiptPath": str(receipt_path),
            "receiptSha256": receipt_sha, "requestSha256": request_sha,
            "verifiedEvidence": verified}


def verify_body_surface_contact_evidence(
    record: dict[str, Any], selected_video: str | Path,
    source_pose_reference: dict[str, Any], *,
    review_receipt_path: str | Path | None = None,
    review_receipt_sha256: str | None = None,
    source_pose_reference_path: str | Path | None = None,
    source_pose_reference_sha256: str | None = None,
) -> dict[str, Any]:
    """Reopen source and visual receipts; report samples without inferring intervals or geometry."""
    from .body_surface_contacts import normalize_body_surface_contact

    contact, video, video_sha, pose_sha, clock_sha, pose, clock, fps = _reopen_source_identity(
        record, selected_video, source_pose_reference,
        source_pose_reference_path=source_pose_reference_path,
        source_pose_reference_sha256=source_pose_reference_sha256)
    source = contact["sourceEvidence"]
    if review_receipt_path is None or review_receipt_sha256 is None:
        raise ValueError("persisted body-surface contact review receipt is required")
    receipt_path = Path(review_receipt_path).expanduser().resolve()
    receipt_sha = _sha256(receipt_path)
    if receipt_sha != review_receipt_sha256:
        raise ValueError("body-surface review receipt bytes do not match expected SHA256")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        raw_responses = receipt["rawResponses"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("persisted body-surface review receipt is malformed") from exc
    bindings = receipt.get("requestBinding")
    if not isinstance(bindings, dict) or not isinstance(raw_responses, dict):
        raise ValueError("body-surface review receipt is malformed")
    samples = bindings.get("samples")
    if (receipt.get("schemaVersion") != 1
            or receipt.get("reviewIdentity") != bindings.get("reviewIdentity")
            or not receipt.get("reviewIdentity")
            or receipt.get("promptPolicyVersion") != bindings.get("policyVersion")
            or bindings.get("contactId") != contact["contactId"]
            or bindings.get("bodyRegion") != contact["bodyRegion"]
            or bindings.get("contactMode") != contact["contactMode"]
            or bindings.get("sourceVideoSha256") != video_sha
            or bindings.get("sourcePosePayloadSha256") != pose_sha
            or bindings.get("sourceFrameClockReceiptSha256") != clock_sha
            or receipt.get("requestSha256") != _canonical_sha256(bindings)):
        raise ValueError("body-surface review receipt is not bound to this pre-call request")
    adjudicated_samples: dict[str, dict[str, Any]] = {}
    adjudication_ref = contact.get("visibilityAdjudication")
    if adjudication_ref is not None:
        adjudication_path = Path(adjudication_ref["receiptPath"]).expanduser().resolve()
        if (not adjudication_path.is_file()
                or _sha256(adjudication_path) != adjudication_ref["receiptSha256"]):
            raise ValueError("root visual visibility receipt bytes do not match expected SHA256")
        try:
            adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("root visual visibility receipt is malformed") from exc
        if (not isinstance(adjudication, dict)
                or adjudication.get("schemaVersion") != 1
                or adjudication.get("authority") != "ROOT_VISUAL_REVIEW"
                or adjudication.get("interfaceVisibility") != "occluded_or_ambiguous"
                or adjudication.get("effectiveVisibility") != "unknown"
                or adjudication.get("effectiveContactState") != "unknown"
                or adjudication.get("sourceApproval") is not False
                or adjudication.get("contactId") != contact["contactId"]
                or adjudication.get("bodyRegion") != contact["bodyRegion"]
                or adjudication.get("contactMode") != contact["contactMode"]
                or adjudication.get("sourceVideoSha256") != video_sha
                or adjudication.get("sourcePosePayloadSha256") != pose_sha
                or adjudication.get("sourceFrameClockReceiptSha256") != clock_sha
                or adjudication.get("originalReviewReceiptSha256") != receipt_sha):
            raise ValueError("root visual visibility receipt is not bound to this source review")
        adjudication_rows = adjudication.get("samples")
        if not isinstance(adjudication_rows, list) or not adjudication_rows:
            raise ValueError("root visual visibility receipt has no adjudicated samples")
        for item in adjudication_rows:
            if not isinstance(item, dict):
                raise ValueError("root visual visibility sample is malformed")
            sample_id = item.get("sampleId")
            if (not isinstance(sample_id, str) or sample_id in adjudicated_samples
                    or item.get("effectiveContactState") != "unknown"):
                raise ValueError("root visual visibility sample decision is invalid")
            adjudicated_samples[sample_id] = item
        if adjudication.get("sampleIds") != list(adjudicated_samples):
            raise ValueError("root visual visibility sample inventory is inconsistent")
        atlas_rows = adjudication.get("atlases")
        if not isinstance(atlas_rows, list) or not atlas_rows:
            raise ValueError("root visual visibility receipt lacks reviewed atlas references")
        atlas_sample_ids: set[str] = set()
        for atlas_index, atlas in enumerate(atlas_rows):
            if (not isinstance(atlas, dict) or atlas.get("batchIndex") != atlas_index
                    or not isinstance(atlas.get("path"), str)
                    or not isinstance(atlas.get("sha256"), str)):
                raise ValueError("root visual visibility atlas reference is malformed")
            atlas_path = Path(atlas["path"]).expanduser().resolve()
            if not atlas_path.is_file() or _sha256(atlas_path) != atlas["sha256"]:
                raise ValueError("root visual visibility atlas bytes changed")
            atlas_samples = atlas.get("samples")
            expected_batch = samples[atlas_index * 4:(atlas_index + 1) * 4]
            if not isinstance(atlas_samples, list) or len(atlas_samples) != len(expected_batch):
                raise ValueError("root visual visibility atlas sample count is invalid")
            for panel_index, (panel, bound) in enumerate(zip(atlas_samples, expected_batch)):
                if (not isinstance(panel, dict)
                        or panel.get("alias") != chr(ord("A") + panel_index)
                        or panel.get("sampleId") != bound.get("sampleId")
                        or panel.get("imageSha256") != bound.get("imageSha256")
                        or panel.get("sourceFrameIndex") != bound.get("sourceFrameIndex")
                        or panel.get("sourcePoseFrameIndex") != bound.get("sourcePoseFrameIndex")
                        or panel.get("sourceTimeSec") != bound.get("sourceTimeSec")):
                    raise ValueError("root visual visibility atlas mapping differs from reviewed images")
                sample_id = panel["sampleId"]
                if sample_id in atlas_sample_ids:
                    raise ValueError("root visual visibility sample appears in multiple atlas panels")
                atlas_sample_ids.add(sample_id)
        if atlas_sample_ids != set(adjudicated_samples):
            raise ValueError("root visual visibility atlas sample set differs from adjudication")
    rows = source["observations"]
    if not isinstance(samples, list) or len(samples) != len(rows) or set(raw_responses) != {r["sampleId"] for r in rows}:
        raise ValueError("body-surface review receipt sample set differs from requested samples")
    result_rows = []
    for row, binding in zip(rows, samples):
        expected_binding = {key: row[key] for key in (
            "sampleId", "sourceTimeSec", "sourcePoseFrameIndex", "sourceFrameIndex",
            "sourceFps", "surfaceId")}
        if any(binding.get(key) != value for key, value in expected_binding.items()):
            raise ValueError("body-surface review receipt sample metadata mismatch")
        raw = raw_responses[row["sampleId"]]
        try:
            answer = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("raw contact review response is malformed") from exc
        if not isinstance(answer, dict) or set(answer) != {"choice"}:
            raise ValueError("raw contact review must contain only the code-owned choice field")
        choice = answer["choice"]
        if choice not in {"direct_contact", "no_contact", "unresolved"}:
            raise ValueError("raw contact review choice is outside the allowed enum")
        derived_state = "unknown" if choice == "unresolved" else choice
        derived_visible = choice != "unresolved"
        adjudication_item = adjudicated_samples.get(row["sampleId"])
        if adjudication_item is not None:
            if (adjudication_item.get("sourceTimeSec") != row["sourceTimeSec"]
                    or adjudication_item.get("sourcePoseFrameIndex") != row["sourcePoseFrameIndex"]
                    or adjudication_item.get("sourceFrameIndex") != row["sourceFrameIndex"]
                    or adjudication_item.get("originalContactState") != derived_state):
                raise ValueError("root visual visibility sample differs from original model receipt")
            derived_state = "unknown"
            derived_visible = False
        if row["contactState"] != derived_state or row["visible"] is not derived_visible:
            # The stored record always retains raw enum-derived values. An
            # adjudication changes only the verified effective view.
            if adjudication_item is None or row["contactState"] != (
                    "unknown" if choice == "unresolved" else choice
            ) or row["visible"] is not (choice != "unresolved"):
                raise ValueError("contact observation differs from code-derived raw review choice")
        expected_image_sha = binding.get("imageSha256")
        with tempfile.TemporaryDirectory(prefix="body-surface-verify-") as temp_dir:
            actual_image_sha = _source_frame_png(video, row["sourceFrameIndex"], Path(temp_dir) / "frame.png")
        if expected_image_sha != actual_image_sha:
            raise ValueError("reviewed full-frame PNG differs from exact selected-video frame")
        result_rows.append({
            "sampleId": row["sampleId"], "bodyRegion": dict(contact["bodyRegion"]),
            "contactMode": contact["contactMode"], "sourceTimeSec": row["sourceTimeSec"],
            "sourcePoseFrameIndex": row["sourcePoseFrameIndex"],
            "sourceFrameIndex": row["sourceFrameIndex"], "sourceFps": row["sourceFps"],
            "contactState": derived_state, "visible": derived_visible,
            "rawContactState": "unknown" if choice == "unresolved" else choice,
            "effectiveVisibility": (
                "occluded_or_ambiguous" if adjudication_item is not None else "unadjudicated"
            ),
            "surfaceId": row["surfaceId"],
        })
    observed = sorted({row["sourcePoseFrameIndex"] for row in result_rows})
    frame_count = len(pose.get("frames") or [])
    return {
        "status": "verified_samples", "contactId": contact["contactId"],
        "sourceVideoSha256": video_sha, "sourcePosePayloadSha256": pose_sha,
        "sourceFrameClockReceiptSha256": clock_sha, "reviewReceiptSha256": receipt_sha,
        "samples": result_rows,
        "coverage": {"domain": "canonical_source_pose_frames",
                     "canonicalPoseFrameCount": frame_count,
                     "observedPoseFrameCount": len(observed),
                     "unobservedPoseFrameCount": frame_count - len(observed),
                     "allCanonicalPoseFramesObserved": observed == list(range(frame_count)),
                     "intervalContactInferred": False, "xyzPinsCreated": False},
        "sourceApproval": False,
        "visibilityAdjudication": ({
            "authority": "ROOT_VISUAL_REVIEW",
            "interfaceVisibility": "occluded_or_ambiguous",
            "receiptSha256": contact["visibilityAdjudication"]["receiptSha256"],
            "sampleIds": list(adjudicated_samples),
        } if adjudicated_samples else None),
    }


__all__ = [
    "adjudicate_root_visual_interface_visibility",
    "review_body_surface_contact_samples",
    "verify_body_surface_contact_evidence",
]
