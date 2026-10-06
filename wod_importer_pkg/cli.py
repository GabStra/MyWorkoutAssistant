"""CLI: build the day's WOD package.

Usage:
  python -m wod_importer_pkg.cli 2026-10-06 [-o out.json] [--library path.json]
  python -m wod_importer_pkg.cli 2026-10-06 --all-entries   (emit every board entry)

Fetches from the GymAutoBook dashboard (must run on the PC hosting it), parses,
maps against the exercise library, and writes a WorkoutPlanPackage JSON ready for
the phone import flow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wod_importer_pkg.build import build_package
from wod_importer_pkg.fetch import fetch_wod, fetch_wod_window
from wod_importer_pkg.mapping import DEFAULT_LIBRARY, MovementMapper
from wod_importer_pkg.parse import parse_wod


def build_for_date(date_iso: str, library_path: Path, entry_index: int | None = None) -> tuple[Path, dict, list[str]]:
    if entry_index is None:
        entry = fetch_wod(date_iso)
        entries = [(entry.title, entry.wod_type, entry.text)]
    else:
        window = fetch_wod_window(date_iso)
        entries_in_day = window.get(date_iso) or []
        if not entries_in_day:
            raise RuntimeError(f"No WOD published for {date_iso}")
        chosen = entries_in_day[min(entry_index, len(entries_in_day) - 1)]
        entries = [(chosen.title, chosen.wod_type, chosen.text)]

    mapper = MovementMapper(library_path=library_path)
    last_output = None
    unparsed: list[str] = []
    for index, (title, wod_type, text) in enumerate(entries):
        ir = parse_wod(text, date=date_iso, title=title, wod_type=wod_type)
        unparsed.extend(ir.unparsed)
        package = build_package(ir, mapper)
        suffix = f"_{index}" if index else ""
        out = Path("workouts") / f"wod_{date_iso}{suffix}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(package, indent=2), encoding="utf-8")
        last_output = out
    return last_output, package, unparsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wod-importer")
    parser.add_argument("date", help="YYYY-MM-DD")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--all-entries", action="store_true", help="emit every board entry for the date")
    parser.add_argument("--dry-run", action="store_true", help="print a summary, write nothing")
    args = parser.parse_args(argv)

    entry = fetch_wod(args.date)
    ir = parse_wod(entry.text, date=args.date, title=entry.title, wod_type=entry.wod_type)
    mapper = MovementMapper(library_path=args.library)
    package = build_package(ir, mapper)

    workout = package["workouts"][0]
    print(f"WOD {args.date} [{entry.wod_type or '?'}] {entry.title}")
    for block in ir.blocks:
        movements = ", ".join(
            f"{m.reps or ('max' if m.max_effort else '?')}"
            f"{'' if m.unit == 'reps' else m.unit} {m.name}"
            for m in block.movements
        )
        print(f"  {block.kind:7s} rounds={block.rounds} min={block.minutes} cap={block.cap_min} :: {movements}")
    print("  workout components:")
    for component in workout["workoutComponents"]:
        label = component["name"] if component["type"] == "Exercise" else f"Superset({len(component['exercises'])})"
        print(f"    {component['type']:8s} {label}")
    created_defs = [d["name"] for d in package["exerciseDefinitions"]]
    created_eq = [e["name"] for e in package["equipments"]]
    print(f"  new definitions: {created_defs or 'none'}")
    print(f"  new equipment:   {created_eq or 'none'}")
    if ir.unparsed:
        print(f"  UNPARSED: {ir.unparsed}")

    if args.dry_run:
        return 0
    output = args.output or (Path("workouts") / f"wod_{args.date}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(package, indent=2), encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
