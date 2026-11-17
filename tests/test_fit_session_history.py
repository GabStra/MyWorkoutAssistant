import pytest

from exercise_motion_pkg import fit_runtime


@pytest.mark.parametrize('changed_input', [False, True])
def test_completed_fit_evidence_follows_shared_spending(tmp_path, monkeypatch, changed_input):
    monkeypatch.setattr(fit_runtime, '_FIT_HISTORY_BY_INPUT', {})
    monkeypatch.setattr(fit_runtime, 'fit_cache_source_namespace', lambda: 'current-code')
    motion = tmp_path / 'motion.cleaned.json'
    motion.write_text('original')
    with fit_runtime.candidate_fit_session(tmp_path, budget_seconds=10.) as session:
        session.results['exact-input'] = ({'frames': []}, {'reason': 'fit_validation_failed'})
        session.previously_spent = 9.

    if changed_input:
        motion.write_text('changed')
    with fit_runtime.candidate_fit_session(tmp_path, budget_seconds=10.) as resumed:
        if changed_input:
            assert resumed.remaining() == 10.
            assert resumed.results == {}
        else:
            assert resumed.remaining() == 1.
            assert resumed.results['exact-input'][1]['reason'] == 'fit_validation_failed'
            from exercise_motion_pkg.controlled_motion import _fit_candidate_motion
            monkeypatch.setattr(fit_runtime, 'fit_input_key', lambda payload: 'exact-input')
            _, report = _fit_candidate_motion({'frames': []})
            assert report['reusedCandidateFit'] is True
            assert report['reason'] == 'fit_validation_failed'
            assert resumed.fit_calls == 0


def test_speculative_fit_cannot_consume_finalization_reserve(tmp_path, monkeypatch):
    monkeypatch.setattr(fit_runtime, '_FIT_HISTORY_BY_INPUT', {})
    monkeypatch.setattr(fit_runtime, 'fit_cache_source_namespace', lambda: 'current-code')
    (tmp_path / 'motion.cleaned.json').write_text('same motion')

    with fit_runtime.speculative_fit_context():
        with fit_runtime.candidate_fit_session(tmp_path) as speculative:
            assert speculative.budget_seconds == fit_runtime.SPECULATIVE_CANDIDATE_FIT_BUDGET_SECONDS
            speculative.previously_spent = speculative.budget_seconds

    with fit_runtime.candidate_fit_session(tmp_path) as finalization:
        assert finalization.budget_seconds == fit_runtime.DEFAULT_CANDIDATE_FIT_BUDGET_SECONDS
        assert finalization.remaining() >= fit_runtime.FINALIZATION_FIT_RESERVE_SECONDS


def test_optional_fit_is_skipped_when_candidate_budget_cannot_validate_it(tmp_path, monkeypatch):
    monkeypatch.setattr(fit_runtime, '_FIT_HISTORY_BY_INPUT', {})
    monkeypatch.setattr(fit_runtime, 'fit_cache_source_namespace', lambda: 'current-code')
    (tmp_path / 'motion.cleaned.json').write_text('same motion')

    with fit_runtime.candidate_fit_session(tmp_path, budget_seconds=30.) as session:
        session.previously_spent = 0.1
        assert not fit_runtime.candidate_fit_budget_available(30.)
        assert fit_runtime.candidate_fit_budget_available(20.)

    assert fit_runtime.candidate_fit_budget_available(30.)
