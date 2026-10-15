from workout_generator_pkg.domain_ops import format_equipment_for_conversation


def test_requirements_context_distinguishes_pair_single_and_barbell_load_limits():
    context = format_equipment_for_conversation({"equipments": [
        {"id": "pair", "name": "Pair", "type": "DUMBBELLS", "dumbbells": [{"weight": 25.0}]},
        {"id": "single", "name": "Single", "type": "DUMBBELL", "dumbbells": [{"weight": 25.0}]},
        {"id": "bar", "name": "Bar", "type": "BARBELL", "barWeight": 10.0, "plates": []},
    ]})

    assert "50.0kg combined = 25.0kg per hand" in context
    assert "Never double these totals" in context
    assert "25.0kg for one dumbbell" in context
    assert "10.0kg including the bar" in context
    assert "do not add bar weight again" in context
    assert "do not assume uniform increments" in context
