from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exercise_motion_pkg.chunking import estimate_chunking
from exercise_motion_pkg.llama_defaults import DEFAULT_LLAMA_CPP_MODEL


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate video-review chunk size and overlap for one exercise using llama.cpp with validated fallback logic."
    )
    parser.add_argument("exercise_name")
    parser.add_argument("--llama-cpp-base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--llama-cpp-model", default=DEFAULT_LLAMA_CPP_MODEL)
    parser.add_argument("--llama-cpp-request-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic hints/fallback only.")
    args = parser.parse_args()

    estimate = estimate_chunking(
        exercise_name=args.exercise_name,
        use_llm=not args.no_llm,
        llama_cpp_base_url=args.llama_cpp_base_url,
        llama_cpp_model=args.llama_cpp_model,
        llama_cpp_request_timeout_seconds=args.llama_cpp_request_timeout_seconds,
    )
    print(json.dumps(asdict(estimate), indent=2))


if __name__ == "__main__":
    main()
