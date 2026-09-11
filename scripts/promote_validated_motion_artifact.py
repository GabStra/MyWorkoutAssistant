"""Promote an exactly revalidated artifact and retain the previous selection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from exercise_motion_pkg.acceptance import promote_verified_artifact
from exercise_motion_pkg.bake_and_rank import FINAL_OUTPUT_VALIDATION_POLICY_VERSION, SELECTION_VALIDATION_POLICY_VERSION
from exercise_motion_pkg.preview import preview_runtime_signature


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--context-json", type=Path, help="Exact exercise context used for revalidation")
    parser.add_argument("--contract-json", type=Path, help="Exact resolved contract used for revalidation")
    args = parser.parse_args()
    backup = promote_verified_artifact(
        args.source, args.destination,
        policies={"selection": SELECTION_VALIDATION_POLICY_VERSION,
                  "visual": FINAL_OUTPUT_VALIDATION_POLICY_VERSION, "renderer": preview_runtime_signature()},
        context=json.loads(args.context_json.read_text(encoding="utf-8")) if args.context_json else None,
        contract=json.loads(args.contract_json.read_text(encoding="utf-8")) if args.contract_json else None,
    )
    print(json.dumps({"promoted": str(args.destination.resolve()), "backup": str(backup) if backup else None}))


if __name__ == "__main__":
    main()
