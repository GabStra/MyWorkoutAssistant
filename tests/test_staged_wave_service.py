import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from contextvars import copy_context

from exercise_motion_pkg.staged_wave_service import (
    ADMISSION_LOCK_VERSION,
    ADMISSION_MUTEX_NAME,
    _queue_admission_mutex_name,
    _queue_admission_mutex_names,
    _prune_staged_wave_records,
    run_staged_wave_service,
)


@pytest.mark.parametrize('cancel_first', [False, True])
def test_service_overlaps_cpu_preparation_with_next_gpu_phase_and_isolates_logs(tmp_path, monkeypatch, cancel_first):
    from exercise_motion_pkg import staged_wave_service as service

    queue = tmp_path / 'queue'
    requests = queue / 'requests'
    requests.mkdir(parents=True)
    for index, name in enumerate(['first', 'second']):
        (requests / f'{name}.json').write_text(json.dumps({
            'requestId': name, 'waveId': name, 'runId': name,
            'enqueuedAtUnixNs': index + 1, 'allowCpuPhaseOverlap': True,
            'logPath': str(tmp_path / f'{name}.log'),
        }))
    first_cpu_started = threading.Event()
    second_gpu_started = threading.Event()
    gpu_active = []
    reviews = []

    def execute(request, *, render_executor, accelerator_phase, on_progress=None):
        name = request['waveId']
        with accelerator_phase(name, 'source_and_generation'):
            assert not gpu_active
            gpu_active.append(name)
            print(f'{name} gpu', flush=True)
            if name == 'second':
                assert first_cpu_started.wait(2)
                second_gpu_started.set()
                if cancel_first:
                    (queue / 'cancelled_runs' / 'first.json').write_text('{}')
            gpu_active.pop()
        if name == 'first':
            def prepare():
                first_cpu_started.set()
                assert second_gpu_started.wait(2), 'next GPU phase did not overlap CPU preparation'
                print('first cpu', flush=True)
            render_executor.submit(copy_context().run, prepare).result(timeout=3)
        with accelerator_phase(name, 'final_review'):
            assert not gpu_active
            gpu_active.append(name)
            print(f'{name} review', flush=True)
            reviews.append(name)
            gpu_active.pop()
        return {'reportPath': str(tmp_path / f'{name}-report.json')}

    monkeypatch.setattr(service, '_execute_wave_request', execute)
    assert run_staged_wave_service(queue, poll_interval_seconds=0.005, idle_timeout_seconds=0.05) == 2
    assert 'second' not in (tmp_path / 'first.log').read_text()
    assert 'first' not in (tmp_path / 'second.log').read_text()
    assert 'first cpu' in (tmp_path / 'first.log').read_text()
    first_result = json.loads((queue / 'results' / 'first.json').read_text())
    assert first_result['exitCode'] == (130 if cancel_first else 0)
    assert ('first' in reviews) is (not cancel_first)
    state = json.loads((queue / 'worker_state.json').read_text())
    assert state['activeRequests'] == []
    assert state['gpuOwnerWaveId'] is None


def test_service_terminalizes_non_object_request_without_retaining_an_active_owner(tmp_path):
    root = tmp_path / "queue"
    (root / "requests").mkdir(parents=True)
    (root / "requests" / "invalid.json").write_text("[]", encoding="utf-8")
    assert run_staged_wave_service(root, idle_timeout_seconds=0.05, poll_interval_seconds=0.01) == 1
    result = json.loads((root / "results" / "invalid.json").read_text())
    state = json.loads((root / "worker_state.json").read_text())
    assert result["status"] == "failed"
    assert "JSON object" in result["error"]
    assert state["activeRequests"] == []
    assert not list((root / "processing").glob("*.json"))


def test_atomic_service_record_retries_transient_windows_sharing_violation(tmp_path, monkeypatch):
    from exercise_motion_pkg import staged_wave_service as service
    original_replace = service.os.replace
    attempts = []

    def replace(source, destination):
        attempts.append(destination)
        if len(attempts) == 1:
            raise PermissionError("temporary sharing violation")
        return original_replace(source, destination)

    monkeypatch.setattr(service.os, "replace", replace)
    path = tmp_path / "worker_state.json"
    service._write_json_atomic(path, {"status": "running"})
    assert json.loads(path.read_text()) == {"status": "running"}
    assert len(attempts) == 2


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
    (queue_root / "stop.request").write_text("stop after queued work drains", encoding="utf-8")
    service_thread.join(timeout=2)
    assert not service_thread.is_alive()
    service_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert service_state["pid"] > 0
    assert service_state["status"] == "stopped"
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


def test_active_wave_state_is_durable_before_executor_starts(tmp_path: Path, monkeypatch):
    from exercise_motion_pkg import staged_wave_service

    queue_root = tmp_path / "queue"
    requests = queue_root / "requests"
    requests.mkdir(parents=True)
    state_path = queue_root / "worker_state.json"
    state_path.write_text(json.dumps({
        "schemaVersion": 1,
        "status": "idle",
        "currentRequestId": None,
        "currentWaveId": None,
    }), encoding="utf-8")
    request_id = "request-active-state"
    run_id = "run-active-state"
    wave_id = f"{run_id}-wave-0001"
    (requests / f"{request_id}.json").write_text(json.dumps({
        "requestId": request_id,
        "runId": run_id,
        "waveId": wave_id,
    }), encoding="utf-8")

    heartbeat_attempted = threading.Event()
    real_write_json_atomic = staged_wave_service._write_json_atomic

    def hold_periodic_heartbeat(path, payload):
        if threading.current_thread().name == "staged-wave-service-heartbeat":
            heartbeat_attempted.set()
            return
        real_write_json_atomic(path, payload)

    monkeypatch.setattr(staged_wave_service, "_write_json_atomic", hold_periodic_heartbeat)
    observed = {}

    def execute_wave(request):
        assert heartbeat_attempted.wait(timeout=1)
        observed["state"] = json.loads(state_path.read_text(encoding="utf-8"))
        return {}

    processed = run_staged_wave_service(
        queue_root,
        execute_wave=execute_wave,
        poll_interval_seconds=0.005,
        idle_timeout_seconds=0.03,
    )

    assert processed == 1
    assert observed["state"]["status"] == "running"
    assert observed["state"]["currentRequestId"] == request_id
    assert observed["state"]["currentWaveId"] == wave_id


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

    def fake_run(args, *, progress, render_executor, accelerator_phase=None):
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
                    {
                        "candidatesJson": "valid-candidates.json",
                        "workspace": "valid-workspace",
                        "exercisePlanJson": "valid-plan.json",
                    },
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


def test_cli_uses_staged_one_exercise_plan_as_authoritative_motion_context(
    tmp_path: Path,
    monkeypatch,
):
    from exercise_motion_pkg import cli
    from exercise_motion_pkg.bake_and_rank import BakeAndRankRequest

    motion_context = {
        "primaryEquipment": {
            "id": "barbell",
            "type": "BARBELL",
            "name": "Barbell",
            "capabilities": ["loaded_bar_support"],
        },
        "requiredAccessories": [
            {"id": "rack", "type": "ACCESSORY", "name": "Squat Rack", "capabilities": ["bar_rack"]}
        ],
    }
    plan_path = tmp_path / "one_exercise_plan.json"
    plan_path.write_text(
        json.dumps({
            "exercises": [{
                "exerciseId": "barbell-back-squat",
                "name": "Barbell Back Squat",
                "motionContext": motion_context,
            }]
        }),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "wave_manifest.json"
    manifest_path.write_text(
        json.dumps({
            "waveId": "wave-authoritative-plan",
            "workspace": str(tmp_path / "wave"),
            "items": [{
                "exerciseId": "barbell-back-squat",
                "exerciseName": "Barbell Back Squat",
                "candidatesJson": str(tmp_path / "candidates.json"),
                "workspace": str(tmp_path / "item-workspace"),
                "exercisePlanJson": str(plan_path),
            }],
        }),
        encoding="utf-8",
    )
    captured = {}

    def capture_wave(items, **_kwargs):
        captured["items"] = items
        return {"waveId": "wave-authoritative-plan"}

    monkeypatch.setattr(cli, "run_staged_bake_wave", capture_wave)
    request = BakeAndRankRequest(
        candidates_json=tmp_path / "shared-candidates.json",
        workspace=tmp_path / "shared-workspace",
        body_model_root=None,
    )

    cli.run_staged_bake_wave_manifest(
        SimpleNamespace(staged_wave_manifest=manifest_path), request=request
    )

    staged_item = captured["items"][0]
    assert staged_item.request.authoritative_exercise_motion_context == motion_context


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


@pytest.mark.parametrize("recover_only", [False, True])
@pytest.mark.parametrize("request_directory", ["processing", "requests"])
def test_queue_service_terminalizes_cancelled_processing_request_without_replaying(tmp_path: Path, recover_only, request_directory):
    queue_root = tmp_path / "queue"
    processing = queue_root / request_directory
    processing.mkdir(parents=True)
    request = {
        "schemaVersion": 1,
        "requestId": "request-cancelled-recovery",
        "runId": "run-cancelled-recovery",
        "waveId": "run-cancelled-recovery-wave-0001",
        "reportPath": str(tmp_path / "report.json"),
    }
    request_path = processing / "request-cancelled-recovery.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    cancelled_runs = queue_root / "cancelled_runs"
    cancelled_runs.mkdir(parents=True)
    (cancelled_runs / "run-cancelled-recovery.json").write_text(
        json.dumps({"runId": "run-cancelled-recovery"}), encoding="utf-8"
    )
    pending_path = queue_root / "requests" / "pending.json"
    if recover_only:
        pending_path.parent.mkdir(exist_ok=True)
        pending_path.write_text(json.dumps({"requestId": "pending", "waveId": "pending"}))
    executed = []

    result = {}

    def run_service():
        result["processed"] = run_staged_wave_service(
            queue_root,
            recover_only=recover_only,
            execute_wave=lambda payload: executed.append(payload["requestId"]) or {},
            poll_interval_seconds=0.01,
        )

    service_thread = threading.Thread(target=run_service)
    service_thread.start()
    result_path = queue_root / "results" / "request-cancelled-recovery.json"
    deadline = time.monotonic() + 2
    while not result_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert result_path.exists()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["requestId"] == "request-cancelled-recovery"
    assert payload["waveId"] == "run-cancelled-recovery-wave-0001"
    assert payload["exitCode"] == 130
    assert payload["status"] == "cancelled"
    assert "not replayed" in payload["error"]
    assert executed == []
    # The result is published before claim archival; inspect cleanup after shutdown.
    (queue_root / "stop.request").write_text("test shutdown", encoding="utf-8")
    service_thread.join(timeout=2)
    assert not service_thread.is_alive()
    assert result["processed"] == 0
    if recover_only:
        assert pending_path.is_file()
    assert not request_path.exists()
    assert not (queue_root / "ambiguous" / request_path.name).exists()
    archived_request = queue_root / "consumed" / "request-cancelled-recovery.request.json"
    assert json.loads(archived_request.read_text(encoding="utf-8")) == request



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


def test_service_persists_thread_stacks_after_an_advertised_operation_deadline(
    tmp_path: Path, monkeypatch,
):
    from exercise_motion_pkg import staged_wave_service as service

    queue = tmp_path / "queue"
    requests = queue / "requests"
    requests.mkdir(parents=True)
    (requests / "deadline.json").write_text(json.dumps({
        "requestId": "deadline",
        "runId": "run-deadline",
        "waveId": "run-deadline-wave-0001",
    }), encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()

    def block_inside_deadlined_phase(request, *, render_executor, accelerator_phase, on_progress=None):
        with accelerator_phase(
            request["waveId"], "source_validation", deadline=time.perf_counter() + 0.05,
        ):
            entered.set()
            release.wait(3)
        return {}

    monkeypatch.setattr(service, "_execute_wave_request", block_inside_deadlined_phase)
    monkeypatch.setattr(service, "STALLED_OPERATION_GRACE_SECONDS", 0.0)
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault(
        "processed",
        run_staged_wave_service(
            queue, poll_interval_seconds=0.01, idle_timeout_seconds=0.05,
        ),
    ))
    worker.start()
    assert entered.wait(2)
    state_path = queue / "worker_state.json"
    diagnostic = None
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("stalledOperation", {}).get("diagnosticPath"):
            diagnostic = Path(state["stalledOperation"]["diagnosticPath"])
            break
        time.sleep(0.02)
    assert diagnostic is not None and diagnostic.is_file()
    captured = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert captured["requestId"] == "deadline"
    assert captured["phase"] == "source_validation"
    assert any("block_inside_deadlined_phase" in "".join(thread["stack"]) for thread in captured["threads"])

    release.set()
    worker.join(timeout=3)
    assert not worker.is_alive()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "stopped"
    assert state["activeRequests"] == []
    assert "stalledOperation" not in state


def test_service_supervises_split_mode_source_checkpoint_without_accelerator_phase(
    tmp_path: Path, monkeypatch,
):
    """The source call in split-GVHMR mode is outside accelerator_phase."""
    from exercise_motion_pkg import staged_wave_service as service

    queue = tmp_path / "queue"
    requests = queue / "requests"
    requests.mkdir(parents=True)
    checkpoint_path = tmp_path / "staged_wave_checkpoint.json"
    checkpoint_bytes = json.dumps({
        "stage": "source_validation",
        "items": [{
            "exerciseName": "Retained exercise",
            "sourceActivity": {
                "operation": "preparing and validating source video",
                "videoId": "retained-video",
                "candidateKey": "retained-exercise:retained-candidate",
                "threadId": 4242,
                "operationDeadlineEpoch": time.time() - 0.2,
            },
        }],
    }).encode("utf-8")
    checkpoint_path.write_bytes(checkpoint_bytes)
    (requests / "source-hang.json").write_text(json.dumps({
        "requestId": "source-hang",
        "runId": "source-hang-run",
        "waveId": "source-hang-wave-0001",
        "checkpointPath": str(checkpoint_path),
    }), encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()

    def blocked_source_call(request, *, render_executor, accelerator_phase, on_progress=None):
        # Deliberately make no accelerator_phase call: this reproduces the
        # split-mode source path that escaped phase-only supervision.
        entered.set()
        release.wait(3)
        return {}

    monkeypatch.setattr(service, "_execute_wave_request", blocked_source_call)
    monkeypatch.setattr(service, "STALLED_OPERATION_GRACE_SECONDS", 0.0)
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault(
        "processed",
        run_staged_wave_service(
            queue, poll_interval_seconds=0.01, idle_timeout_seconds=0.05,
        ),
    ))
    worker.start()
    assert entered.wait(2)
    state_path = queue / "worker_state.json"
    diagnostic = None
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("stalledOperation", {}).get("diagnosticPath"):
            diagnostic = Path(state["stalledOperation"]["diagnosticPath"])
            break
        time.sleep(0.02)
    assert diagnostic is not None and diagnostic.is_file()
    captured = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert captured["operationDeadlineEpoch"] == pytest.approx(
        json.loads(checkpoint_bytes)["items"][0]["sourceActivity"]["operationDeadlineEpoch"]
    )
    assert captured["sourceActivities"][0]["videoId"] == "retained-video"
    assert captured["sourceActivities"][0]["candidateKey"] == "retained-exercise:retained-candidate"
    assert captured["sourceActivities"][0]["threadId"] == 4242
    assert any("blocked_source_call" in "".join(thread["stack"]) for thread in captured["threads"])

    release.set()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert checkpoint_path.read_bytes() == checkpoint_bytes
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["activeRequests"] == []
    assert "stalledOperation" not in state


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


def test_queue_pruning_expires_old_terminal_records_and_unreferenced_cancel_markers(
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
    old_timestamp = now - 120 * 24 * 60 * 60

    old_consumed_result = consumed / "old-consumed.json"
    old_consumed_result.write_text("{}", encoding="utf-8")
    old_unconsumed_result = results / "old-unconsumed.json"
    old_unconsumed_result.write_text("{}", encoding="utf-8")
    recent_unconsumed_result = results / "recent-unconsumed.json"
    recent_unconsumed_result.write_text("{}", encoding="utf-8")
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
    recent_ambiguous_request = ambiguous / "recent-ambiguous-request.json"
    recent_ambiguous_request.write_text(json.dumps({"runId": "recent-ambiguous-run"}), encoding="utf-8")

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
    recent_timestamp = now - 2 * 24 * 60 * 60
    for path in (recent_unconsumed_result, recent_ambiguous_request):
        os.utime(path, (recent_timestamp, recent_timestamp))

    pruned = _prune_staged_wave_records(queue_root, now_epoch=now)

    assert pruned == {
        "consumedResults": 1,
        "unconsumedResults": 1,
        "ambiguousRequests": 1,
        "cancelledRuns": 1,
    }
    assert not old_consumed_result.exists()
    assert not old_unconsumed_result.exists()
    assert recent_unconsumed_result.exists()
    assert not old_cancel_marker.exists()
    assert queued_cancel_marker.exists()
    assert processing_cancel_marker.exists()
    assert queued_request.exists()
    assert in_flight_request.exists()
    assert not ambiguous_request.exists()
    assert recent_ambiguous_request.exists()


def test_gpu_gate_shares_review_slots_and_prioritizes_review_over_extraction():
    from concurrent.futures import ThreadPoolExecutor
    from exercise_motion_pkg.staged_wave_service import WaveGpuGate

    gate = WaveGpuGate()
    barrier = threading.Barrier(3, timeout=3)
    def parallel_review():
        with gate.phase("wave", "final_review"):
            barrier.wait()
    with ThreadPoolExecutor(max_workers=3) as executor:
        jobs = [executor.submit(parallel_review) for _ in range(3)]
        for job in jobs:
            job.result(timeout=4)

    order = []
    def run(stage):
        with gate.phase("next", stage):
            order.append(stage)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with gate.phase("current", "reconstruction"):
            review = executor.submit(run, "final_review")
            with gate.condition:
                assert gate.condition.wait_for(lambda: gate.review_waiters == 1, timeout=2)
            extraction = executor.submit(run, "reconstruction")
        review.result(timeout=3)
        extraction.result(timeout=3)
    assert order == ["final_review", "reconstruction"]


def test_gpu_gate_cancellation_interrupts_a_queued_review():
    from concurrent.futures import ThreadPoolExecutor
    from exercise_motion_pkg.staged_wave_service import WaveGpuGate

    gate = WaveGpuGate()
    cancelled = threading.Event()
    def review():
        with gate.phase("cancelled", "final_review", cancelled.is_set):
            pytest.fail("Cancelled review acquired the GPU")
    with ThreadPoolExecutor(max_workers=1) as executor:
        with gate.phase("current", "reconstruction"):
            job = executor.submit(review)
            with gate.condition:
                assert gate.condition.wait_for(lambda: gate.review_waiters == 1, timeout=2)
            cancelled.set()
            with pytest.raises(KeyboardInterrupt, match="cancelled"):
                job.result(timeout=2)
    assert gate.review_waiters == 0
    with gate.phase("next", "reconstruction"):
        pass


def test_gpu_gate_preserves_candidate_deadline_while_queued():
    from exercise_motion_pkg.staged_wave_service import WaveGpuGate
    from exercise_motion_pkg.bake_and_rank import CandidateWallTimeBudgetExpired

    gate = WaveGpuGate()
    with gate.phase("current", "reconstruction"):
        with pytest.raises(CandidateWallTimeBudgetExpired, match="waiting for the GPU"):
            with gate.phase("expired", "final_review", deadline=time.perf_counter() - 1):
                pytest.fail("Expired candidate acquired the GPU")
        assert gate.users == 1
        assert gate.review_waiters == 0


def test_gpu_gate_allows_only_explicit_distinct_gpu_lanes_to_overlap():
    from concurrent.futures import ThreadPoolExecutor
    from exercise_motion_pkg.staged_wave_service import WaveGpuGate

    gate = WaveGpuGate()
    barrier = threading.Barrier(2, timeout=3)

    def run(lane):
        with gate.phase("wave", lane, gpu_lane=lane):
            barrier.wait()

    with ThreadPoolExecutor(max_workers=2) as executor:
        llama = executor.submit(run, "llama")
        reconstruction = executor.submit(run, "reconstruction")
        llama.result(timeout=4)
        reconstruction.result(timeout=4)


def test_gpu_gate_global_phase_remains_exclusive_with_named_lanes():
    from concurrent.futures import ThreadPoolExecutor
    from exercise_motion_pkg.staged_wave_service import WaveGpuGate

    gate = WaveGpuGate()
    attempted = threading.Event()
    acquired = threading.Event()

    def named_lane():
        attempted.set()
        with gate.phase("split", "reconstruction", gpu_lane="reconstruction"):
            acquired.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with gate.phase("legacy", "whole_wave"):
            job = executor.submit(named_lane)
            assert attempted.wait(2)
            assert not acquired.wait(0.05)
        job.result(timeout=3)
    assert acquired.is_set()

    attempted.clear()
    acquired.clear()

    def global_lane():
        attempted.set()
        with gate.phase("legacy-next", "whole_wave"):
            acquired.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with gate.phase("split", "reconstruction", gpu_lane="reconstruction"):
            job = executor.submit(global_lane)
            assert attempted.wait(2)
            assert not acquired.wait(0.05)
        job.result(timeout=3)
    assert acquired.is_set()


def test_gpu_gate_keeps_final_review_priority_within_its_lane():
    from concurrent.futures import ThreadPoolExecutor
    from exercise_motion_pkg.staged_wave_service import WaveGpuGate

    gate = WaveGpuGate()
    order = []

    def run(stage):
        with gate.phase("next", stage, gpu_lane="llama"):
            order.append(stage)

    with ThreadPoolExecutor(max_workers=2) as executor:
        with gate.phase("current", "source_and_generation", gpu_lane="llama"):
            source = executor.submit(run, "source_and_generation")
            with gate.condition:
                assert gate.condition.wait_for(
                    lambda: gate._lanes["llama"]["users"] == 1
                    and gate._lanes["llama"]["review_waiters"] == 0,
                    timeout=2,
                )
            review = executor.submit(run, "final_review")
            with gate.condition:
                assert gate.condition.wait_for(
                    lambda: gate._lanes["llama"]["review_waiters"] == 1,
                    timeout=2,
                )
        review.result(timeout=3)
        source.result(timeout=3)
    assert order == ["final_review", "source_and_generation"]
