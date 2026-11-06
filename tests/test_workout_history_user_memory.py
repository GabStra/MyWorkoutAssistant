from __future__ import annotations

import asyncio
import json
from pathlib import Path

from test_workout_history_mcp import fixture_backup
from workout_history_mcp.server import _user_memory, _with_store_dict, create_mcp
from workout_history_mcp.loader import load_store
from workout_user_memory import bind_history, capture_scope, create_profile, record_fact


def store_with_backup(tmp_path: Path):
    path = tmp_path / "backup.json"
    path.write_text(json.dumps(fixture_backup()), encoding="utf-8")
    return path, load_store(path)


def test_unbound_history_does_not_guess_or_expose_profiles(monkeypatch, tmp_path: Path):
    path, store = store_with_backup(tmp_path)
    monkeypatch.setenv("MYWORKOUT_BACKUP_PATH", str(path))
    monkeypatch.setenv("MYWORKOUT_USER_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.delenv("MYWORKOUT_PROFILE_ID", raising=False)

    result = _with_store_dict(lambda loaded: _user_memory(loaded), label="get_user_memory")

    assert result == {"configured": False, "facts": [], "unavailableFacts": []}


def test_bound_profile_returns_kind_filtered_facts(monkeypatch, tmp_path: Path):
    path, store = store_with_backup(tmp_path)
    root = tmp_path / "memory"
    monkeypatch.setenv("MYWORKOUT_BACKUP_PATH", str(path))
    monkeypatch.setenv("MYWORKOUT_USER_MEMORY_DIR", str(root))
    monkeypatch.delenv("MYWORKOUT_PROFILE_ID", raising=False)
    profile = create_profile("Test profile", root)
    bind_history(profile["profileId"], path, root)
    record_fact(
        profile["profileId"],
        kind="standing_preference",
        value="Use a pause",
        source={"role": "user", "statement": "I prefer a pause."},
        root=root,
    )
    record_fact(
        profile["profileId"],
        kind="standing_restriction",
        value="Avoid overhead work",
        source={"role": "user", "statement": "Avoid overhead work."},
        root=root,
    )
    record_fact(
        profile["profileId"],
        kind="shared_station",
        value=["44444444-4444-4444-4444-444444444444", "55555555-5555-5555-5555-555555555555"],
        source={"role": "user", "statement": "These can share a station."},
        scope=capture_scope(
            store.workout_store,
            ["44444444-4444-4444-4444-444444444444", "55555555-5555-5555-5555-555555555555"],
        ),
        root=root,
    )

    all_memory = _with_store_dict(lambda loaded: _user_memory(loaded), label="get_user_memory")
    result = _with_store_dict(lambda loaded: _user_memory(loaded, "standing_preference"), label="get_user_memory")

    assert result["configured"] is True
    assert result["profileId"] == profile["profileId"]
    assert [fact["value"] for fact in result["facts"]] == ["Use a pause"]
    assert result["unavailableFacts"] == []
    assert len(all_memory["facts"]) == 3
    assert all_memory["unavailableFacts"] == []


def test_explicit_profile_conflicting_with_binding_is_a_structured_failure(monkeypatch, tmp_path: Path):
    path, store = store_with_backup(tmp_path)
    root = tmp_path / "memory"
    monkeypatch.setenv("MYWORKOUT_BACKUP_PATH", str(path))
    monkeypatch.setenv("MYWORKOUT_USER_MEMORY_DIR", str(root))
    bound = create_profile("Bound profile", root)
    selected = create_profile("Other profile", root)
    bind_history(bound["profileId"], path, root)
    monkeypatch.setenv("MYWORKOUT_PROFILE_ID", selected["profileId"])

    result = _with_store_dict(lambda loaded: _user_memory(loaded), label="get_user_memory")

    assert result["ok"] is False
    assert "conflicts with this history file binding" in result["error"]


def test_server_registers_read_only_user_memory_tool_and_resource():
    mcp = create_mcp()

    tools = {tool.name for tool in asyncio.run(mcp.list_tools())}
    resources = {str(resource.uri) for resource in asyncio.run(mcp.list_resources())}

    assert "get_user_memory" in tools
    assert "workout-history://user-memory" in resources
    assert not any("set_user_memory" in name for name in tools)
