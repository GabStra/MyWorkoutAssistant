"""Shared source-stage support observation and readiness owner.

Both the staged wave and the legacy bake must establish exact-cut support
evidence before an expensive reconstruction attempt.  This module owns the
single bounded observation chain:

* coarse ``observe_body_support``,
* cached dense sole review re-derivation,
* exact-cut foot contact timeline observation,
* one bounded stationary-sole interval review when still unresolved,
* ``pre_reconstruction_source_support_readiness`` after every refresh.

The caller owns contract rejection routing.  Storage failures are re-raised;
observer/tool failures are returned so the caller can route them to source
evidence instead of mislabelling them as geometry failures.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .reconstruction_compat import loads_reconstruction_metadata
from .storage import is_storage_failure, require_storage_reserve

SOURCE_SUPPORT_STAGE_POLICY_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_review_failure(exc: Exception) -> dict[str, str]:
    """Keep a small failure diagnostic without retaining request payloads."""
    raw = str(exc).splitlines()[0].strip()
    if (len(str(exc)) > 512
            or any(marker in raw.casefold() for marker in (
                "prompt", "frame_paths", "data:image", "image_base64",
            ))):
        message = "[omitted potentially payload-bearing exception detail]"
    else:
        message = re.sub(
            r"(?i)\b(authorization|bearer|token|api[_ -]?key|password)\b\s*[:=]?\s*[^\s,;]+",
            r"\1=[redacted]",
            raw,
        )[:240]
    return {"exceptionType": type(exc).__name__, "exceptionMessage": message}


def _pose_reference_receipt_from_workspace(candidate_workspace: Path):
    """Return the canonical pose receipt path/SHA selected by normal phase metadata."""
    segment_detection = Path(candidate_workspace) / "segment_detection"
    candidates = []
    for path, key in (
        (segment_detection / "exact_source_phase_validation.json", "metrics"),
        (segment_detection / "segment_selection.json", "exactSourcePhaseValidation"),
    ):
        try:
            payload = loads_reconstruction_metadata(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        metrics = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(metrics, dict):
            candidates.append(metrics)
    if not candidates:
        return None, None
    def policy_version(item):
        try:
            return int(item.get("validationPolicyVersion") or 0)
        except (TypeError, ValueError):
            return 0

    metrics = max(candidates, key=policy_version)
    reference_path = metrics.get("sourcePoseReferencePath")
    reference_sha = metrics.get("sourcePoseReferenceSha256")
    if not reference_path and not reference_sha:
        return None, None
    if reference_path:
        path = Path(reference_path).expanduser()
        if not path.is_absolute():
            path = Path(candidate_workspace) / path
        reference_path = path.resolve()
    else:
        # A partial explicit binding must fail closed in the consumer.
        reference_path = Path("").resolve()
    return reference_path, str(reference_sha) if reference_sha else None


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write a source receipt without leaving a partial file behind."""
    require_storage_reserve(path, reserve_bytes=64 * 1024**2)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            # Windows readers can briefly deny replacement of the checkpoint.
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def contact_timeline_repair_key(
    source_video_sha256: str,
    source_pose: Any,
    support_evidence: dict[str, Any],
) -> str:
    """Stable identity for one bounded contact-timeline repair attempt."""
    from . import body_support_observation

    evidence_identity = {
        key: value for key, value in support_evidence.items()
        if key != "bodySupportObservation"
    }
    body_observation = support_evidence.get("bodySupportObservation")
    if isinstance(body_observation, dict):
        evidence_identity["bodySupportObservation"] = {
            key: value for key, value in body_observation.items()
            if key not in {"contactTimeline", "contactTimelineRepairEvidenceKey",
                           "contactTimelineAttempt"}
        }
    payload = {
        "policyVersion": body_support_observation.CONTACT_TIMELINE_POLICY_VERSION,
        "cropPolicy": body_support_observation.CONTACT_TIMELINE_CROP_POLICY,
        "sourceVideoSha256": source_video_sha256,
        "sourcePose": source_pose,
        "sourceFootSupportEvidence": evidence_identity,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def refresh_cached_foot_pose_binding(
    evidence, source_video, source_pose, *, camera_normal=None, depth_alignment=None,
):
    """Reassociate cached landmarks when the authoritative source pose changes."""
    from . import foot_contact_observation as fco

    patch = (evidence or {}).get('footPatchEvidence')
    if not fco.foot_patch_pose_binding_failure(patch, source_pose):
        return evidence, {'refreshed': False, 'reason': 'binding_current_or_not_required'}
    observations = fco.load_cached_foot_landmarks(Path(source_video))
    if observations is None:
        return evidence, {'refreshed': False, 'reason': 'raw_landmark_cache_unavailable'}
    refreshed = fco.add_observed_foot_contacts(
        evidence, observations, source_pose, camera_normal, depth_alignment,
        source_video_path=Path(source_video))
    if (refreshed.get('footPatchEvidence') or {}).get('available') is not True:
        return evidence, {'refreshed': False, 'reason': 'reclassification_unavailable'}
    failure = fco.foot_patch_pose_binding_failure(
        refreshed.get('footPatchEvidence'), source_pose)
    if failure:
        return evidence, {'refreshed': False, 'reason': failure}
    return refreshed, {'refreshed': True, 'bindingFailure': failure}


def reclassify_source_foot_contacts_from_timeline(
    support_evidence: dict[str, Any],
    timeline: dict[str, Any],
    source_video: Path,
    source_pose: dict[str, Any],
) -> dict[str, Any]:
    """Apply a newly observed exact-source timeline before persisting foot states."""
    from . import body_support_observation as bso
    from . import foot_contact_observation as fco

    digest = str(support_evidence.get("sourceVideoSha256") or "")
    if (source_pose is None or not source_video.is_file()
            or not bso.validated_body_support_contact_timeline(
                timeline, expected_video_sha256=digest)):
        return support_evidence

    # The nested body-support receipt may have a separate status. Pass the
    # validated point timeline directly to the classifier without rewriting it.
    original_observation = support_evidence.get("bodySupportObservation")
    classifier_input = dict(support_evidence)
    classifier_input["bodySupportObservation"] = timeline
    refreshed = fco.add_observed_foot_contacts(
        classifier_input, fco.observe_foot_landmarks(source_video), source_pose,
        source_video_path=source_video,
    )
    if original_observation is not None:
        refreshed["bodySupportObservation"] = original_observation
    return refreshed


def dense_sole_review_is_source_bound(
    support_evidence: dict[str, Any],
    review: dict[str, Any],
) -> bool:
    """A dense review may only re-derive evidence for its exact source cut."""
    digest = str(support_evidence.get("sourceVideoSha256") or "")
    patch = support_evidence.get("footPatchEvidence") or {}
    frame_count = patch.get("sourceFrameCount")
    return bool(
        digest
        and str(review.get("sourceVideoSha256") or "") == digest
        and patch.get("sourceVideoSha256") == digest
        and patch.get("available") is True
        and type(frame_count) is int
        and frame_count > 0
        and review.get("sourceFrameCount") == frame_count
    )


def refresh_source_foot_contacts_from_dense_sole_review(
    support_evidence: dict[str, Any],
    source_video: Path,
    source_pose: dict[str, Any],
) -> dict[str, Any] | None:
    """Derive contacts and material proof from a source-bound dense sole review.

    The dense review owns native-frame visual sole facts; the shared foot
    classifier owns the derived contacts and their material corroboration. Run
    that derivation before readiness/admission so the source decision consumes
    exactly the evidence the bake stage would otherwise discover later. Cached
    landmarks are reused when available.
    """
    from . import foot_contact_observation as fco

    review = support_evidence.get("stationarySoleIntervalReview")
    if (source_pose is None or not isinstance(review, dict)
            or not dense_sole_review_is_source_bound(support_evidence, review)
            or not source_video.is_file()):
        return None
    observations = fco.observe_foot_landmarks(source_video)
    if observations.get("available") is not True:
        return None
    refreshed = fco.add_observed_foot_contacts(
        dict(support_evidence), observations, source_pose,
        source_video_path=source_video,
    )
    if (refreshed.get("footPatchEvidence") or {}).get("available") is not True:
        return None
    return refreshed


def persist_exact_source_support_evidence(
    candidate_workspace: Path,
    source_video_sha256: str,
    support_evidence: dict[str, Any],
) -> bool:
    """Persist refreshed evidence only into artifacts bound to the exact cut."""
    segment_detection = candidate_workspace / "segment_detection"
    validation_path = segment_detection / "exact_source_phase_validation.json"
    try:
        validation = loads_reconstruction_metadata(
            validation_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return False
    metrics = validation.get("metrics") if isinstance(validation, dict) else None
    if (not isinstance(metrics, dict)
            or str(metrics.get("sourceVideoSha256") or "").casefold()
            != source_video_sha256.casefold()
            or str(support_evidence.get("sourceVideoSha256") or "").casefold()
            != source_video_sha256.casefold()):
        return False

    selection_path = segment_detection / "segment_selection.json"
    try:
        selection = loads_reconstruction_metadata(
            selection_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        selection = None
    selected_metrics = (selection.get("exactSourcePhaseValidation")
                        if isinstance(selection, dict) else None)
    if (isinstance(selected_metrics, dict)
            and str(selected_metrics.get("sourceVideoSha256") or "").casefold()
            != source_video_sha256.casefold()):
        # The loader may prefer this newer receipt over exact validation. Never
        # persist to only one side and then let the downstream loader select a
        # different cut's metrics.
        return False

    metrics["sourceFootSupportEvidence"] = support_evidence
    if (isinstance(selected_metrics, dict)
            and str(selected_metrics.get("sourceVideoSha256") or "").casefold()
            == source_video_sha256.casefold()):
        selected_metrics["sourceFootSupportEvidence"] = support_evidence
        # This artifact can outrank exact validation in the loader, so update it
        # first. A later validation-write failure still leaves one reusable,
        # exact-hash-bound copy for downstream stages.
        write_json_atomic(selection_path, selection)
    write_json_atomic(validation_path, validation)
    if not _persist_body_support_timeline_cache(
            candidate_workspace, source_video_sha256, support_evidence):
        return False
    return True


def _persist_body_support_timeline_cache(
    candidate_workspace: Path,
    source_video_sha256: str,
    support_evidence: dict[str, Any],
) -> bool:
    """Keep the latest validated timeline available to later support refreshes.

    The source-phase receipt and body-support observer cache are separate inputs
    to baking. A later coarse observation can be selected from the latter and
    replace a timeline-bearing observation from the former, so carry only the
    exact-hash-validated timeline into the observer cache before fit begins.
    """
    from . import body_support_observation as bso

    observation = support_evidence.get("bodySupportObservation")
    if (not isinstance(observation, dict)
            or str(observation.get("sourceVideoSha256") or "").casefold()
            != source_video_sha256.casefold()
            or observation.get("policyVersion") != bso.POLICY_VERSION
            or bso.validated_body_support_answer(observation) is None):
        return True
    timeline = observation.get("contactTimeline")
    if not isinstance(timeline, dict):
        return True
    if not bso.validated_body_support_contact_timeline(
            timeline, expected_video_sha256=source_video_sha256):
        return False

    cache_dir = candidate_workspace / "segment_detection" / "body_support"
    base_name = f"body-support-{source_video_sha256}-v{bso.POLICY_VERSION}"
    cache_paths = [cache_dir / f"{base_name}.json", cache_dir / f"{base_name}-labeled.json"]
    for cache_path in cache_paths:
        if cache_path.name.endswith("-labeled.json") and not cache_path.exists():
            continue
        try:
            cached = loads_reconstruction_metadata(
                cache_path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            cached = dict(observation)
        except ValueError:
            if cache_path.name.endswith("-labeled.json"):
                continue
            cached = dict(observation)
        except OSError:
            return False
        if not isinstance(cached, dict):
            return False
        if (str(cached.get("sourceVideoSha256") or "").casefold()
                != source_video_sha256.casefold()
                or cached.get("policyVersion") != bso.POLICY_VERSION):
            return False
        if bso.validated_body_support_answer(cached) is None:
            # An invalid observer cache remains retryable; the standard cache
            # is seeded below from the already-validated exact-source answer.
            if cache_path.name.endswith("-labeled.json"):
                continue
            cached = dict(observation)
        else:
            cached = dict(cached)
        for key in tuple(cached):
            if key.startswith("contactTimeline"):
                cached.pop(key, None)
        for key, value in observation.items():
            if key.startswith("contactTimeline"):
                cached[key] = value
        write_json_atomic(cache_path, cached)
    return True


def source_support_readiness_route(readiness: dict[str, Any]) -> tuple[str, list[str]]:
    """Route contact-evidence gaps to retained-source review.

    Even a same-time disagreement between contact observers is a conflict in
    evidence, not a verified contract violation. Source rejection remains owned
    by the independent source/contract gates. Older payloads are unresolved.
    """
    reasons_value = readiness.get("rejectionReasons") if isinstance(readiness, dict) else None
    reasons = [str(reason) for reason in reasons_value or [] if str(reason).strip()]
    status = (str(readiness.get("status") or "").strip().casefold()
              if isinstance(readiness, dict) else "")
    if status == "ready" or (isinstance(readiness, dict) and readiness.get("passed") is True):
        return "ready", reasons
    if not reasons:
        reasons = ["source_support_contact_evidence_incomplete"]
    return "incomplete", reasons


def _downgrade_for_persistence_failure(readiness: dict[str, Any]) -> dict[str, Any]:
    downgraded = dict(readiness)
    downgraded.update(status="incomplete", available=False, passed=False)
    downgraded["rejectionReasons"] = list(dict.fromkeys([
        *(downgraded.get("rejectionReasons") or []),
        "source_support_evidence_persistence_unavailable",
    ]))
    return downgraded


def _generic_body_surface_review_records(
    requirements, selected_video, pose_reference, *, include_legacy_requirements=(),
):
    """Build exact-frame requests only for body regions not owned by legacy point paths."""
    from .pose_fidelity import _canonical_source_pose_sha256
    from .source_frame_clock import load_verified_source_frame_clock, source_frame_clock_path_for_video

    video = Path(selected_video).resolve()
    video_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    if not isinstance(pose_reference, dict) or pose_reference.get("sourceVideoSha256") != video_sha:
        raise ValueError("generic body-region contact review pose belongs to different source video")
    pose_sha = _canonical_source_pose_sha256(pose_reference)
    clock_path = source_frame_clock_path_for_video(video)
    clock_sha = hashlib.sha256(clock_path.read_bytes()).hexdigest()
    clock = load_verified_source_frame_clock(clock_path, expected_video_path=video)
    fps = float(clock.get("outputFps", 0.0))
    pose_payload = pose_reference.get("pose")
    pose_container = pose_payload if isinstance(pose_payload, dict) else pose_reference
    frames = pose_container.get("frames") or []
    if not frames or fps <= 0.0:
        raise ValueError("generic body-region contact review requires verified source pose frames and clock")
    legacy_regions = {"ankle", "foot", "knee", "hand", "pelvis", "upper_back", "head"}
    include_legacy_requirements = set(include_legacy_requirements)
    records = []
    for disposition in _BODY_SURFACE_REVIEW_DISPOSITIONS:
        for requirement in (requirements or {}).get(disposition, []):
            region = requirement["region"]
            identity = (region, requirement.get("side"),
                        requirement.get("surface", "any"),
                        requirement.get("contactMode", "stationary"))
            if region in legacy_regions and identity not in include_legacy_requirements:
                continue
            declared_side = requirement["side"]
            sides = ["left", "right"] if declared_side in {"both", "either"} else [declared_side]
            surface = requirement.get("surface", "any")
            for side in sides:
                region_side = "center" if side == "center" else side
                item = {"disposition": disposition, "declaredSide": declared_side,
                        "region": region, "side": region_side,
                        "surface": surface, "contactMode": requirement.get("contactMode", "stationary")}
                contact_id = hashlib.sha256(json.dumps(
                    {"video": video_sha, **item}, sort_keys=True, separators=(",", ":")
                ).encode()).hexdigest()[:24]
                observations = []
                for index, frame in enumerate(frames):
                    source_time = float(frame.get("sourceTimeSec", float("nan")))
                    frame_index = round(source_time * fps)
                    if abs(source_time - frame_index / fps) > 1e-6:
                        raise ValueError("canonical pose sample does not align to selected-video frame clock")
                    observations.append({
                        "sampleId": f"{contact_id}-{index}", "sourceTimeSec": source_time,
                        "sourcePoseFrameIndex": index, "sourceFrameIndex": frame_index,
                        "sourceFps": fps, "contactState": "unknown", "visible": False,
                        "surfaceId": surface,
                    })
                records.append({
                    "requirement": item,
                    "record": {
                    "schemaVersion": 1, "contactId": contact_id,
                    "bodyRegion": {"name": region, "side": region_side},
                    "contactMode": item["contactMode"],
                    "sourceEvidence": {"sourceVideoSha256": video_sha,
                                       "sourcePosePayloadSha256": pose_sha,
                                       "sourceFrameClockReceiptSha256": clock_sha,
                                       "observations": observations},
                    "patchBinding": None, "surfaceEstimate": None,
                    "geometryProvenance": None,
                    },
                })
    return records


_BODY_SURFACE_REVIEW_DISPOSITIONS = ("required", "prohibited", "discovery")


def _body_surface_review_requests(requirements, hints):
    """Merge real requirements with discovery-only hint entries.

    Hint entries live under their own disposition so validators that read only
    ``required``/``prohibited`` cannot turn a hint into a hard requirement.
    """
    requests = {
        "required": list((requirements or {}).get("required") or []),
        "prohibited": list((requirements or {}).get("prohibited") or []),
    }
    declared = {
        (item.get("region"), item.get("side"), item.get("surface", "any"),
         item.get("contactMode", "stationary"))
        for item in (*requests["required"], *requests["prohibited"])
        if isinstance(item, dict)
    }
    discovery = []
    for hint in hints:
        identity = (hint.get("region"), hint.get("side"), hint.get("surface", "any"),
                    hint.get("contactMode", "stationary"))
        if identity in declared:
            continue
        declared.add(identity)
        discovery.append(hint)
    if discovery:
        requests["discovery"] = discovery
    return requests


def _unresolved_required_legacy_requirements(requirements, contract_status):
    """Return required legacy targets whose exact typed/timed check did not pass."""
    if not isinstance(contract_status, dict) or contract_status.get("status") not in {
        "insufficient_evidence", "contradicted",
    }:
        return set()
    # Feet retain their dedicated material/sole interval reviewer below.
    legacy_regions = {"ankle", "knee", "hand", "pelvis", "upper_back", "head"}
    failures = tuple(str(value) for value in contract_status.get("failures") or [])
    unresolved = set()
    for item in (requirements or {}).get("required") or []:
        if not isinstance(item, dict) or item.get("region") not in legacy_regions:
            continue
        prefix = f"required_{item.get('region')}_{item.get('side')}_support_"
        if any(value.startswith(prefix) for value in failures):
            unresolved.add((item["region"], item.get("side"),
                            item.get("surface", "any"),
                            item.get("contactMode", "stationary")))
    return unresolved


def _pending_required_foot_ground_material_inference(
    candidate_workspace: Path,
    contract: dict[str, Any],
    evidence: dict[str, Any],
    readiness: dict[str, Any],
    selected_video: Path,
    source_pose: dict[str, Any] | None,
    source_pose_reference: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Describe exact-source foot-patch uncertainty without turning it into pins."""
    requirements = (contract.get("bodySupportRequirements") or {}).get("required") or []
    ground_requirements = [item for item in requirements if isinstance(item, dict)
                           and item.get("region") == "foot"
                           and item.get("surface") in {"ground", "floor"}
                           and item.get("side") in {"both", "left", "right"}]
    reasons = list(readiness.get("rejectionReasons") or [])
    supported_readiness_reasons = {
        "source_support_contact_evidence_incomplete",
        "body_surface_contact_source_evidence_unavailable",
    }
    if (not ground_requirements
            or not reasons or any(reason not in supported_readiness_reasons for reason in reasons)
            or not isinstance(source_pose, dict)
            or not isinstance(source_pose_reference, dict)):
        return []

    from .body_support_observation import validated_body_support_answer, validated_body_support_contact_timeline
    from .foot_contact_observation import POLICY_VERSION as FOOT_PATCH_POLICY_VERSION
    from .pose_fidelity import _canonical_source_pose_sha256
    from .source_frame_clock import load_verified_source_frame_clock, source_frame_clock_path_for_video
    from .source_support_tracking import FOOT_MATERIAL_POLICY_VERSION
    from .bake_and_rank import (
        SOURCE_POSE_SUPPORT_EVIDENCE_POLICY_VERSION,
        source_pose_support_contract_fingerprint,
    )

    video = Path(selected_video).expanduser().resolve()
    if not video.is_file():
        return []
    video_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    pose = source_pose.get("pose") if isinstance(source_pose.get("pose"), dict) else source_pose
    frames = pose.get("frames") if isinstance(pose, dict) else None
    pose_sha = _canonical_source_pose_sha256(pose) if isinstance(pose, dict) else None
    if (not isinstance(frames, list) or not frames
            or source_pose_reference.get("sourceVideoSha256") != video_sha
            or source_pose_reference.get("pose") != pose
            or source_pose.get("sourceVideoSha256") not in (None, video_sha)):
        return []
    reference_path, _ = _pose_reference_receipt_from_workspace(candidate_workspace)
    if not reference_path.is_file():
        return []
    reference_sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    _, recorded_reference_sha = _pose_reference_receipt_from_workspace(candidate_workspace)
    if recorded_reference_sha != reference_sha:
        return []

    clock_path = source_frame_clock_path_for_video(video)
    try:
        clock = load_verified_source_frame_clock(clock_path, expected_video_path=video)
    except (OSError, ValueError, TypeError):
        return []
    clock_sha = hashlib.sha256(clock_path.read_bytes()).hexdigest()
    patch = evidence.get("footPatchEvidence") or {}
    states_by_side = patch.get("feet") or {}
    count = clock.get("outputFrameCount")
    patch_times = patch.get("sourceTimesSec")
    clock_frames = clock.get("frames")
    try:
        patch_origin = float(patch.get("sourceTimeOriginSec"))
        output_fps = float(clock.get("outputFps", 0.))
    except (TypeError, ValueError, OverflowError):
        return []
    if (evidence.get("sourceVideoSha256") != video_sha
            or evidence.get("sourcePoseSupportEvidencePolicyVersion")
            != SOURCE_POSE_SUPPORT_EVIDENCE_POLICY_VERSION
            or evidence.get("sourcePoseSupportContractFingerprint")
            != source_pose_support_contract_fingerprint(contract)
            or patch.get("available") is not True
            or patch.get("policyVersion") != FOOT_PATCH_POLICY_VERSION
            or patch.get("materialStationarityPolicyVersion") != FOOT_MATERIAL_POLICY_VERSION
            or patch.get("sourceVideoSha256") != video_sha
            or patch.get("sourcePoseVideoSha256") != video_sha
            or patch.get("sourcePosePayloadSha256") != pose_sha
            or patch.get("sourcePoseFrameCount") != len(frames)
            or patch.get("sourceFrameCount") != count
            or type(count) is not int or count <= 0
            or not isinstance(patch_times, list) or len(patch_times) != count
            or not isinstance(clock_frames, list) or len(clock_frames) != count
            or not patch.get("sourceTimeBasis")
            or abs(float(patch.get("sourceFps", 0.)) - output_fps) > .02):
        return []
    try:
        if any(clock_frames[index].get("outputFrameIndex") != index
               or abs(float(patch_times[index]) - (patch_origin + index / output_fps)) > 1e-6
               for index in range(count)):
            return []
    except (KeyError, TypeError, ValueError, OverflowError):
        return []
    try:
        pose_origin = float(pose.get("sourceTimeOriginSec", 0.))
        pose_tolerance = float(pose.get("sourcePoseSampleBoundaryToleranceSeconds", 1. / output_fps))
        if any(abs((float(frame.get("sourceTimeSec")) - pose_origin)
                   - round((float(frame.get("sourceTimeSec")) - pose_origin) * output_fps) / output_fps)
               > pose_tolerance + 1e-6 for frame in frames):
            return []
    except (TypeError, ValueError, OverflowError):
        return []

    observation = evidence.get("bodySupportObservation")
    answer = validated_body_support_answer(observation)
    if (not isinstance(observation, dict)
            or observation.get("sourceVideoSha256") != video_sha
            or answer is None):
        return []
    timeline = validated_body_support_contact_timeline(
        observation, expected_video_sha256=video_sha,
    ) or []
    if any(row.get("contactState") in {"airborne", "no_contact"}
           and row.get("visible") is True for row in timeline
           if row.get("landmark", "foot") == "foot"):
        return []

    unresolved = readiness.get("unresolvedSides") or []
    if not unresolved or not set(unresolved).issubset({"left", "right"}):
        return []
    pending: list[dict[str, Any]] = []
    for item in ground_requirements:
        sides = ["left", "right"] if item.get("side") == "both" else [item["side"]]
        for side in sides:
            if side not in unresolved:
                continue
            foot = states_by_side.get(side)
            states = foot.get("states") if isinstance(foot, dict) else None
            if (not isinstance(states, list) or len(states) != count
                    or any(state not in {"unknown", "toe_only", "full_sole", "heel_only"}
                           for state in states)
                    or "unknown" not in states):
                return []
            coarse_state = answer.get(f"{side}Foot")
            coarse_surface = answer.get(f"{side}FootSurface")
            if (coarse_state not in {"unknown", "stationary_full_sole", "stationary_forefoot",
                                     "supported_dorsum"}
                    or coarse_surface not in {"unknown", "ground", "floor"}):
                return []
            unknown_indexes = [i for i, state in enumerate(states) if state == "unknown"]
            pending.append({
                "kind": "required_foot_ground_material_inference",
                "requirement": {"region": "foot", "side": side,
                                 "surface": item.get("surface"),
                                 "contactMode": item.get("contactMode", "stationary")},
                "sourceVideoSha256": video_sha,
                "sourcePoseReferenceSha256": reference_sha,
                "sourcePosePayloadSha256": pose_sha,
                "sourceFrameClockReceiptSha256": clock_sha,
                "footPatchEvidencePolicyVersion": FOOT_PATCH_POLICY_VERSION,
                "materialStationarityPolicyVersion": FOOT_MATERIAL_POLICY_VERSION,
                "sourceFrameCount": count,
                "sourcePoseFrameCount": len(frames),
                "unknownFrameIndexes": unknown_indexes,
                "unknownSelectedSourceFrameIndexes": [
                    clock_frames[i]["sourceFrameIndex"] for i in unknown_indexes
                ],
                "observedPatchStates": sorted(set(states)),
                "coarseObservedState": coarse_state,
                "coarseObservedSurface": coarse_surface,
                "accountsForReadinessReasons": (
                    ["source_support_contact_evidence_incomplete"]
                    if "source_support_contact_evidence_incomplete" in reasons else []
                ),
                "sourceApproval": False,
                "geometryApproval": False,
            })
    expected_sides = {
        side for item in ground_requirements
        for side in (["left", "right"] if item.get("side") == "both" else [item["side"]])
        if side in unresolved
    }
    if {item["requirement"]["side"] for item in pending} != expected_sides:
        return []
    return pending


def _stage_result(
    *,
    evidence: dict[str, Any],
    readiness: dict[str, Any],
    contract_status: dict[str, Any],
    refreshed: bool,
    persisted: bool,
    steps: list[str],
    contradiction: bool = False,
    contract_insufficient: bool = False,
    timeline_status: str | None = None,
    timeline_error: BaseException | None = None,
    unresolved_ground_review: bool = False,
    stationary_sole_review_attempted: bool = False,
    reconstruction_only_pending_inference: bool = False,
    pending_inference_requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "policyVersion": SOURCE_SUPPORT_STAGE_POLICY_VERSION,
        "evidence": evidence,
        "readiness": readiness,
        "contractStatus": contract_status,
        "refreshed": refreshed,
        "persisted": persisted,
        "steps": list(steps),
        "contradiction": contradiction,
        "contractInsufficient": contract_insufficient,
        "timelineStatus": timeline_status,
        "timelineError": timeline_error,
        "unresolvedGroundReview": unresolved_ground_review,
        "stationarySoleReviewAttempted": stationary_sole_review_attempted,
        "reconstructionOnlyPendingInference": reconstruction_only_pending_inference,
        "pendingInferenceRequirements": list(pending_inference_requirements or []),
    }


def observe_source_support_stage(
    candidate_workspace: Path,
    selected_video: Path,
    *,
    contract: dict[str, Any] | None,
    caption_images: Callable[..., str] | None,
    source_pose: dict[str, Any] | None,
    source_pose_reference: dict[str, Any] | None,
    source_foot_support_evidence: dict[str, Any] | None,
    contract_status_fn: Callable[..., dict[str, Any]],
    stance_review_cache_dir: Path | None = None,
    joint_names: Sequence[str] | None = None,
    persist_evidence: bool = True,
    persist_fn: Callable[[Path, str, dict[str, Any]], bool] | None = None,
    write_json_fn: Callable[[Path, dict[str, Any]], None] | None = None,
    write_repair_marker: bool = True,
    force_observation: bool = False,
) -> dict[str, Any]:
    """Run the bounded exact-cut support observation/readiness chain once.

    ``contract_status_fn`` must be ``body_support_contract_evidence_status``
    (passed by the caller to avoid a module import cycle).  The returned
    evidence is in-memory and already persisted when ``persist_evidence`` is
    true and exact-cut receipts are available.
    """
    from . import body_support_observation as bso
    from . import foot_contact_observation as fco
    from . import support_geometry
    from .smpl_joint_names import SMPL_JOINT_NAMES

    persist_fn = persist_fn or persist_exact_source_support_evidence
    write_json_fn = write_json_fn or write_json_atomic
    candidate_workspace = Path(candidate_workspace)
    selected_video = Path(selected_video)
    contract = contract if isinstance(contract, dict) else {}
    ground_contact_mode = contract.get("groundContactMode")
    requirements = contract.get("bodySupportRequirements")
    contract_requires_observation = isinstance(requirements, dict) and bool(
        requirements.get("required") or requirements.get("prohibited")
    )
    discovery_hints = bso.body_support_discovery_hint_items(contract)
    # A typed requirement or an explicit caller request owns source
    # observation. Ground mode is judged by readiness itself, so it must not
    # silently turn a wave candidate with no retained evidence into a new
    # observation after this refactor; the legacy owner opts in with
    # ``force_observation``.
    observation_required = bool(
        force_observation or contract_requires_observation or discovery_hints
    )
    joint_names = list(joint_names or SMPL_JOINT_NAMES)
    steps: list[str] = []
    refreshed = False
    persisted = False
    evidence = (
        dict(source_foot_support_evidence)
        if isinstance(source_foot_support_evidence, dict)
        else {}
    )
    if not isinstance(source_foot_support_evidence, dict) and not observation_required:
        # No source observation is owned or requested. Preserve the legacy
        # behavior of proceeding without inventing support evidence.
        contract_status = contract_status_fn(
            contract, evidence, source_pose=source_pose,
            selected_video_path=selected_video,
        )
        return _stage_result(
            evidence=evidence,
            readiness={
                "status": "not_observed",
                "required": False,
                "available": False,
                "evaluated": False,
                "passed": True,
                "rejectionReasons": [],
            },
            contract_status=contract_status,
            refreshed=False,
            persisted=False,
            steps=["observation_not_required"],
        )

    source_digest = hashlib.sha256(selected_video.read_bytes()).hexdigest()
    body_support_dir = candidate_workspace / "segment_detection" / "body_support"
    stance_cache_dir = (
        Path(stance_review_cache_dir)
        if stance_review_cache_dir is not None
        else candidate_workspace / "source-review-cache" / "stance-intervals"
    )
    if not evidence and observation_required:
        evidence = {"contacts": []}
    if evidence:
        cached_digest = evidence.get("sourceVideoSha256")
        if ((cached_digest
             and str(cached_digest).casefold() != source_digest.casefold())
                or (observation_required and not cached_digest)):
            # Never carry support claims from a different cut into this
            # candidate's source decision.
            evidence = {"sourceVideoSha256": source_digest, "contacts": []}
            refreshed = True
            steps.append("source_identity_reset")

    contract_status = contract_status_fn(
        contract, evidence, source_pose=source_pose,
        selected_video_path=selected_video,
    )
    existing_observation = evidence.get("bodySupportObservation")
    if (contract_status.get("status") != "contradicted"
            and (bso.source_support_observation_needed(
                source_pose, evidence, contract)
                 or isinstance(existing_observation, dict))):
        required_observation_fields = bso.body_support_discovery_observation_fields(
            contract)
        request_identity = bso.body_support_discovery_request_identity(contract)
        reused_reviewed_coarse = False
        if isinstance(existing_observation, dict):
            # First ask the normal observer's cache-only path. It validates the
            # exact video, policy, discovery request and required fields while
            # preserving the original reviewIdentity. A new provider identity
            # must not cause a second coarse review of unchanged, complete
            # source evidence; the provider is still used below for any new
            # timeline observations.
            cached_observation = bso.observe_body_support(
                selected_video,
                None,
                body_support_dir,
                existing_observation=existing_observation,
                require_knee_observation=True,
                required_observation_fields=required_observation_fields,
                request_identity=request_identity,
            )
            cached_answer = bso.validated_body_support_answer(cached_observation)
            reused_reviewed_coarse = bool(
                isinstance(cached_observation, dict)
                and cached_observation.get("status") == "observed"
                and str(cached_observation.get("sourceVideoSha256") or "").casefold()
                == source_digest.casefold()
                and cached_observation.get("policyVersion") == bso.POLICY_VERSION
                and isinstance(cached_observation.get("reviewIdentity"), dict)
                and bool(cached_observation.get("reviewIdentity"))
                and (request_identity is None
                     or cached_observation.get("requestIdentity") == request_identity)
                and cached_answer is not None
                and bso.body_support_observation_covers(
                    cached_observation, required_observation_fields,
                )
            )
            if reused_reviewed_coarse:
                existing_observation = cached_observation
                steps.append("coarse_support_cache_reused")
            elif caption_images is None:
                # Keep cache-only callers fail-closed when a receipt is stale,
                # incomplete or unbound; no model is available to repair it.
                existing_observation = cached_observation
        if not reused_reviewed_coarse and caption_images is not None:
            # Invalid/missing cache uses the current provider and its actual
            # identity through the normal owner.
            existing_observation = bso.observe_body_support(
                selected_video,
                caption_images,
                body_support_dir,
                existing_observation=existing_observation,
                require_knee_observation=True,
                required_observation_fields=required_observation_fields,
                request_identity=request_identity,
            )
            refreshed = True
        elif not reused_reviewed_coarse:
            # Cache-only validation produced the current observer-unavailable
            # result, which remains unresolved and is never promoted.
            refreshed = existing_observation != evidence.get("bodySupportObservation")
        if not reused_reviewed_coarse:
            steps.append("coarse_support_observation")
        evidence["bodySupportObservation"] = existing_observation

    # A previously persisted dense review must also refresh its derived
    # contacts/material proof before this attempt's first readiness check.
    dense_refresh = refresh_source_foot_contacts_from_dense_sole_review(
        evidence, selected_video, source_pose,
    )
    if dense_refresh is not None:
        evidence = dense_refresh
        refreshed = True
        steps.append("dense_sole_review_refresh")

    contract_status = contract_status_fn(
        contract, evidence, source_pose=source_pose,
        selected_video_path=selected_video,
    )
    if (contract_status.get("status") == "contradicted"
            and not _unresolved_required_legacy_regions(requirements, contract_status)):
        if refreshed and persist_evidence:
            persisted = persist_fn(candidate_workspace, source_digest, evidence)
        return _stage_result(
            evidence=evidence, readiness={}, contract_status=contract_status,
            refreshed=refreshed, persisted=persisted, steps=steps,
            contradiction=True,
        )

    def current_support_readiness() -> dict[str, Any]:
        bso.materialize_knee_support({
            "jointNames": joint_names,
            "sourceFootSupportEvidence": evidence,
        }, source_pose_reference)
        return support_geometry.pre_reconstruction_source_support_readiness(
            evidence,
            source_frames=(source_pose or {}).get("frames"),
            ground_contact_mode=ground_contact_mode,
            source_pose=source_pose_reference,
            source_video_path=selected_video,
            exercise_motion_contract=contract,
        )

    readiness = current_support_readiness()
    answer = bso.validated_body_support_answer(existing_observation)
    if (not readiness.get("passed")
            and (answer is None
                 or any(f"{side}Knee" not in answer for side in ("left", "right")))):
        existing_observation = bso.observe_body_support(
            selected_video,
            caption_images,
            body_support_dir,
            existing_observation=existing_observation,
            require_knee_observation=True,
            required_observation_fields=bso.body_support_discovery_observation_fields(
                contract),
            request_identity=bso.body_support_discovery_request_identity(contract),
        )
        evidence["bodySupportObservation"] = existing_observation
        refreshed = True
        steps.append("knee_support_observation")
        readiness = current_support_readiness()

    if (source_pose is not None
            and (not readiness.get("passed") or bool(evidence.get("footPatchEvidence")))):
        # The retained phase cache may have been classified with an older
        # foot-patch policy. Coarse readiness validates body support, not patch
        # policy/material freshness, so reclassify the exact selected cut
        # whenever the persisted patch is stale, independently of readiness.
        # This must happen before spending a GPU reconstruction attempt.
        from .source_support_tracking import FOOT_MATERIAL_POLICY_VERSION

        patch = evidence.get("footPatchEvidence") or {}
        if (patch.get("policyVersion") != fco.POLICY_VERSION
                or patch.get("materialStationarityPolicyVersion")
                != FOOT_MATERIAL_POLICY_VERSION):
            landmarks = fco.observe_foot_landmarks(selected_video)
            evidence = fco.add_observed_foot_contacts(
                evidence, landmarks, source_pose,
                source_video_path=selected_video,
            )
            refreshed = True
            steps.append("foot_patch_reclassification")
            readiness = current_support_readiness()

    timeline_status: str | None = None
    timeline_error: BaseException | None = None
    if (source_pose is not None
            and bso._contact_timeline_candidates(source_pose, evidence)):
        # The observer owns cache freshness; matching IDs alone cannot reuse
        # evidence from a different crop or reviewer. One bounded exact-cut
        # timeline can resolve patch ambiguity even when coarse readiness
        # passes. Persist its receipt before any later bake reloads the
        # retained source metrics.
        evidence_key = contact_timeline_repair_key(
            source_digest, source_pose_reference, evidence,
        )
        repair_marker_path = (
            candidate_workspace / "segment_detection"
            / "source_foot_contact_timeline_repair.json"
        )
        timeline_status = "observer_error"
        try:
            timeline = bso.observe_foot_contact_timeline(
                selected_video,
                source_pose_reference,
                evidence,
                caption_images,
                body_support_dir,
            )
            if isinstance(timeline, dict):
                if not isinstance(existing_observation, dict):
                    existing_observation = {
                        "status": "unknown",
                        "reason": "coarse_support_observation_unavailable",
                        "sourceVideoSha256": source_digest,
                    }
                existing_observation = dict(existing_observation)
                existing_observation["contactTimeline"] = timeline
                evidence["bodySupportObservation"] = existing_observation
                refreshed = True
                timeline_status = str(timeline.get("status") or "unknown")
                evidence = reclassify_source_foot_contacts_from_timeline(
                    evidence, timeline, selected_video, source_pose,
                )
                if persist_evidence:
                    if persist_fn(candidate_workspace, source_digest, evidence):
                        persisted = True
                        readiness = current_support_readiness()
                    else:
                        timeline_status = "persistence_unavailable"
        except Exception as exc:
            if is_storage_failure(exc):
                raise
            timeline_error = exc
        if write_repair_marker:
            marker = {
                "schemaVersion": 1,
                "policyVersion": bso.CONTACT_TIMELINE_POLICY_VERSION,
                "sourceVideoSha256": source_digest,
                "evidenceKey": evidence_key,
                "status": timeline_status,
                "attemptedAt": _utc_now(),
            }
            if timeline_error is not None:
                marker["errorType"] = type(timeline_error).__name__
                marker["error"] = str(timeline_error)[:1000]
            write_json_fn(repair_marker_path, marker)
        if timeline_error is not None:
            return _stage_result(
                evidence=evidence, readiness=readiness,
                contract_status=contract_status, refreshed=refreshed,
                persisted=persisted, steps=steps,
                timeline_status=timeline_status, timeline_error=timeline_error,
            )

    contract_status = contract_status_fn(
        contract, evidence, source_pose=source_pose,
        selected_video_path=selected_video,
    )
    legacy_followup_requirements = _unresolved_required_legacy_requirements(
        requirements, contract_status,
    )
    legacy_contact_regions = {"ankle", "foot", "knee", "hand", "pelvis", "upper_back", "head"}
    surface_review_requests = _body_surface_review_requests(requirements, discovery_hints)
    generic_requested = any(
        isinstance(item, dict) and item.get("region") not in legacy_contact_regions
        for disposition in _BODY_SURFACE_REVIEW_DISPOSITIONS
        for item in surface_review_requests.get(disposition, [])
    ) or bool(legacy_followup_requirements)
    generic_reviews = _generic_body_surface_review_records(
        surface_review_requests, selected_video, source_pose_reference,
        include_legacy_requirements=legacy_followup_requirements,
    ) if generic_requested and isinstance(source_pose_reference, dict) else []
    pose_reference_path, pose_reference_sha256 = (
        _pose_reference_receipt_from_workspace(candidate_workspace)
        if generic_reviews else (None, None)
    )
    if generic_requested and not isinstance(source_pose_reference, dict):
        evidence["bodySurfaceContactEvidence"] = {
            "schemaVersion": 1, "sourceVideoSha256": source_digest,
            "status": "insufficient_evidence", "reason": "verified_source_pose_unavailable",
            "sourceApproval": False, "geometryApproval": False, "reviews": [],
        }
        refreshed = True
        steps.append("generic_body_surface_review_unresolved")
    if generic_reviews:
        from .body_surface_evidence import (
            review_body_surface_contact_samples,
            verify_body_surface_contact_evidence,
        )

        cached_bundle = evidence.get("bodySurfaceContactEvidence")
        cached_reviews = (cached_bundle.get("reviews")
                          if isinstance(cached_bundle, dict) else None)
        cached_by_id = {
            item.get("contactId"): item for item in cached_reviews or []
            if isinstance(item, dict)
        }
        review_identity = bso._review_model_identity(caption_images)
        review_rows = []
        unresolved = False
        discovery_unresolved = False
        for review_request in generic_reviews:
            template = review_request["record"]
            cached = cached_by_id.get(template["contactId"])
            reviewed = None
            cached_record = cached.get("record") if isinstance(cached, dict) else None
            template_rows = template["sourceEvidence"]["observations"]
            cached_source = (cached_record.get("sourceEvidence")
                             if isinstance(cached_record, dict) else None)
            cached_rows = cached_source.get("observations") if isinstance(cached_source, dict) else None
            cached_matches_request = bool(
                isinstance(cached, dict)
                and cached.get("requirement") == review_request["requirement"]
                and isinstance(cached_record, dict)
                and isinstance(cached_source, dict)
                and cached_record.get("contactId") == template.get("contactId")
                and cached_record.get("bodyRegion") == template.get("bodyRegion")
                and cached_record.get("contactMode") == template.get("contactMode")
                and all(cached_source.get(key) == template["sourceEvidence"].get(key)
                        for key in ("sourceVideoSha256", "sourcePosePayloadSha256",
                                    "sourceFrameClockReceiptSha256"))
                and isinstance(cached_rows, list) and len(cached_rows) == len(template_rows)
                and all(all(cached_row.get(key) == template_row.get(key) for key in (
                    "sampleId", "sourceTimeSec", "sourcePoseFrameIndex", "sourceFrameIndex",
                    "sourceFps", "surfaceId"))
                    for cached_row, template_row in zip(cached_rows, template_rows))
            )
            if (isinstance(cached, dict)
                    and cached_matches_request
                    and isinstance(cached.get("record"), dict)
                    and isinstance(cached.get("receiptPath"), str)
                    and isinstance(cached.get("receiptSha256"), str)):
                try:
                    verified = verify_body_surface_contact_evidence(
                        cached["record"], selected_video, source_pose_reference,
                        review_receipt_path=cached["receiptPath"],
                        review_receipt_sha256=cached["receiptSha256"],
                        source_pose_reference_path=pose_reference_path,
                        source_pose_reference_sha256=pose_reference_sha256,
                    )
                    receipt = json.loads(Path(cached["receiptPath"]).read_text(encoding="utf-8"))
                    if caption_images is None or receipt.get("reviewIdentity") == review_identity:
                        reviewed = {**cached, "verifiedEvidence": verified}
                except (OSError, ValueError, TypeError):
                    reviewed = None
            if reviewed is None and caption_images is not None and review_identity:
                review_failure = None
                try:
                    reviewed = review_body_surface_contact_samples(
                        template, selected_video, source_pose_reference,
                        caption_images=caption_images,
                        receipt_directory=body_support_dir / "body-surface-reviews",
                        review_identity=review_identity,
                        source_pose_reference_path=pose_reference_path,
                        source_pose_reference_sha256=pose_reference_sha256,
                    )
                except Exception as exc:
                    if is_storage_failure(exc):
                        raise
                    review_failure = _safe_review_failure(exc)
                    reviewed = None
            else:
                review_failure = None
            if not isinstance(reviewed, dict):
                unresolved = True
                unresolved_row = {
                    "contactId": template["contactId"],
                    "requirement": review_request["requirement"],
                    "record": template, "status": "unresolved",
                    "reason": "visual_review_unavailable",
                }
                if review_failure is not None:
                    unresolved_row["failure"] = review_failure
                review_rows.append(unresolved_row)
                continue
            result = reviewed.get("verifiedEvidence") or {}
            coverage = result.get("coverage") or {}
            rows = result.get("samples") or []
            complete = (coverage.get("allCanonicalPoseFramesObserved") is True
                        and len(rows) == len(template["sourceEvidence"]["observations"])
                        and all(row.get("contactState") != "unknown" for row in rows))
            if not complete:
                if review_request["requirement"].get("disposition") == "discovery":
                    discovery_unresolved = True
                else:
                    unresolved = True
            review_rows.append({
                "contactId": template["contactId"],
                "requirement": review_request["requirement"],
                "record": reviewed.get("record"),
                "receiptPath": reviewed.get("receiptPath"),
                "receiptSha256": reviewed.get("receiptSha256"),
                "coverage": coverage,
                "status": "observed" if complete else "unresolved",
            })
        regional_status = "insufficient_evidence" if unresolved else "observed"
        regional_evidence = {
            "schemaVersion": 1,
            "sourceVideoSha256": source_digest,
            "status": regional_status,
            "sourceApproval": False,
            "geometryApproval": False,
            "reviews": review_rows,
        }
        if pose_reference_path is not None and pose_reference_sha256:
            regional_evidence["sourcePoseReferencePath"] = str(pose_reference_path)
            regional_evidence["sourcePoseReferenceSha256"] = pose_reference_sha256
        if caption_images is None and unresolved:
            # An unavailable refresh cannot replace a retained exact-source
            # receipt with a generated template or erase its adjudication ref.
            steps.append("generic_body_surface_review_unavailable_preserved_existing")
        else:
            evidence["bodySurfaceContactEvidence"] = regional_evidence
            if discovery_unresolved:
                evidence["bodySurfaceContactEvidence"]["discoveryStatus"] = "insufficient_evidence"
            refreshed = True
            steps.append("generic_body_surface_review")
            if persist_evidence:
                if persist_fn(candidate_workspace, source_digest, evidence):
                    persisted = True
                else:
                    evidence["bodySurfaceContactEvidence"]["status"] = "insufficient_evidence"
                    evidence["bodySurfaceContactEvidence"]["persistenceAvailable"] = False

    contract_status = contract_status_fn(
        contract, evidence, source_pose=source_pose,
        selected_video_path=selected_video,
    )
    if contract_status.get("status") == "contradicted":
        if refreshed and not persisted and persist_evidence:
            persisted = persist_fn(candidate_workspace, source_digest, evidence)
        return _stage_result(
            evidence=evidence, readiness=readiness,
            contract_status=contract_status, refreshed=refreshed,
            persisted=persisted, steps=steps, contradiction=True,
            timeline_status=timeline_status,
        )

    pending_foot_inference = _pending_required_foot_ground_material_inference(
        candidate_workspace, contract, evidence, readiness, selected_video,
        source_pose, source_pose_reference,
    )
    if pending_foot_inference:
        steps.append("required_foot_ground_material_inference_pending")
    if (refreshed and readiness.get("passed") and not persisted
            and persist_evidence):
        if persist_fn(candidate_workspace, source_digest, evidence):
            persisted = True
        else:
            readiness = _downgrade_for_persistence_failure(readiness)

    unresolved_ground_review = bool(
        readiness.get("passed")
        and source_pose_reference is not None
        and source_pose is not None
        and any(
            bso.source_sole_review_side_eligibility(
                evidence,
                source_pose_reference.get("pose") or {},
                side,
                ground_contact_mode=ground_contact_mode,
            ) == bso.UNRESOLVED_CONTINUOUS_GROUND_SOLE_REVIEW
            for side in ("left", "right")
        )
    )
    interval_review = None
    if ((not readiness.get("passed") or unresolved_ground_review)
            and not pending_foot_inference):
        # A coarse moving/unknown foot label over an unresolved patch can still
        # hide a real ground stance. Schedule one bounded native-frame review
        # only for that unresolved case, never for ordinary ready sources.
        interval_review = bso.observe_stationary_sole_intervals(
            selected_video,
            source_pose_reference,
            evidence,
            caption_images,
            stance_cache_dir,
            ground_contact_mode=ground_contact_mode,
        )
        if interval_review is not None:
            evidence["stationarySoleIntervalReview"] = interval_review
            dense_refresh = refresh_source_foot_contacts_from_dense_sole_review(
                evidence, selected_video, source_pose,
            )
            if dense_refresh is not None:
                evidence = dense_refresh
                refreshed = True
            review_persisted = (
                persist_fn(candidate_workspace, source_digest, evidence)
                if persist_evidence else False
            )
            persisted = persisted or review_persisted
            # Readiness must judge the same in-memory derivation even when
            # persistence failed; otherwise a negative material proof
            # discovered here would not block admission.
            readiness = current_support_readiness()
            if (refreshed and readiness.get("passed")
                    and not review_persisted and persist_evidence):
                readiness = _downgrade_for_persistence_failure(readiness)

    # Foot-interval evidence is independent of an unresolved body-region
    # requirement; do not short-circuit before the bounded review above.
    contract_status = contract_status_fn(
        contract, evidence, source_pose=source_pose,
        selected_video_path=selected_video,
    )
    if contract_status.get("status") == "contradicted":
        if refreshed and not persisted and persist_evidence:
            persisted = persist_fn(candidate_workspace, source_digest, evidence)
        return _stage_result(
            evidence=evidence, readiness=readiness,
            contract_status=contract_status, refreshed=refreshed,
            persisted=persisted, steps=steps, contradiction=True,
            timeline_status=timeline_status,
        )
    if contract_status.get("status") == "insufficient_evidence":
        if refreshed and not persisted and persist_evidence:
            persisted = persist_fn(candidate_workspace, source_digest, evidence)
        contract_pending = list(contract_status.get("pendingInferenceRequirements") or [])
        readiness_reasons = list(readiness.get("rejectionReasons") or [])
        stage_contract_pending = []
        for item in contract_pending:
            staged = dict(item) if isinstance(item, dict) else item
            requirement = staged.get("requirement") if isinstance(staged, dict) else None
            if (isinstance(requirement, dict)
                    and requirement.get("region") == "upper_back"
                    and "body_surface_contact_source_evidence_unavailable" in readiness_reasons):
                staged["accountsForReadinessReasons"] = [
                    "body_surface_contact_source_evidence_unavailable",
                ]
            stage_contract_pending.append(staged)
        pending_requirements = [*stage_contract_pending, *pending_foot_inference]
        contract_failures = list(contract_status.get("failures") or [])
        contract_failures_accounted = bool(contract_pending) and all(
            failure in {
                f"required_{item.get('requirement', {}).get('region')}_"
                f"{item.get('requirement', {}).get('side')}_support_unobserved"
                for item in contract_pending if isinstance(item, dict)
            }
            for failure in contract_failures
        )
        readiness_reasons_accounted = (
            readiness.get("passed") is True
            or (bool(pending_requirements) and bool(readiness_reasons)
                and all(reason in set(
                    account for item in pending_foot_inference
                    for account in item.get("accountsForReadinessReasons", [])
                ) | {
                    account for item in stage_contract_pending if isinstance(item, dict)
                    for account in item.get("accountsForReadinessReasons", [])
                } for reason in readiness_reasons))
        )
        pending_route = bool(pending_requirements and contract_failures_accounted
                             and readiness_reasons_accounted)
        return _stage_result(
            evidence=evidence, readiness=readiness,
            contract_status=contract_status, refreshed=refreshed,
            persisted=persisted, steps=steps, contract_insufficient=True,
            timeline_status=timeline_status,
            unresolved_ground_review=unresolved_ground_review,
            stationary_sole_review_attempted=interval_review is not None,
            reconstruction_only_pending_inference=pending_route,
            pending_inference_requirements=pending_requirements,
        )

    if (not readiness.get("passed")
            and evidence.get("stationarySoleIntervalReview")
            and refreshed and not persisted and persist_evidence):
        persisted = persist_fn(candidate_workspace, source_digest, evidence)

    return _stage_result(
        evidence=evidence, readiness=readiness,
        contract_status=contract_status, refreshed=refreshed,
        persisted=persisted, steps=steps,
        timeline_status=timeline_status,
        unresolved_ground_review=unresolved_ground_review,
        stationary_sole_review_attempted=interval_review is not None,
    )
