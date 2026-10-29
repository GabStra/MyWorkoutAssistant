"""Small Python-owned cursor writer for the PowerShell movement runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .source_turn_budget import write_source_turn_cursor_from_wave_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave-state-json", required=True)
    parser.add_argument("--exercise-plan-json", required=True)
    parser.add_argument("--cursor-path", required=True)
    parser.add_argument("--source-review-turn-id", required=True)
    parser.add_argument(
        "--transition", required=True,
        choices=("next_source_candidate", "bounded_source_discovery"),
    )
    args = parser.parse_args(argv)
    try:
        wave_state = json.loads(Path(args.wave_state_json).read_text(encoding="utf-8-sig"))
        cursor = write_source_turn_cursor_from_wave_state(
            args.cursor_path,
            wave_state=wave_state,
            exercise_plan_path=args.exercise_plan_json,
            source_review_turn_id=args.source_review_turn_id,
            transition=args.transition,
        )
    except (OSError, ValueError, TypeError) as exc:
        print(f"Could not persist source-turn cursor: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "cursorPath": str(Path(args.cursor_path)),
        "exerciseId": cursor["cursorExerciseId"],
        "sourceReviewTurnId": cursor["sourceReviewTurnId"],
        "nextCandidateKey": cursor["nextCandidateKey"],
        "attemptedCandidateCount": len(cursor["attemptedCandidateKeys"]),
        "transition": cursor["cursorTransition"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
