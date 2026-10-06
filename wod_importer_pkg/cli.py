"""CLI: build the day's WOD package via the LLM generation stack.

No heuristic parsing anywhere. The flow:
  1. fetch the WOD text from the GymAutoBook dashboard
  2. setup step (one LLM call): given the whole WOD, the gym equipment catalog and
     the existing exercise names, decide which equipment and which exercises are
     missing; extend the catalog and create the missing definitions through the
     exercise library generator
  3. workout generation (LLM, strict library mode): the workout generator turns the
     WOD into the final workout, choosing set types itself (auto-countdowns for
     timed blocks, supersets for rounds)
  4. write workouts/wod_<date>.json for the phone import flow

  python -m wod_importer_pkg.cli 2026-10-06
  python -m wod_importer_pkg.cli 2026-10-06 --dry-run   # setup plan only, no generation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wod_importer_pkg.fetch import fetch_wod
from wod_importer_pkg.setup import plan_missing

DEFAULT_BASE_LIBRARY = Path("exercise_libraries/exercise_library_2026-08-17_164507_with_movements.json")
DEFAULT_ACCUMULATED_LIBRARY = Path("exercise_libraries/wod_accumulated_library.json")
DEFAULT_EQUIPMENT_FILE = Path(__file__).resolve().parent / "assets" / "gym_equipment.json"


def run(date_iso: str, entry, output: Path, base_library: Path, accumulated_library: Path,
        equipment_file: Path, skip_library_generation: bool, dry_run: bool) -> None:
    from wod_importer_pkg.generators import (
        ensure_definitions,
        generate_workout_package,
        load_working_library,
        make_deepseek_client,
        sanitize_package_name,
    )
    from wod_importer_pkg.setup import _default_llm_call, extend_equipment_catalog, plan_missing

    library, library_path = load_working_library(base_library, accumulated_library)
    with open(equipment_file, encoding="utf-8") as handle:
        catalog = json.load(handle)

    exercise_names = [d["name"] for d in library.get("exerciseDefinitions", [])]
    print("setup step: LLM decides missing equipment + exercises...")
    plan = plan_missing(
        make_deepseek_client(), entry.text, catalog, exercise_names,
        call=_default_llm_call,
    )
    print(f"  exercises to create: {plan['exercisesToCreate'] or 'nothing — all covered'}")
    print(f"  missing equipment:   {[i['name'] for i in plan['missingEquipment']] or 'none'}")
    if dry_run:
        return

    if plan["missingEquipment"]:
        catalog, added = extend_equipment_catalog(catalog, plan["missingEquipment"])
        equipment_file.parent.mkdir(parents=True, exist_ok=True)
        equipment_file.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        print(f"  catalog extended with: {[e['name'] for e in added]}")

    if plan["exercisesToCreate"] and not skip_library_generation:
        print("creating exercise definitions (LLM, scoped)...")
        library, created, _ = ensure_definitions(
            movement_names=plan["exercisesToCreate"],
            working_library=library,
            working_library_path=library_path,
            equipment_file=equipment_file,
        )
        print(f"  created: {created or 'nothing — merged as duplicates'}")

    print("generating workout (LLM, strict library mode — a couple of minutes)...")
    package = generate_workout_package(entry.text, library)
    package = sanitize_package_name(package, date_iso)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(package, indent=2), encoding="utf-8")
    print(f"wrote {output}")
    workout = package["workouts"][0]
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
    parser.add_argument("--base-library", type=Path, default=DEFAULT_BASE_LIBRARY)
    parser.add_argument("--accumulated-library", type=Path, default=DEFAULT_ACCUMULATED_LIBRARY)
    parser.add_argument("--equipment-file", type=Path, default=DEFAULT_EQUIPMENT_FILE)
    parser.add_argument("--skip-library-generation", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="setup plan only, no generation")
    args = parser.parse_args(argv)

    entry = fetch_wod(args.date)
    print(f"WOD {args.date} [{entry.wod_type or '?'}] {entry.title}")
    output = args.output or (Path("workouts") / f"wod_{args.date}.json")
    run(
        date_iso=args.date,
        entry=entry,
        output=output,
        base_library=args.base_library,
        accumulated_library=args.accumulated_library,
        equipment_file=args.equipment_file,
        skip_library_generation=args.skip_library_generation,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
