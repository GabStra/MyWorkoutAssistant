"""CLI: build the day's WOD package via the LLM generation stack.

Default flow (requires DEEPSEEK_API_KEY, minutes of LLM time):
  1. fetch the WOD text from the GymAutoBook dashboard
  2. parse it; check which movements the exercise library is missing
  3. exercise_library_generator creates ONLY the missing definitions (scoped LLM run,
     merged into exercise_libraries/wod_accumulated_library.json, idempotent)
  4. workout_generator builds the final workout in strict library mode — the LLM
     chooses the set types (auto-countdowns for timed blocks, supersets for rounds)
  5. write workouts/wod_<date>.json for the phone import flow

  python -m wod_importer_pkg.cli 2026-10-06
  python -m wod_importer_pkg.cli 2026-10-06 --offline   # heuristic path, no API
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wod_importer_pkg.build import build_package
from wod_importer_pkg.fetch import fetch_wod
from wod_importer_pkg.generators import movement_names
from wod_importer_pkg.mapping import MovementMapper
from wod_importer_pkg.parse import parse_wod


def _print_ir_summary(ir) -> None:
    for block in ir.blocks:
        movements = ", ".join(
            f"{m.reps or ('max' if m.max_effort else '?')}"
            f"{'' if m.unit == 'reps' else m.unit} {m.name}"
            for m in block.movements
        )
        print(f"  {block.kind:7s} rounds={block.rounds} min={block.minutes} cap={block.cap_min} :: {movements}")
    if ir.unparsed:
        print(f"  UNPARSED: {ir.unparsed}")


def run_offline(date_iso: str, entry, output: Path) -> None:
    ir = parse_wod(entry.text, date=date_iso, title=entry.title, wod_type=entry.wod_type)
    package = build_package(ir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(package, indent=2), encoding="utf-8")
    print(f"[offline] wrote {output} (heuristic encoding)")


def run_llm(
    date_iso: str,
    entry,
    output: Path,
    base_library: Path,
    accumulated_library: Path,
    equipment_file: Path,
    skip_library_generation: bool,
) -> None:
    from wod_importer_pkg.generators import (
        ensure_definitions,
        generate_workout_package,
        load_working_library,
        sanitize_package_name,
    )

    ir = parse_wod(entry.text, date=date_iso, title=entry.title, wod_type=entry.wod_type)
    names = movement_names(ir)
    print(f"movements: {names}")

    library, library_path = load_working_library(base_library, accumulated_library)
    if skip_library_generation:
        print("skipping exercise-definition generation (--skip-library-generation)")
    else:
        print("ensuring exercise definitions (LLM, scoped)...")
        library, created, _ = ensure_definitions(
            movement_names=names,
            working_library=library,
            working_library_path=library_path,
            equipment_file=equipment_file,
        )
        print(f"  created: {created or 'nothing — all covered'}")

    print("generating workout (LLM, strict library mode — several minutes)...")
    package = generate_workout_package(entry.text, library)
    package = sanitize_package_name(package, date_iso)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(package, indent=2), encoding="utf-8")
    workout = package["workouts"][0]
    print(f"wrote {output}")
    print(f"  plan: {package.get('name')}")
    for component in workout.get("workoutComponents", []):
        if component["type"] == "Exercise":
            sets = ", ".join(s["type"] for s in component.get("sets", []))
            print(f"    Exercise {component['name']} [{sets}]")
        elif component["type"] == "Superset":
            print(f"    Superset({len(component['exercises'])})")
        else:
            print(f"    {component['type']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wod-importer")
    parser.add_argument("date", help="YYYY-MM-DD")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--base-library", type=Path, default=Path("exercise_libraries/exercise_library_2026-08-17_164507_with_movements.json"))
    parser.add_argument("--accumulated-library", type=Path, default=Path("exercise_libraries/wod_accumulated_library.json"))
    parser.add_argument("--equipment-file", type=Path, default=Path(__file__).resolve().parent / "assets" / "gym_equipment.json")
    parser.add_argument("--offline", action="store_true", help="heuristic path: no LLM, no API key needed")
    parser.add_argument("--skip-library-generation", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the parse summary only")
    args = parser.parse_args(argv)

    entry = fetch_wod(args.date)
    ir = parse_wod(entry.text, date=args.date, title=entry.title, wod_type=entry.wod_type)
    print(f"WOD {args.date} [{entry.wod_type or '?'}] {entry.title}")
    _print_ir_summary(ir)
    if args.dry_run:
        return 0

    output = args.output or (Path("workouts") / f"wod_{args.date}.json")
    if args.offline:
        run_offline(args.date, entry, output)
    else:
        run_llm(
            date_iso=args.date,
            entry=entry,
            output=output,
            base_library=args.base_library,
            accumulated_library=args.accumulated_library,
            equipment_file=args.equipment_file,
            skip_library_generation=args.skip_library_generation,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
