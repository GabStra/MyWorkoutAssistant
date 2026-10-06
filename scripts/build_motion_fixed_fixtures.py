"""Build a fixed fixture set for motion speed-harness A/B runs.

Pins a verified recommended candidate per exercise out of the retained
discovery output, records SHA-256 provenance for the source video, prepared
candidates file, exercise-motion contract, and quality references, and emits
a runner-compatible prepared-candidates manifest. Fresh arm workspaces are
seeded with exercise_plan.json only, so every arm starts from identical,
verified inputs instead of re-running discovery.

Usage:
  python scripts/build_motion_fixed_fixtures.py
  python scripts/build_motion_fixed_fixtures.py --exercise barbell-step-up=s564zFjF3nU=2e58bcbc-072b-5057-a5e0-09fa1e2374ff
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (slug, videoId, exerciseId, cached source MP4 file name)
DEFAULT_EXERCISES: tuple[tuple[str, str, str, str], ...] = (
    (
        "barbell-step-up",
        "s564zFjF3nU",
        "2e58bcbc-072b-5057-a5e0-09fa1e2374ff",
        "s564zFjF3nU-2291a862b53a.mp4",
    ),
    (
        "bench-step-up",
        "Xa_buzDE5AM",
        "ad47ab15-6ce3-5214-b1be-131394063a94",
        "Xa_buzDE5AM-927f5fc8c92c.mp4",
    ),
)

REFERENCE_SUFFIXES = (
    "_wear_skeleton.json",
    "_selected_preview.webm",
    "_selected_input.mp4",
)


def _posix(path: Path) -> str:
    return path.resolve().as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory_contents(directory: Path) -> str:
    """Hash file names and contents in a directory tree, independent of order."""
    if not directory.is_dir():
        raise SystemExit(f"Fixture directory missing: {directory}")
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        relative_path = path.relative_to(directory).as_posix().encode("utf-8")
        content_digest = bytes.fromhex(sha256_file(path))
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        digest.update(content_digest)
    return digest.hexdigest()


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def parse_exercise_spec(spec: str, source_cache_dir: Path) -> tuple[str, str, str, str]:
    """Parse slug=videoId=exerciseId[=cachedSourceFileName]."""
    parts = spec.split("=")
    if len(parts) not in (3, 4) or not all(parts[:3]):
        raise SystemExit(
            f"--exercise must be slug=videoId=exerciseId[=cachedSourceFileName], got: {spec}"
        )
    slug, video_id, exercise_id = parts[:3]
    if len(parts) == 4:
        return slug, video_id, exercise_id, parts[3]
    matches = sorted(source_cache_dir.glob(f"{video_id}-*.mp4"))
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one cached source MP4 for video {video_id} in "
            f"{source_cache_dir}, found {len(matches)}: {[m.name for m in matches]}"
        )
    return slug, video_id, exercise_id, matches[0].name


def find_recommended_candidate(
    full_candidates: dict, slug: str, video_id: str
) -> tuple[dict, dict]:
    """Return (candidate, exerciseEntry) for the pinned recommended candidate."""
    for entry in full_candidates.get("exercises") or []:
        for candidate in entry.get("candidates") or []:
            if candidate.get("videoId") != video_id:
                continue
            if candidate.get("status") != "recommended":
                break
            vision = candidate.get("visionPayload") or {}
            vision_score = candidate.get("visionScore")
            if vision.get("target_identity_match") or isinstance(vision_score, (int, float)):
                return candidate, entry
            break
    raise SystemExit(
        f"{slug}: no recommended candidate for video {video_id} with complete "
        f"identity evidence (target_identity_match or visionScore) in "
        f"selected/debug/youtube_candidates.full.json"
    )


def prepare_candidates_file(
    full_candidates: dict,
    slug: str,
    video_id: str,
    exercise_id: str,
    source_candidates_file: Path,
    destination: Path,
) -> None:
    """Pin the chosen candidate into a prepared candidates JSON.

    Deterministic: no wall-clock timestamps are written into the hashed file.
    """
    chosen, entry = find_recommended_candidate(full_candidates, slug, video_id)
    payload = json.loads(json.dumps(full_candidates))  # deep copy
    kept_entries = [e for e in payload.get("exercises") or [] if e.get("exerciseId") == exercise_id]
    if not kept_entries:
        raise SystemExit(
            f"{slug}: exerciseId {exercise_id} not found among candidates-file exercises"
        )
    for kept in kept_entries:
        kept["candidates"] = [json.loads(json.dumps(chosen))]
        debug = kept.get("debugCandidates")
        if isinstance(debug, list):
            trimmed = [d for d in debug if d.get("videoId") == video_id]
            if trimmed:
                kept["debugCandidates"] = trimmed
            else:
                kept.pop("debugCandidates", None)
    payload["exercises"] = kept_entries
    payload["preparedFixture"] = {
        "sourceCandidatesFile": _posix(source_candidates_file),
        "sourceGeneratedAt": full_candidates.get("generatedAt"),
        # Derived from the source snapshot so identical inputs yield identical
        # hashes; the fixture manifest carries the real wall-clock build time.
        "preparedAtUtc": full_candidates.get("generatedAt"),
        "expectedVideoId": video_id,
        "exerciseId": exercise_id,
    }
    write_json(destination, payload)


def resolve_contract(
    base_workspace: Path,
    slug: str,
    contract_cache_dir: Path,
    candidate: dict,
    destination: Path,
) -> tuple[Path, str]:
    """Copy the contract cache entry, or fall back to the embedded payload."""
    revalidation_path = base_workspace / slug / "selected" / "revalidation.json"
    revalidation = json.loads(revalidation_path.read_text(encoding="utf-8"))
    contract_sha = (revalidation.get("artifactIdentity") or {}).get("contractSha256")
    cache_file = (
        contract_cache_dir / f"{contract_sha}.json"
        if isinstance(contract_sha, str) and contract_sha
        else None
    )
    if cache_file is not None and cache_file.is_file():
        destination.write_bytes(cache_file.read_bytes())
    else:
        contract = (candidate.get("visionPayload") or {}).get("exerciseMotionContract")
        if not isinstance(contract, dict):
            cache_status = f"{contract_sha} not in cache" if contract_sha else "no cached contract identity"
            raise SystemExit(
                f"{slug}: {cache_status} and candidate has no "
                "visionPayload.exerciseMotionContract to fall back on"
            )
        write_json(destination, contract)
    return destination, sha256_file(destination)


def build_exercise_fixture(
    base_workspace: Path,
    source_cache_dir: Path,
    contract_cache_dir: Path,
    output_dir: Path,
    slug: str,
    video_id: str,
    exercise_id: str,
    source_file_name: str,
) -> dict:
    retained = base_workspace / slug
    selected = retained / "selected"
    if not retained.is_dir():
        raise SystemExit(f"Missing retained exercise workspace: {retained}")

    full_candidates_path = selected / "debug" / "youtube_candidates.full.json"
    if not full_candidates_path.is_file():
        raise SystemExit(f"Missing retained candidates file: {full_candidates_path}")
    full_candidates = json.loads(full_candidates_path.read_text(encoding="utf-8"))
    chosen, entry = find_recommended_candidate(full_candidates, slug, video_id)
    exercise_name = entry.get("exerciseName") or slug

    prepared_path = output_dir / "prepared" / slug / "youtube_candidates.json"
    prepare_candidates_file(
        full_candidates, slug, video_id, exercise_id, full_candidates_path, prepared_path
    )

    source_path = source_cache_dir / source_file_name
    if not source_path.is_file():
        raise SystemExit(f"Missing cached source MP4: {source_path}")

    contract_path = output_dir / "prepared" / slug / "contract.json"
    _, contract_sha = resolve_contract(
        base_workspace, slug, contract_cache_dir, chosen, contract_path
    )

    references: list[dict] = []
    prefix = slug.replace("-", "_")
    reference_names = [f"{prefix}{suffix}" for suffix in REFERENCE_SUFFIXES]
    reference_names += ["selection_manifest.json", "revalidation.json"]
    references_dir = output_dir / "references" / slug
    for name in reference_names:
        source = selected / name
        if not source.is_file():
            raise SystemExit(f"Missing quality reference: {source}")
        destination = references_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        references.append({"path": _posix(destination), "sha256": sha256_file(destination)})

    seed_source = retained / "exercise_plan.json"
    if not seed_source.is_file():
        raise SystemExit(f"Missing exercise plan: {seed_source}")
    seed_dir = output_dir / "workspaces" / slug
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_destination = seed_dir / "exercise_plan.json"
    shutil.copy2(seed_source, seed_destination)

    return {
        "slug": slug,
        "exerciseId": exercise_id,
        "exerciseName": exercise_name,
        "expectedVideoId": video_id,
        "sourceCachePath": _posix(source_path),
        "sourceSha256": sha256_file(source_path),
        "preparedCandidatesPath": _posix(prepared_path),
        "preparedCandidatesSha256": sha256_file(prepared_path),
        "contractPath": _posix(contract_path),
        "contractSha256": contract_sha,
        "workspaceSeedPath": _posix(seed_destination),
        "workspaceSeedSha256": sha256_file(seed_destination),
        "referenceFiles": references,
    }


def print_summary(exercises: list[dict]) -> None:
    print(f"{'slug':<20} {'videoId':<14} {'source sha256':<18} {'candidates sha256':<18} {'contract sha256':<18}")
    for exercise in exercises:
        print(
            f"{exercise['slug']:<20} {exercise['expectedVideoId']:<14} "
            f"{exercise['sourceSha256'][:16]:<18} {exercise['preparedCandidatesSha256'][:16]:<18} "
            f"{exercise['contractSha256'][:16]:<18}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "build/exercise_motion/speed-harness/fixtures/step-up-pair",
    )
    parser.add_argument(
        "--base-workspace",
        type=Path,
        default=REPO_ROOT / "build/exercise_motion/exercise-library",
    )
    parser.add_argument(
        "--source-cache-dir",
        type=Path,
        default=REPO_ROOT / "build/exercise_motion/youtube-source-cache",
    )
    parser.add_argument(
        "--contract-cache-dir",
        type=Path,
        default=REPO_ROOT / "build/exercise_motion/exercise-library/exercise-motion-contract-cache",
    )
    parser.add_argument(
        "--exercise",
        action="append",
        dest="exercise_specs",
        metavar="SLUG=VIDEOID=EXERCISEID[=CACHEFILENAME]",
        help="Exercise row to pin; repeats replace the default Step-Up pair",
    )
    args = parser.parse_args()

    if args.exercise_specs:
        rows = [parse_exercise_spec(spec, args.source_cache_dir) for spec in args.exercise_specs]
    else:
        rows = list(DEFAULT_EXERCISES)

    output_dir = args.output_dir
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise SystemExit(
            f"--output-dir already exists and was preserved: {output_dir}. "
            "Choose a new output directory for this fixture set."
        ) from exc

    contract_cache_snapshot = output_dir / "contract-cache"
    if args.contract_cache_dir.is_dir():
        shutil.copytree(args.contract_cache_dir, contract_cache_snapshot)
    else:
        contract_cache_snapshot.mkdir()
    contract_cache_sha256 = sha256_directory_contents(contract_cache_snapshot)

    exercises = [
        build_exercise_fixture(
            args.base_workspace, args.source_cache_dir, contract_cache_snapshot,
            output_dir, slug, video_id, exercise_id, source_file_name,
        )
        for slug, video_id, exercise_id, source_file_name in rows
    ]

    manifest_path = output_dir / "prepared_candidates_manifest.json"
    write_json(manifest_path, {
        "schemaVersion": 1,
        "kind": "prepared_exercise_candidates",
        "items": [
            {
                "exerciseId": exercise["exerciseId"],
                "exerciseName": exercise["exerciseName"],
                "exerciseSlug": exercise["slug"],
                "candidatesJson": exercise["preparedCandidatesPath"],
                "expectedVideoId": exercise["expectedVideoId"],
            }
            for exercise in exercises
        ],
    })

    fixture_manifest_path = output_dir / "fixture_manifest.json"
    write_json(fixture_manifest_path, {
        "schemaVersion": 1,
        "kind": "motion_fixed_fixture_set",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "exercises": exercises,
        "preparedCandidatesManifestPath": _posix(manifest_path),
        "workspaceSeedsRoot": _posix(output_dir / "workspaces"),
        "contractCacheSnapshotPath": _posix(contract_cache_snapshot),
        "contractCacheSnapshotSha256": contract_cache_sha256,
    })

    print_summary(exercises)
    print(f"\nfixture manifest: {fixture_manifest_path}")


if __name__ == "__main__":
    main()
