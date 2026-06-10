from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exercise_motion_pkg.chunking import DEFAULT_MODEL, estimate_chunking, find_default_litert_command


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate video-review chunk size and overlap for one exercise using LiteRT-LM with validated fallback logic."
    )
    parser.add_argument("exercise_name")
    parser.add_argument("--litert-command", default=find_default_litert_command())
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--backend", default="gpu", choices=("cpu", "gpu", "npu"))
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic hints/fallback only.")
    args = parser.parse_args()

    estimate = estimate_chunking(
        exercise_name=args.exercise_name,
        litert_command=args.litert_command,
        model=args.model,
        backend=args.backend,
        use_llm=not args.no_llm,
    )
    print(json.dumps(asdict(estimate), indent=2))


if __name__ == "__main__":
    main()
