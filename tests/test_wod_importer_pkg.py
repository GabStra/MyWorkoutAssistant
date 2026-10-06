"""Parser and builder tests against the gym's real WOD texts (2026-09-30 .. 10-06).

These are the actual published texts fetched from the GymAutoBoard dashboard;
they are the regression corpus for the heuristic parser. Assertions focus on
scheme detection and complete consumption of movement lines, not on cosmetic
parsing details.
"""

from wod_importer_pkg.build import build_package
from wod_importer_pkg.mapping import MovementMapper, stable_id
from wod_importer_pkg.parse import parse_wod

REAL_WODS = {
    "2026-09-30": (
        "For Time",
        "Strength & Gymnastics\nEmom 10' \n1) Deadlift 6 rep @ 75 % of 1 rm\n2) kipping pull ups 5-10 rep\n"
        "WOD\n4 rounds for time: \n12 one DB devil press @ 22.5/15 \n8 box jumps\n6 bar muscle ups",
    ),
    "2026-10-01": (
        "For Time",
        "HYROX PREP \n4 intervals, 6' ON : 1' OFF\n alternate:\nA) Amrap of:\n200mt run \n15 wall ball \n"
        "20 mt burpees broad jumps \n\nB) Amrap of:\n10 mt sled push @ 150/100 \n10 strict pull ups \n16 alt. lunges @ 20/10",
    ),
    "2026-10-02": (
        "For Time",
        "8 Intervals – 2' ON / 2' OFF\n\nA\n•\t15 Deadlift @60/45 kg\n•\t4 Wall Walks\n•\tMax Effort Double Unders\n\n"
        "B\n•\t16 Alt. DB Snatch @22.5/15 kg\n•\t12 Push Ups\n•\tMax Effort Power Clean @60/45 kg",
    ),
    "2026-10-03": (
        "For Time",
        "WOD\n10 rounds for time of:\nAlt. between:\n24/20 cal row - 150 mt farmers carry @ 2x32/20\nthen:\n"
        "12 toes to bar / toes to KB\n6 burpees box jump overs\n*time cap 25'",
    ),
    "2026-10-04": (
        "For Time",
        "WOD\nIn team of 2, complete:\n1200 mt run\n100 synchro air squat\n800 mt run\n80 synchro walkin lunges\n"
        "600 mt run\n60 synchro med ball sit ups\n400 mt run\n40 synchro push ups\n600 mt run\n20 synchro wall ball\n"
        "800 mt run\n*time cap 35'",
    ),
    "2026-10-05": (
        "For Time",
        "LIFTING CLUB\nFor time\nIn 12' time cap, perform: \n30 burpees \n40 toes to bar \n30 burpees  \n"
        "2' rest, then - 10' to find a heavy push jerk/split jerk",
    ),
    "2026-10-06": (
        "EMOM",
        "HYROX PREP\nFrom 0-4'\nmax mt row (target 1100/1000) \nFrom 4'-8' \nmax cal bike erg/AB - 1' standing + 1' seated \n"
        "From 8'-12'\nAmrap of:\n20 gtoh plate + 20 mt shuttle run \n*no rest and repeat",
    ),
}


def parse_day(day: str):
    wod_type, text = REAL_WODS[day]
    return parse_wod(text, date=day, title="WOD", wod_type=wod_type)


def _all_movements(ir):
    return [movement for block in ir.blocks for movement in block.movements]


def test_sep30_emom_then_rft():
    ir = parse_day("2026-09-30")
    kinds = [block.kind for block in ir.blocks]
    assert "emom" in kinds and "rft" in kinds
    emom = next(block for block in ir.blocks if block.kind == "emom")
    assert emom.minutes == 10 and len(emom.movements) == 2
    rft = next(block for block in ir.blocks if block.kind == "rft")
    assert rft.rounds == 4 and len(rft.movements) == 3
    devil = rft.movements[0]
    assert devil.reps == 12 and devil.weight_hint and devil.weight_hint.startswith("22.5")
    assert not ir.unparsed, ir.unparsed


def test_oct01_intervals_with_two_amraps():
    ir = parse_day("2026-10-01")
    amraps = [block for block in ir.blocks if block.kind == "amrap"]
    assert len(amraps) == 2, ir.blocks
    assert {block.label for block in amraps} == {"A", "B"}
    first_movements = [movement.name for movement in amraps[0].movements]
    assert any("run" in name.lower() for name in first_movements)
    assert any("wall" in name.lower() for name in first_movements)
    assert not ir.unparsed, ir.unparsed


def test_oct02_intervals_ab_chipper():
    ir = parse_day("2026-10-02")
    movements = _all_movements(ir)
    names = [movement.name.lower() for movement in movements]
    assert any("deadlift" in name for name in names)
    assert any("double under" in name or "under" in name for name in names)
    assert any("push up" in name.replace("-", " ") for name in names)
    max_efforts = [movement for movement in movements if movement.max_effort]
    assert len(max_efforts) >= 2
    assert not ir.unparsed, ir.unparsed


def test_oct03_rft_with_then_and_cap():
    ir = parse_day("2026-10-03")
    rft = next(block for block in ir.blocks if block.kind == "rft")
    assert rft.rounds == 10
    row = rft.movements[0]
    assert row.unit == "cal" and row.reps == 24
    assert any("farmer" in movement.name.lower() for movement in rft.movements)
    # "then:" section lands as its own chipper block carrying the whole-workout cap
    follow_up = ir.blocks[-1]
    assert follow_up is not rft and follow_up.kind == "chipper"
    assert follow_up.cap_min == 25
    all_names = " ".join(movement.name.lower() for movement in _all_movements(ir))
    assert "toes to" in all_names and "box jump" in all_names
    assert not ir.unparsed, ir.unparsed


def test_oct04_team_chipper_cap():
    ir = parse_day("2026-10-04")
    movements = _all_movements(ir)
    assert len(movements) == 11
    runs = [movement for movement in movements if movement.unit == "m"]
    assert len(runs) == 6
    assert ir.blocks[0].cap_min == 35
    assert not ir.unparsed, ir.unparsed


def test_oct05_chipper_with_rest_and_strength():
    ir = parse_day("2026-10-05")
    kinds = [block.kind for block in ir.blocks]
    assert "chipper" in kinds
    rests = [movement for movement in _all_movements(ir) if movement.rest_seconds]
    assert rests and rests[0].rest_seconds == 120
    heavy = [movement for movement in _all_movements(ir) if movement.max_effort]
    assert heavy and "jerk" in heavy[0].name.lower()
    assert not ir.unparsed, ir.unparsed


def test_oct06_timed_blocks_and_amrap():
    ir = parse_day("2026-10-06")
    timed = [block for block in ir.blocks if block.kind == "timed"]
    assert len(timed) == 2  # the third window becomes the AMRAP block
    assert [block.minutes for block in timed] == [4, 4]
    assert timed[0].movements[0].max_effort and timed[0].movements[0].unit == "m"
    bike = timed[1].movements[0]
    assert bike.sub_splits_seconds == [60, 60]
    amrap = next(block for block in ir.blocks if block.kind == "amrap")
    assert amrap.cap_min == 4  # inherited from the 8'-12' window
    assert len(amrap.movements) == 2  # compound "+" line split
    assert amrap.movements[0].reps == 20 and amrap.movements[1].unit == "m"
    assert not ir.unparsed, ir.unparsed


def test_build_today_package_structure_and_stable_ids():
    mapper = MovementMapper(library_path=None)  # no library: everything auto-created
    ir = parse_day("2026-10-06")
    ir.date = "2026-10-06"
    package = build_package(ir, mapper)

    workout = package["workouts"][0]
    components = workout["workoutComponents"]
    assert [c["type"] for c in components] == ["Exercise", "Exercise", "Superset"]
    rowing, bike, amrap = components
    assert rowing["sets"][0]["timeInMillis"] == 240_000
    assert len(bike["sets"]) == 2 and bike["sets"][0]["timeInMillis"] == 60_000
    assert all(s["autoStart"] and s["autoStop"] for s in rowing["sets"] + bike["sets"])
    assert len(amrap["exercises"]) == 2
    assert {len(e["sets"]) for e in amrap["exercises"]} == {len(amrap["exercises"][0]["sets"])}

    # every referenced definition/equipment id is present in the package
    definition_ids = {d["id"] for d in package["exerciseDefinitions"]}
    equipment_ids = {e["id"] for e in package["equipments"]}

    def walk(components):
        for component in components:
            if component["type"] == "Superset":
                walk(component["exercises"])
            else:
                yield component

    for exercise in walk(components):
        assert exercise["exerciseDefinitionId"] in definition_ids
        if exercise["equipmentId"] is not None:
            assert exercise["equipmentId"] in equipment_ids

    # determinism: rebuilding yields identical ids
    mapper2 = MovementMapper(library_path=None)
    ir2 = parse_day("2026-10-06")
    ir2.date = "2026-10-06"
    package2 = build_package(ir2, mapper2)
    assert package2["workouts"][0]["id"] == workout["id"]
    assert {d["id"] for d in package2["exerciseDefinitions"]} == definition_ids


def test_synonym_matching_prefers_existing_library_definitions():
    mapper = MovementMapper(library_path=None)
    mapper.definitions_by_name = {
        "barbelldeadlift": {"id": "d1", "name": "Barbell Deadlift", "exerciseType": "WEIGHT",
                            "equipmentId": "e1", "bodyWeightPercentage": None,
                            "requiredAccessoryEquipmentIds": [], "muscleGroups": [],
                            "secondaryMuscleGroups": [], "exerciseCategory": None},
        "powerclean": {"id": "d2", "name": "Power Clean", "exerciseType": "WEIGHT",
                       "equipmentId": "e1", "bodyWeightPercentage": None,
                       "requiredAccessoryEquipmentIds": [], "muscleGroups": [],
                       "secondaryMuscleGroups": [], "exerciseCategory": None},
    }
    deadlift = mapper.resolve("15 Deadlift", "60/45 kg")
    assert deadlift.definition["id"] == "d1"
    assert deadlift.source in ("synonym", "library")  # prefers the existing library variant
    clean = mapper.resolve("Max Effort Power Clean", "60/45 kg")
    assert clean.definition["id"] == "d2"
    burpee = mapper.resolve("burpees", None)
    assert burpee.definition["name"] == "Burpee" and burpee.definition["exerciseType"] == "BODY_WEIGHT"


def test_ensure_definitions_merges_generated_and_skips_when_covered(tmp_path):
    from wod_importer_pkg.generators import ensure_definitions

    working = {
        "exerciseDefinitions": [_def("d-existing", "Deadlift")],
        "equipments": [_eq("e1", "Barbell")],
        "exerciseMovements": [{"movementRef": {"movementId": "m1"}}],
    }
    library_path = tmp_path / "accumulated.json"

    calls = []

    def fake_generation(client, equipment_file, request, max_definitions):
        calls.append(request)
        assert "Wall Ball" in request and "Deadlift" not in request
        return {
            "exerciseDefinitions": [
                _def("d-new", "Wall Ball"),
                _def("d-existing", "Deadlift"),  # duplicate: must be skipped
            ],
            "equipments": [_eq("e1", "Barbell"), _eq("e2", "Medicine Ball")],
        }

    library, created, _skipped = ensure_definitions(
        movement_names=["Deadlift", "Wall Ball"],
        working_library=working,
        working_library_path=library_path,
        equipment_file=tmp_path / "equipment.json",
        make_client=lambda: object(),
        generate_library=fake_generation,
    )

    names = [d["name"] for d in library["exerciseDefinitions"]]
    assert names == ["Deadlift", "Wall Ball"]
    assert created == ["Wall Ball"]
    assert len(calls) == 1
    assert library["exerciseMovements"] == working["exerciseMovements"]  # sidecar preserved
    assert {e["id"] for e in library["equipments"]} == {"e1", "e2"}
    assert library_path.exists()  # accumulated sidecar written

    # second run: everything covered -> no generation call at all
    calls.clear()
    library2, created2, _ = ensure_definitions(
        movement_names=["Deadlift", "Wall Ball"],
        working_library=library,
        working_library_path=library_path,
        equipment_file=tmp_path / "equipment.json",
        make_client=lambda: object(),
        generate_library=fake_generation,
    )
    assert created2 == [] and calls == []
    assert library2["exerciseDefinitions"][0]["id"] == "d-existing"


def _def(id_, name):
    return {"id": id_, "name": name, "exerciseType": "BODY_WEIGHT", "equipmentId": None,
            "bodyWeightPercentage": None, "requiredAccessoryEquipmentIds": [],
            "muscleGroups": [], "secondaryMuscleGroups": [], "exerciseCategory": None}


def _eq(id_, name):
    return {"id": id_, "type": "GENERIC", "name": name}


def test_stable_id_determinism():
    assert stable_id("definition", "Burpee") == stable_id("definition", "Burpee")
    assert stable_id("definition", "Burpee") != stable_id("equipment", "Burpee")
