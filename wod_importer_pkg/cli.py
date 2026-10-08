"""CLI: turn a workout description into a MyWorkoutAssistant plan package.

Works for ANY workout text - a gym WOD, a strength session, a circuit, a Hyrox
simulation. The flow:
  1. get the workout text (GymAutoBook fetch by date, or pass it directly)
  2. setup: one LLM call decides which equipment and which movements are missing;
     missing equipment extends the catalog, missing movements are created through
     the exercise library generator
  3. workout generation (LLM, strict library mode): the generator chooses set
     types itself. Two styles:
       hands-free (default) - timed blocks auto-advance, AMRAPs/rounds become
         tap-through supersets; nothing is entered mid-workout
       standard - a regular plan; you enter weights/reps as usual
  4. write the plan package JSON for the phone import flow

  python -m wod_importer_pkg.cli 2026-10-06                     # gym WOD of the day
  python -m wod_importer_pkg.cli --text-file session.txt --name "Push Day"
  python -m wod_importer_pkg.cli --text "5x5 bench press @ 80kg" --style standard
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from wod_importer_pkg.fetch import fetch_wod

DEFAULT_BASE_LIBRARY = Path("exercise_libraries/exercise_library_2026-08-17_164507_with_movements.json")
DEFAULT_ACCUMULATED_LIBRARY = Path("exercise_libraries/wod_accumulated_library.json")
DEFAULT_EQUIPMENT_FILE = Path(__file__).resolve().parent / "assets" / "gym_equipment.json"


def run(date_iso: str, workout_text: str, output: Path, base_library: Path, accumulated_library: Path,
        equipment_file: Path, skip_library_generation: bool, dry_run: bool,
        style: str, explicit_name: str | None) -> None:
    from wod_importer_pkg.generators import (
        backfill_equipment_from_catalog,
        ensure_wod_coverage,
        generate_workout_package,
        guidance_for_style,
        load_working_library,
        make_deepseek_client,
        review_crossfit_mode_compliance,
        sanitize_package_name,
    )
    from wod_importer_pkg.setup import _default_llm_call, extend_equipment_catalog, plan_missing_equipment

    library, library_path = load_working_library(base_library, accumulated_library)
    with open(equipment_file, encoding="utf-8") as handle:
        catalog = json.load(handle)
    client = make_deepseek_client()

    # 0) running support: the library has no RUNNING definitions and the exercise
    #    generator cannot create them; guarantee the canonical 'Run' entry so
    #    stated runs become real GPS-tracked running exercises.
    from wod_importer_pkg.generators import ensure_running_definition
    if ensure_running_definition(library, library_path):
        print("  added RUNNING 'Run' definition to the working library")

    # 1) exercise coverage first: the exercise generator's audit reads the workout
    #    with the library as existing inventory and creates what's missing - or a
    #    more appropriate version when the existing entry is a poor match.
    if skip_library_generation:
        print("skipping exercise coverage (--skip-library-generation)")
    else:
        print("coverage pass: exercise generator audit creates missing/improved definitions...")
        library, created = ensure_wod_coverage(
            client=client,
            workout_text=workout_text,
            working_library=library,
            working_library_path=library_path,
            equipment_file=equipment_file,
        )
        print(f"  created/improved: {created or 'nothing — all covered'}")

    # 2) equipment for those exercises: deterministic catalog check for everything the
    #    library references, plus the LLM equipment pass on the text as catch-all.
    referenced_equipment_ids = {
        d["equipmentId"] for d in library.get("exerciseDefinitions", []) if d.get("equipmentId")
    }
    referenced_equipment_ids |= {
        accessory_id
        for d in library.get("exerciseDefinitions", [])
        for accessory_id in d.get("requiredAccessoryEquipmentIds", [])
    }
    catalog_equipment_ids = {e["id"] for e in catalog.get("equipments", [])} | {
        a["id"] for a in catalog.get("accessoryEquipments", [])
    }
    unmet_ids = referenced_equipment_ids - catalog_equipment_ids
    if unmet_ids:
        unmet_names = [
            d["name"] for d in library.get("exerciseDefinitions", [])
            if d.get("equipmentId") in unmet_ids
            or any(a in unmet_ids for a in d.get("requiredAccessoryEquipmentIds", []))
        ]
        print(f"  equipment gap for: {unmet_names} - extending catalog via LLM")
    missing_equipment = plan_missing_equipment(client, workout_text, catalog, call=_default_llm_call)
    if unmet_ids or missing_equipment:
        catalog, added = extend_equipment_catalog(catalog, missing_equipment)
        equipment_file.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        print(f"  catalog extended with: {[e['name'] for e in added] or list(unmet_ids)}")
    else:
        print("  equipment: catalog covers everything")

    # 3) workout generation - the catalog is the equipment source of truth (it
    #    supersets everything the library references).
    if dry_run:
        print("dry run: skipping workout generation")
        return
    library["equipments"] = catalog["equipments"]
    library["accessoryEquipments"] = catalog["accessoryEquipments"]
    guidance = guidance_for_style(style)
    print(f"generating workout (LLM, strict library mode, style={style} — a couple of minutes)...")
    package = generate_workout_package(
        workout_text,
        library,
        guidance=guidance,
    )

    # 4) compliance review: one cheap LLM audit of the encoding rules against the
    #    text (caps, cadence, cardio targets, nothing dropped), with a single
    #    corrective regeneration when it finds violations.
    issues = review_crossfit_mode_compliance(client, workout_text, package)
    if issues:
        print(f"  compliance review found {len(issues)} issue(s); regenerating once with fixes:")
        for issue in issues:
            print(f"    - {issue}")
        package = generate_workout_package(
            workout_text,
            library,
            guidance=guidance,
            corrective_context="\n".join(f"- {issue}" for issue in issues),
        )
    else:
        print("  compliance review: ok")

    package = sanitize_package_name(package, date_iso, explicit_name)
    # the workout generator emits only plan-declared equipment; the catalog is the
    # complete superset, so backfill any definition-referenced gear it dropped.
    backfilled = backfill_equipment_from_catalog(package, catalog)
    if backfilled:
        print(f"  equipment backfilled from catalog: {backfilled}")

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
    parser = argparse.ArgumentParser(prog="workout-importer")
    parser.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (gym WOD fetch; optional)")
    parser.add_argument("--text-file", type=Path, default=None, help="workout text file (any workout)")
    parser.add_argument("--text", default=None, help="workout text inline")
    parser.add_argument("--name", default=None, help="plan name (defaults to the LLM's choice)")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--base-library", type=Path, default=DEFAULT_BASE_LIBRARY)
    parser.add_argument("--accumulated-library", type=Path, default=DEFAULT_ACCUMULATED_LIBRARY)
    parser.add_argument("--equipment-file", type=Path, default=DEFAULT_EQUIPMENT_FILE)
    parser.add_argument("--style", choices=["hands-free", "standard"], default="hands-free",
                        help="hands-free: nothing entered mid-workout (WOD style); "
                             "standard: regular plan, enter weights/reps as usual")
    parser.add_argument("--skip-library-generation", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="setup plan only, no generation")
    args = parser.parse_args(argv)

    if args.text_file and args.text:
        parser.error("use --text-file or --text, not both")
    if args.text_file:
        workout_text = args.text_file.read_text(encoding="utf-8").strip()
    elif args.text:
        workout_text = args.text.strip()
    else:
        if not args.date:
            parser.error("provide a date (gym WOD fetch) or --text-file/--text")
        workout_text = fetch_wod(args.date).text
    date_iso = args.date or date.today().isoformat()

    print(f"workout [{date_iso}] ({len(workout_text)} chars)")
    output = args.output
    if output is None:
        if args.date:
            # Daily-WOD runs keep the canonical gate-tracked name.
            output = Path("workouts") / f"wod_{args.date}.json"
        else:
            from wod_importer_pkg.generators import _normalize
            slug_source = args.name or workout_text
            output = Path("workouts") / f"workout_{_normalize(slug_source)[:60] or 'import'}.json"
    run(
        date_iso=date_iso,
        workout_text=workout_text,
        output=output,
        base_library=args.base_library,
        accumulated_library=args.accumulated_library,
        equipment_file=args.equipment_file,
        skip_library_generation=args.skip_library_generation,
        dry_run=args.dry_run,
        style=args.style,
        explicit_name=args.name,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
