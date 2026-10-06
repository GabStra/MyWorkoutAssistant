"""Re-eligible previously discovery-rejected YouTube candidates for bake.

Same-workspace library resumes never re-attempt candidates whose discovery
review set ``status: "rejected"`` in ``youtube_candidates.json``: the bake
wave only accepts ``recommended`` candidates, so a rejected candidate is
permanently stuck even after pipeline fixes change the outcome. Bake-stage
rejections are different — the candidate stays ``recommended`` and every new
round re-attempts it automatically.

This script flips discovery rejections back to ``recommended`` so the next
library run re-reviews and re-bakes them under the current code. The original
status is preserved in ``sourceDiscoveryStatus`` for auditability, mirroring
``mark_ranked_candidate_as_bake_fallback``. Candidates rejected because the
video shows the wrong exercise or equipment (``visionPayload
.target_identity_match is False``) stay rejected: no pipeline fix can make a
wrong video usable, and the identity guard requires that verdict to stay
honest.

Usage:
    python scripts/reset_exercise_motion_candidate_rejections.py --dry-run
    python scripts/reset_exercise_motion_candidate_rejections.py
    python scripts/reset_exercise_motion_candidate_rejections.py \
        --exercise-slug barbell-bulgarian-split-squat
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_WORKSPACE_ROOT = Path("build/exercise_motion/exercise-library")


def reset_candidate(candidate: dict) -> bool:
    """Flip one discovery rejection back to recommended; True when changed."""
    if str(candidate.get("status") or "").strip().casefold() != "rejected":
        return False
    vision_payload = candidate.get("visionPayload")
    if isinstance(vision_payload, dict) and vision_payload.get("target_identity_match") is False:
        return False
    # Preserve the original verdict under the same convention the bake
    # fallback path uses, so the reset stays auditable in the artifact.
    candidate.setdefault("sourceDiscoveryStatus", "rejected")
    candidate["status"] = "recommended"
    return True


def reset_manifest(path: Path, *, dry_run: bool) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    reset_count = 0
    identity_kept = 0
    for exercise in payload.get("exercises") or []:
        for candidate in exercise.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("status") or "").casefold() != "rejected":
                continue
            vision_payload = candidate.get("visionPayload")
            if (
                isinstance(vision_payload, dict)
                and vision_payload.get("target_identity_match") is False
            ):
                identity_kept += 1
                continue
            reset_count += 1
            if not dry_run:
                reset_candidate(candidate)
    if not dry_run and reset_count:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"reset": reset_count, "identityKept": identity_kept}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=DEFAULT_WORKSPACE_ROOT,
        help="Exercise library workspace (default: %(default)s)",
    )
    parser.add_argument(
        "--exercise-slug",
        action="append",
        default=[],
        help="Restrict to these exercise slugs (repeatable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing files",
    )
    args = parser.parse_args()

    workspace_root = args.workspace_root
    if not workspace_root.is_dir():
        parser.error(f"workspace root not found: {workspace_root}")

    totals = {"reset": 0, "identityKept": 0, "exercises": 0}
    slug_filter = {slug.strip().casefold() for slug in args.exercise_slug}
    for manifest_path in sorted(workspace_root.glob("*/youtube_candidates.json")):
        slug = manifest_path.parent.name
        if slug_filter and slug.casefold() not in slug_filter:
            continue
        try:
            counts = reset_manifest(manifest_path, dry_run=args.dry_run)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"SKIP {slug}: {exc}")
            continue
        if counts["reset"] or counts["identityKept"]:
            totals["exercises"] += 1
            totals["reset"] += counts["reset"]
            totals["identityKept"] += counts["identityKept"]
            mode = "would reset" if args.dry_run else "reset"
            print(
                f"{slug}: {mode} {counts['reset']} candidate(s); "
                f"{counts['identityKept']} kept rejected (wrong exercise/equipment)"
            )
    scope = "would reset" if args.dry_run else "reset"
    print(
        f"Total: {scope} {totals['reset']} candidate(s) across "
        f"{totals['exercises']} exercise(s); {totals['identityKept']} kept rejected"
    )
    if not args.dry_run and totals["reset"]:
        print("Restart the library run to re-review and re-bake these candidates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
