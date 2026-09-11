from types import SimpleNamespace

import pytest

from exercise_motion_pkg import wave_pipeline as wave


@pytest.mark.parametrize("failure", [None, "prefetch", "processing"])
def test_final_timing_separates_waits_and_preserves_failures(monkeypatch, failure):
    clock = iter([10.0, 14.0, 14.0, 20.0])
    monkeypatch.setattr(wave, "time", SimpleNamespace(perf_counter=lambda: next(clock)))
    timings = {}
    calls = []

    def prefetch():
        calls.append("prefetch")
        if failure == "prefetch":
            raise RuntimeError("prefetch failed")

    def process():
        calls.append("processing")
        if failure == "processing":
            raise RuntimeError("processing failed")
        return {"selected": True}

    def run():
        return wave.run_timed_final_processing(
            queued_at=7.0, wait_for_prefetch=prefetch, operation=process, timings=timings,
        )

    if failure:
        with pytest.raises(RuntimeError, match=f"{failure} failed"):
            run()
    else:
        assert run() == {"selected": True}
    assert timings["executorQueueWaitSeconds"] == 3.0
    assert timings["renderPrefetchWaitSeconds"] == 4.0
    if failure == "prefetch":
        assert calls == ["prefetch"]
        assert "pipelineProcessingSeconds" not in timings
    else:
        assert calls == ["prefetch", "processing"]
        assert timings["pipelineProcessingSeconds"] == 6.0
