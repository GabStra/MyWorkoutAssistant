"""Repair only proven rigid-correction metadata mismatches; preserve motion bytes."""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exercise_motion_pkg.bake_and_rank import repair_selection_manifest_renderer_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--exercise", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.workspace.resolve()
    for name in args.exercise:
        path = (root / name / "bake" / "selection_manifest.json").resolve()
        if not path.is_relative_to(root):
            raise ValueError("Exercise path must stay within the workspace")
        if not path.exists():
            path = (root / name / "selected" / "selection_manifest.json").resolve()
            if not path.is_relative_to(root):
                raise ValueError("Selected path must stay within the workspace")
        if not path.exists():
            print(json.dumps({"exercise": name, "repairedEntries": 0, "status": "no_manifest"}))
            continue
        before = path.read_bytes()
        updated, count = repair_selection_manifest_renderer_metadata(json.loads(before))
        if count and args.apply:
            if path.read_bytes() != before:
                raise RuntimeError(f"Manifest changed concurrently: {path}")
            backup = path.with_name(f"selection_manifest.before-metadata-repair-{uuid.uuid4().hex}.json")
            backup.write_bytes(before)
            temporary = path.with_name(f"selection_manifest.repair-{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps(updated, indent=2), encoding="utf-8")
            temporary.replace(path)
        print(json.dumps({"exercise": name, "repairedEntries": count, "applied": args.apply and count > 0}))


if __name__ == "__main__":
    main()
