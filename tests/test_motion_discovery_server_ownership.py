import pytest
import threading
from types import SimpleNamespace

from exercise_motion_pkg import youtube


@pytest.mark.parametrize("shared", [False, True])
def test_discovery_startup_only_stops_a_standalone_server(tmp_path, monkeypatch, shared):
    stopped = []
    monkeypatch.setattr(youtube, "load_workout_plan_exercises", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        youtube, "stop_llama_cpp_servers_for_base_url",
        lambda *args, **kwargs: stopped.append(args[0]),
    )
    youtube.discover_and_rank_youtube_candidates(
        workout_plan_json=tmp_path / "plan.json",
        out_json=tmp_path / "candidates.json",
        settings=youtube.YouTubeRankingSettings(
            pose_prefilter_enabled=True,
            llama_cpp_auto_start_server=True,
            llama_cpp_shared_server=shared,
            llama_cpp_base_url="http://127.0.0.1:8090",
            rank_with_vision=False,
            exercise_name_rewrite_enabled=False,
            exercise_motion_contract_enabled=False,
        ),
    )
    assert stopped == ([] if shared else ["http://127.0.0.1:8090"])


def test_shared_client_recovery_waits_for_supervisor_without_killing_server(monkeypatch):
    ranker = object.__new__(youtube.LlamaCppVisionRanker)
    ranker.settings = SimpleNamespace(llama_cpp_shared_server=True)
    ranker._server_recovery_lock = threading.Lock()
    ranker._server_models_payload = lambda: None
    recovered = []
    ranker._ensure_server = lambda: recovered.append(True)
    monkeypatch.setattr(youtube, "stop_llama_cpp_servers_for_base_url", lambda *args, **kwargs: pytest.fail("Shared client killed supervisor server"))
    ranker._recover_llama_cpp_server_after_vlm_failure()
    assert recovered == [True]
