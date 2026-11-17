from __future__ import annotations

import json
from pathlib import Path

from exercise_motion_pkg import bake_and_rank as bake


def test_target_blind_equipment_check_accepts_explicit_nonwaived_station_requirement(
    tmp_path: Path, monkeypatch
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"review frame placeholder")
    cache = tmp_path / "target_blind_equipment_observation.json"
    # An older default-name result must not satisfy a differently projected
    # requirement, even if its first required item happens to match.
    cache.write_text(json.dumps({
        "schemaVersion": 1,
        "policyVersion": bake.PRE_RECONSTRUCTION_EQUIPMENT_OBSERVATION_POLICY_VERSION,
        "requiredEquipment": "pull up station",
        "passed": False,
    }), encoding="utf-8")
    monkeypatch.setattr(
        bake, "prepare_pre_reconstruction_equipment_observation_frames",
        lambda _paths, *, output_dir: [frame],
    )
    captured: dict[str, object] = {}

    def fake_call(_caption_images, **kwargs):
        captured.update(kwargs)
        return '{"visibleEquipment":["pull up station"],"evidence":"A bar supports the hands."}'

    monkeypatch.setattr(bake, "call_caption_images_json", fake_call)
    result = bake.confirm_pre_reconstruction_named_equipment(
        exercise_name="Weighted Vest Pull-Up",
        frame_paths=[frame],
        caption_images=lambda **_kwargs: "unused",
        cache_path=cache,
        request_timeout_seconds=1.0,
        required_equipment_names=["Pull-Up Station"],
    )

    assert result["passed"] is True
    assert result["requiredEquipmentNames"] == ["pull up station"]
    assert result["visibleEquipment"] == ["pull up station"]
    assert "Weighted Vest Pull-Up" not in str(captured["prompt"])
    assert "Pull-Up Station" not in str(captured["prompt"])
    assert "fixed bar" in str(captured["prompt"])
    assert "fixed bar support" in str(captured["prompt"])
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["requiredEquipmentNames"] == ["pull up station"]


def test_target_blind_equipment_check_keeps_default_bodyweight_skip(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(bake, "two_scale_named_equipment", lambda _name: "none")

    def should_not_call(*_args, **_kwargs):
        raise AssertionError("bodyweight check should not call the vision model")

    monkeypatch.setattr(bake, "call_caption_images_json", should_not_call)
    result = bake.confirm_pre_reconstruction_named_equipment(
        exercise_name="Bodyweight Pull-Up",
        frame_paths=[],
        caption_images=lambda **_kwargs: "unused",
        cache_path=tmp_path / "target_blind_equipment_observation.json",
        request_timeout_seconds=1.0,
    )

    assert result["passed"] is True
    assert result["requiredEquipment"] == "none"


def test_explicit_target_blind_cache_misses_when_ordered_frame_bytes_change(
    tmp_path: Path, monkeypatch
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"first source image")
    cache = tmp_path / "target_blind_equipment_observation.json"
    monkeypatch.setattr(
        bake, "prepare_pre_reconstruction_equipment_observation_frames",
        lambda _paths, *, output_dir: [frame],
    )
    calls = 0

    def fake_call(_caption_images, **_kwargs):
        nonlocal calls
        calls += 1
        return '{"visibleEquipment":["pull up station"],"evidence":"A bar supports the hands."}'

    monkeypatch.setattr(bake, "call_caption_images_json", fake_call)
    kwargs = dict(
        exercise_name="Weighted Vest Pull-Up",
        frame_paths=[frame], caption_images=lambda **_kwargs: "unused",
        cache_path=cache, request_timeout_seconds=1.0,
        required_equipment_names=["Pull-Up Station"],
    )
    first = bake.confirm_pre_reconstruction_named_equipment(**kwargs)
    assert first["passed"] is True
    assert calls == 1

    frame.write_bytes(b"different exact source image")
    second = bake.confirm_pre_reconstruction_named_equipment(**kwargs)
    assert second["passed"] is True
    assert calls == 2


def test_fixed_pullup_bar_aliases_remain_distinct_from_barbell() -> None:
    for alias in (
        "fixed bar",
        "fixed support bar",
        "fixed bar station",
        "pull-up bar",
        "chin-up bar",
        "pull-up station",
        "chin-up station",
    ):
        assert bake.normalize_observed_equipment_name(alias) == "pull up station"

    assert bake.normalize_observed_equipment_name("barbell") == "barbell"
    assert not bake.equipment_names_are_motion_equivalent("Pull-Up Station", "barbell")
