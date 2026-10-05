import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from exercise_motion_pkg.staged_wave_service import (
    ADMISSION_LOCK_VERSION,
    ADMISSION_MUTEX_NAME,
    _queue_admission_mutex_name,
    _queue_admission_mutex_names,
    _prune_staged_wave_records,
    run_staged_wave_service,
)


def test_windows_admission_mutex_is_queue_scoped_with_legacy_worker_fallback(tmp_path):
    first_root = tmp_path / "workspace-one" / "staged-wave-services" / "v1"
    second_root = tmp_path / "workspace-two" / "staged-wave-services" / "v1"

    assert _queue_admission_mutex_name(first_root) != _queue_admission_mutex_name(second_root)
    assert _queue_admission_mutex_name(first_root) == _queue_admission_mutex_name(
        Path(str(first_root).swapcase())
    )
    assert _queue_admission_mutex_names(
        first_root,
        include_legacy_compatibility=False,
    ) == [_queue_admission_mutex_name(first_root)]

    first_root.mkdir(parents=True)
    state_path = first_root / "worker_state.json"
    state_path.write_text(json.dumps({"schemaVersion": 1}), encoding="utf-8")
    assert _queue_admission_mutex_names(
        first_root,
        include_legacy_compatibility=True,
    ) == [ADMISSION_MUTEX_NAME]

    state_path.write_text(
        json.dumps({"schemaVersion": 1, "admissionLockVersion": ADMISSION_LOCK_VERSION}),
        encoding="utf-8",
    )
    assert _queue_admission_mutex_names(
        first_root,
        include_legacy_compatibility=True,
    ) == [ADMISSION_MUTEX_NAME, _queue_admission_mutex_name(first_root)]


def test_idle_shutdown_rechecks_requests_after_producer_wins_admission_lock(
    tmp_path: Path,
    monkeypatch,
):
    from contextlib import contextmanager

    from exercise_motion_pkg import staged_wave_service

    queue_root = tmp_path / "queue"
    requests = queue_root / "requests"
    requests.mkdir(parents=True)
    service_reached_idle_lock = threading.Event()
    producer_published = threading.Event()
    executed = []
    result = {}
    real_admission_lock = staged_wave_service.staged_wave_admission_lock

    @contextmanager
    def pause_service_before_admission_lock(root):
        service_reached_idle_lock.set()
        assert producer_published.wait(timeout=2)
        with real_admission_lock(root):
            yield

    monkeypatch.setattr(
        staged_wave_service,
        "staged_wave_admission_lock",
        pause_service_before_admission_lock,
    )

    def run_service():
        result["processed"] = run_staged_wave_service(
            queue_root,
            execute_wave=lambda request: executed.append(request["waveId"]) or {},
            poll_interval_seconds=0.005,
            idle_timeout_seconds=0.03,
        )

    service_thread = threading.Thread(target=run_service)
    service_thread.start()
    try:
        assert service_reached_idle_lock.wait(timeout=2)
        request_id = "arrived-at-idle-boundary"
        request_path = requests / f"{request_id}.json"
        with real_admission_lock(queue_root):
            request_path.write_text(
                json.dumps(
                    {
                        "requestId": request_id,
                        "runId": "run-at-idle-boundary",
                        "waveId": "run-at-idle-boundary-wave-0001",
                    }
                ),
                encoding="utf-8",
            )
        producer_published.set()
        service_thread.join(timeout=3)
        assert not service_thread.is_alive()
    finally:
        producer_published.set()
        if service_thread.is_alive():
            (queue_root / "stop.request").write_text("test cleanup", encoding="utf-8")
            service_thread.join(timeout=3)

    request_id = "arrived-at-idle-boundary"
    result_path = queue_root / "results" / f"{request_id}.json"
    assert result["processed"] == 1
    assert executed == ["run-at-idle-boundary-wave-0001"]
    assert result_path.is_file()
    assert json.loads(result_path.read_text(encoding="utf-8"))["exitCode"] == 0
    assert not (requests / f"{request_id}.json").exists()
    worker_state = json.loads((queue_root / "worker_state.json").read_text(encoding="utf-8"))
    assert worker_state["status"] == "stopped"
    assert worker_state["admissionLockVersion"] == ADMISSION_LOCK_VERSION


def test_queue_service_processes_wave_request_and_stops_after_drain(tmp_path: Path):
    queue_root = tmp_path / "queue"
    requests = queue_root / "requests"
    results = queue_root / "results"
    requests.mkdir(parents=True)
    response = {}

    def execute_wave(request):
        response["waveId"] = request["waveId"]
        return {"reportPath": request["reportPath"]}

    result = {}

    def run_service():
        result["processed"] = run_staged_wave_service(
            queue_root,
            execute_wave=execute_wave,
            poll_interval_seconds=0.01,
            source_identity_fingerprint="source-v1",
            service_configuration_fingerprint="runtime-config-v1",
        )

    service_thread = threading.Thread(target=run_service)
    service_thread.start()
    state_path = queue_root / "worker_state.json"
    deadline = time.monotonic() + 2
    while not state_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert state_path.exists()

    request = {
        "waveId": "run-wave-0001",
        "sourceIdentityFingerprint": "source-v1",
        "serviceConfigurationFingerprint": "runtime-config-v1",
        "arguments": ["bake-and-rank", "--staged-wave-manifest", "manifest.json"],
        "reportPath": str(tmp_path / "wave" / "staged_wave_report.json"),
    }
    (requests / "run-wave-0001.json").write_text(json.dumps(request), encoding="utf-8")
    result_path = results / "run-wave-0001.json"
    deadline = time.monotonic() + 2
    while not result_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert result_path.exists()
    service_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert service_state["pid"] > 0
    assert service_state["status"] in {"idle", "running"}
    assert service_state["sourceIdentityFingerprint"] == "source-v1"
    assert service_state["serviceConfigurationFingerprint"] == "runtime-config-v1"
    assert response["waveId"] == "run-wave-0001"
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["exitCode"] == 0
    assert result_payload["reportPath"] == request["reportPath"]

    (queue_root / "stop.request").write_text("stop after queued work drains", encoding="utf-8")
    service_thread.join(timeout=2)
    assert not service_thread.is_alive()
    assert result["processed"] == 1
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "stopped"


def test_queue_service_orders_requests_by_enqueue_time_not_request_id(tmp_path: Path):
    queue_root = tmp_path / "queue"
    requests = queue_root / "requests"
    requests.mkdir(parents=True)
    for request_id, wave_id, enqueued_at in (
        ("aaa-later", "wave-later", 200),
        ("zzz-earlier", "wave-earlier", 100),
    ):
        (requests / f"{request_id}.json").write_text(
            json.dumps(
                {
                    "requestId": request_id,
                    "waveId": wave_id,
                    "enqueuedAtUnixNs": enqueued_at,
                }
            ),
            encoding="utf-8",
        )

    processed_wave_ids = []
    processed = run_staged_wave_service(
        queue_root,
        execute_wave=lambda request: processed_wave_ids.append(request["waveId"]) or {},
        poll_interval_seconds=0.01,
        idle_timeout_seconds=0.05,
    )

    assert processed == 2
    assert processed_wave_ids == ["wave-earlier", "wave-later"]


def test_queue_service_rejects_requests_from_a_different_source_identity(tmp_path: Path):
    queue_root = tmp_path / "queue"
    requests = queue_root / "requests"
    requests.mkdir(parents=True)
    request = {
        "requestId": "request-old-source",
        "runId": "run-old-source",
        "waveId": "run-old-source-wave-0001",
        "sourceIdentityFingerprint": "old-source",
    }
    (requests / "request-old-source.json").write_text(json.dumps(request), encoding="utf-8")
    executed = []
    result = {}

    def run_service():
        result["processed"] = run_staged_wave_service(
            queue_root,
            execute_wave=lambda payload: executed.append(payload["requestId"]) or {},
            poll_interval_seconds=0.01,
            source_identity_fingerprint="current-source",
        )

    service_thread = threading.Thread(target=run_service)
    service_thread.start()
    result_path = queue_root / "results" / "request-old-source.json"
    deadline = time.monotonic() + 2
    while not result_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert result_path.exists()
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["exitCode"] == 1
    assert "source identity" in result_payload["error"]
    assert executed == []

    (queue_root / "stop.request").write_text("test shutdown", encoding="utf-8")
    service_thread.join(timeout=2)
    assert not service_thread.is_alive()
    assert result["processed"] == 1


def test_queue_service_rejects_requests_from_a_different_runtime_configuration(
    tmp_path: Path,
):
    queue_root = tmp_path / "queue"
    requests = queue_root / "requests"
    requests.mkdir(parents=True)
    request = {
        "requestId": "request-old-configuration",
        "runId": "run-old-configuration",
        "waveId": "run-old-configuration-wave-0001",
        "sourceIdentityFingerprint": "current-source",
        "serviceConfigurationFingerprint": "old-runtime-config",
    }
    (requests / "request-old-configuration.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    executed = []
    result = {}

    def run_service():
        result["processed"] = run_staged_wave_service(
            queue_root,
            execute_wave=lambda payload: executed.append(payload["requestId"]) or {},
            poll_interval_seconds=0.01,
            source_identity_fingerprint="current-source",
            service_configuration_fingerprint="current-runtime-config",
        )

    service_thread = threading.Thread(target=run_service)
    service_thread.start()
    result_path = queue_root / "results" / "request-old-configuration.json"
    deadline = time.monotonic() + 2
    while not result_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert result_path.exists()
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["exitCode"] == 1
    assert "runtime configuration" in result_payload["error"]
    assert executed == []

    (queue_root / "stop.request").write_text("test shutdown", encoding="utf-8")
    service_thread.join(timeout=2)
    assert not service_thread.is_alive()
    assert result["processed"] == 1


def test_service_dispatches_manifest_arguments_through_the_cli_wave_entrypoint(
    tmp_path: Path,
    monkeypatch,
):
    from exercise_motion_pkg import cli
    from exercise_motion_pkg.staged_wave_service import _execute_wave_request

    manifest_path = tmp_path / "wave_manifest.json"
    wave_workspace = tmp_path / "wave"
    manifest_path.write_text(
        json.dumps({"waveId": "wave-a", "workspace": str(wave_workspace), "items": []}),
        encoding="utf-8",
    )
    captured = {}

    def fake_run(args, *, progress, render_executor):
        captured["command"] = args.command
        captured["manifest"] = args.staged_wave_manifest
        captured["progress"] = progress
        captured["render_executor"] = render_executor
        return {"waveId": "wave-a"}

    monkeypatch.setattr(cli, "run_staged_bake_wave_manifest", fake_run)
    render_executor = object()
    result = _execute_wave_request(
        {
            "arguments": [
                "bake-and-rank",
                "--candidates-json", str(tmp_path / "candidates.json"),
                "--wham-repo-path", str(tmp_path / "wham"),
                "--body-model-root", str(tmp_path / "body-models"),
                "--workspace", str(tmp_path / "workspace"),
                "--staged-wave-manifest", str(manifest_path),
            ],
        },
        render_executor=render_executor,
    )

    assert captured["command"] == "bake-and-rank"
    assert captured["manifest"] == manifest_path
    assert callable(captured["progress"])
    assert captured["render_executor"] is render_executor
    assert result["reportPath"] == str((wave_workspace / "staged_wave_report.json").resolve())
    assert result["report"] == {"waveId": "wave-a"}


@pytest.mark.parametrize(
    ("invalid_item", "expected_error"),
    [
        (None, "item at index 1 must be an object"),
        ({"workspace": "item-workspace"}, "requires a non-empty 'candidatesJson' path"),
        ({"candidatesJson": "candidates.json"}, "requires a non-empty 'workspace' path"),
    ],
)
def test_cli_rejects_invalid_wave_items_before_starting_wave(
    tmp_path: Path,
    monkeypatch,
    invalid_item,
    expected_error: str,
):
    from exercise_motion_pkg import cli

    manifest_path = tmp_path / "wave_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "waveId": "wave-invalid",
                "items": [
                    {"candidatesJson": "valid-candidates.json", "workspace": "valid-workspace"},
                    invalid_item,
                ],
            }
        ),
        encoding="utf-8",
    )
    wave_started = False

    def unexpected_wave_start(*args, **kwargs):
        nonlocal wave_started
        wave_started = True
        raise AssertionError("invalid manifest started the staged wave")

    monkeypatch.setattr(cli, "run_staged_bake_wave", unexpected_wave_start)
    with pytest.raises(ValueError, match=expected_error):
        cli.run_staged_bake_wave_manifest(
            SimpleNamespace(staged_wave_manifest=manifest_path),
            request=object(),
        )

    assert not wave_started


def test_queue_service_retains_ambiguous_processing_request_without_replaying(tmp_path: Path):
    queue_root = tmp_path / "queue"
    processing = queue_root / "processing"
    processing.mkdir(parents=True)
    request = {
        "schemaVersion": 1,
        "requestId": "request-recovered",
        "runId": "run-recovered",
        "waveId": "run-recovered-wave-0001",
        "reportPath": str(tmp_path / "report.json"),
    }
    (processing / "request-recovered.json").write_text(json.dumps(request), encoding="utf-8")
    executed = []

    def execute_wave(payload):
        executed.append(payload["requestId"])
        return {"reportPath": payload["reportPath"]}

    result = {}

    def run_service():
        result["processed"] = run_staged_wave_service(
            queue_root,
            execute_wave=execute_wave,
            poll_interval_seconds=0.01,
        )

    service_thread = threading.Thread(target=run_service)
    service_thread.start()
    result_path = queue_root / "results" / "request-recovered.json"
    deadline = time.monotonic() + 2
    while not result_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["requestId"] == "request-recovered"
    assert payload["waveId"] == "run-recovered-wave-0001"
    assert payload["exitCode"] == 76
    assert payload["status"] == "ambiguous_recovery"
    assert "not replayed" in payload["error"]
    assert executed == []
    assert (queue_root / "ambiguous" / "request-recovered.json").is_file()

    (queue_root / "stop.request").write_text("test shutdown", encoding="utf-8")
    service_thread.join(timeout=2)
    assert not service_thread.is_alive()
    assert result["processed"] == 0


def test_queue_service_os_lease_prevents_a_second_in_process_owner(tmp_path: Path):
    queue_root = tmp_path / "queue"
    service_thread = threading.Thread(
        target=run_staged_wave_service,
        kwargs={"queue_root": queue_root, "poll_interval_seconds": 0.01},
    )
    service_thread.start()
    state_path = queue_root / "worker_state.json"
    deadline = time.monotonic() + 2
    while not state_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert state_path.exists()

    try:
        with pytest.raises(TimeoutError, match="Timed out waiting for process lock"):
            run_staged_wave_service(queue_root)
    finally:
        (queue_root / "stop.request").write_text("test shutdown", encoding="utf-8")
        service_thread.join(timeout=2)
    assert not service_thread.is_alive()


def test_queue_service_exits_after_bounded_idle_timeout(tmp_path: Path):
    queue_root = tmp_path / "queue"
    processed = run_staged_wave_service(
        queue_root,
        poll_interval_seconds=0.01,
        idle_timeout_seconds=0.05,
    )
    assert processed == 0
    state = json.loads((queue_root / "worker_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "stopped"
    assert state["processIdentity"] is not None


def test_queue_service_drops_requests_marked_cancelled_by_the_supervisor(tmp_path: Path):
    queue_root = tmp_path / "queue"
    requests = queue_root / "requests"
    cancelled_runs = queue_root / "cancelled_runs"
    requests.mkdir(parents=True)
    cancelled_runs.mkdir(parents=True)
    request = {
        "requestId": "request-cancelled",
        "runId": "run-cancelled",
        "waveId": "run-cancelled-wave-0001",
    }
    (requests / "request-cancelled.json").write_text(json.dumps(request), encoding="utf-8")
    (cancelled_runs / "run-cancelled.json").write_text("{}", encoding="utf-8")
    executed = []
    result = {}

    def run_service():
        result["processed"] = run_staged_wave_service(
            queue_root,
            execute_wave=lambda payload: executed.append(payload["requestId"]) or {},
            poll_interval_seconds=0.01,
        )

    service_thread = threading.Thread(target=run_service)
    service_thread.start()
    result_path = queue_root / "results" / "request-cancelled.json"
    deadline = time.monotonic() + 2
    while not result_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert result_path.exists()
    cancelled_result = json.loads(result_path.read_text(encoding="utf-8"))
    assert cancelled_result["exitCode"] == 130
    assert executed == []

    (queue_root / "stop.request").write_text("test shutdown", encoding="utf-8")
    service_thread.join(timeout=2)
    assert not service_thread.is_alive()


def test_queue_service_preserves_success_when_cancel_marker_arrives_at_executor_return(
    tmp_path: Path,
):
    queue_root = tmp_path / "queue"
    requests = queue_root / "requests"
    requests.mkdir(parents=True)
    request_id = "request-late-cancel"
    run_id = "run-late-cancel"
    report_path = tmp_path / "report.json"
    (requests / f"{request_id}.json").write_text(
        json.dumps({
            "requestId": request_id,
            "runId": run_id,
            "waveId": f"{run_id}-wave-0001",
        }),
        encoding="utf-8",
    )

    def complete_then_receive_cancel_marker(request):
        cancelled_runs = queue_root / "cancelled_runs"
        (cancelled_runs / f"{run_id}.json").write_text("{}", encoding="utf-8")
        return {"reportPath": str(report_path)}

    processed = run_staged_wave_service(
        queue_root,
        execute_wave=complete_then_receive_cancel_marker,
        poll_interval_seconds=0.005,
        idle_timeout_seconds=0.03,
    )

    result = json.loads(
        (queue_root / "results" / f"{request_id}.json").read_text(encoding="utf-8")
    )
    assert processed == 1
    assert result["exitCode"] == 0
    assert result["status"] == "completed"
    assert result["reportPath"] == str(report_path)
    assert result["error"] is None


def test_queue_pruning_only_removes_old_consumed_results_and_unreferenced_cancel_markers(
    tmp_path: Path,
):
    queue_root = tmp_path / "queue"
    consumed = queue_root / "consumed"
    results = queue_root / "results"
    cancelled_runs = queue_root / "cancelled_runs"
    requests = queue_root / "requests"
    processing = queue_root / "processing"
    ambiguous = queue_root / "ambiguous"
    for directory in (consumed, results, cancelled_runs, requests, processing, ambiguous):
        directory.mkdir(parents=True)

    now = time.time()
    old_timestamp = now - 90 * 24 * 60 * 60

    old_consumed_result = consumed / "old-consumed.json"
    old_consumed_result.write_text("{}", encoding="utf-8")
    old_unconsumed_result = results / "old-unconsumed.json"
    old_unconsumed_result.write_text("{}", encoding="utf-8")
    old_cancel_marker = cancelled_runs / "old-idle-run.json"
    old_cancel_marker.write_text("{}", encoding="utf-8")
    queued_cancel_marker = cancelled_runs / "queued-run.json"
    queued_cancel_marker.write_text("{}", encoding="utf-8")
    processing_cancel_marker = cancelled_runs / "processing-run.json"
    processing_cancel_marker.write_text("{}", encoding="utf-8")
    queued_request = requests / "queued-request.json"
    queued_request.write_text(json.dumps({"runId": "queued-run"}), encoding="utf-8")
    in_flight_request = processing / "in-flight-request.json"
    in_flight_request.write_text(json.dumps({"runId": "processing-run"}), encoding="utf-8")
    ambiguous_request = ambiguous / "ambiguous-request.json"
    ambiguous_request.write_text(json.dumps({"runId": "ambiguous-run"}), encoding="utf-8")

    for path in (
        old_consumed_result,
        old_unconsumed_result,
        old_cancel_marker,
        queued_cancel_marker,
        processing_cancel_marker,
        queued_request,
        in_flight_request,
        ambiguous_request,
    ):
        os.utime(path, (old_timestamp, old_timestamp))

    pruned = _prune_staged_wave_records(queue_root, now_epoch=now)

    assert pruned == {"consumedResults": 1, "cancelledRuns": 1}
    assert not old_consumed_result.exists()
    assert old_unconsumed_result.exists()
    assert not old_cancel_marker.exists()
    assert queued_cancel_marker.exists()
    assert processing_cancel_marker.exists()
    assert queued_request.exists()
    assert in_flight_request.exists()
    assert ambiguous_request.exists()
