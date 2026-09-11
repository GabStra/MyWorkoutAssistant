import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from exercise_motion_pkg import youtube


@pytest.mark.parametrize('name,invalid', [
    ('Barbell Push Jerk', True), ('Dumbbell Power Jerk', True),
    ('Kettlebell Squat Jerk', True), ('Barbell Split Jerk', False),
    ('Clean and Jerk', False),
])
def test_contract_receiving_stance_matches_variant(name, invalid):
    contract = {'exerciseName': name, 'requiredPhases': ['catch overhead in a split stance']}
    assert bool(youtube.exercise_motion_contract_identity_issues(contract)) is invalid


def test_materialized_camera_override_executes_real_renderer_expression():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node required for renderer expression execution')
    source = Path(youtube.__file__).with_name('preview.py').read_text(encoding='utf-8')
    block = re.search(r'const reviewYaw = .*?Math.PI / 180.0;', source, re.S).group()
    script = '''let yaw; const wearDisplay = {viewYawDegrees: 135};
      const results = [315, 0, undefined, 'invalid'].map(value => {
        const options = {cameraYawDegrees: value}; BLOCK
        return yaw * 180 / Math.PI;
      }); console.log(JSON.stringify(results));'''.replace('BLOCK', block)
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == pytest.approx([315, 0, 135, 135])


@pytest.mark.parametrize('strong,extra_calls,recover', [(True, 1, False), (False, 0, False), (True, 1, True)])
def test_contradiction_review_is_bounded_and_does_not_auto_approve(tmp_path, monkeypatch, strong, extra_calls, recover):
    candidate = youtube.YouTubeCandidate('https://example.test', 'id', 'Demo', None, 10, None, None, None, None)
    frame = tmp_path / 'frame.jpg'
    frame.write_bytes(b'fixture')
    prepared = youtube.PreparedVisionReview(candidate, tempfile.TemporaryDirectory(),
        [frame], [[frame], [frame]], [(0., 4.), (4., 8.)], 2, 'Review')
    monkeypatch.setattr(youtube, 'source_review_pose_motion_evidence', lambda *a, **k: {'strongMotion': strong})
    monkeypatch.setattr(youtube, 'source_review_temporal_change_metrics', lambda *a, **k: {'available': False})
    monkeypatch.setattr(youtube, 'planned_adaptive_chunk_indexes', lambda *a: [0, 1])
    calls = []
    def caption(**kwargs):
        calls.append(kwargs['prompt'])
        if recover and len(calls) == 2:
            result = {key: True for key in youtube.VISION_HARD_GATE_REASONS}
            result.update(target_identity_match=True, target_match=1., complete_movement=1.,
                          capture_quality=1., execution_quality=1., moving_subject_realism_score=1.,
                          source_score=1., blocking_issues=['none'], confidence=1.)
            return json.dumps(result)
        return json.dumps({'correct_exercise': False, 'complete_repetition_visible': False,
                          'usable_for_motion_extraction': False, 'source_score': 0,
                          'blocking_issues': ['wrong_exercise'], 'confidence': 1})
    try:
        score, reasons, payload = youtube.score_prepared_vision_review(
            prepared=prepared, settings=youtube.YouTubeRankingSettings(), caption_images=caption)
    finally:
        prepared.close()
    assert (score >= .5) is recover
    assert sum('Independent evidence check:' in prompt for prompt in calls) == extra_calls
    assert len(calls) <= 2 + extra_calls


def test_cached_contradiction_requires_review_once(monkeypatch):
    candidate = youtube.YouTubeCandidate('x', 'id', 'Demo', None, 10, None, None, None, None,
        vision_score=0., vision_payload={'correct_exercise': False, 'source_score': 0.})
    monkeypatch.setattr(youtube, 'source_review_pose_motion_evidence', lambda *a, **k: {'strongMotion': True})
    assert not youtube.candidate_has_debug_review_payload(candidate)
    candidate.vision_payload['sourceRejectionReviewPolicyVersion'] = 1
    assert youtube.candidate_has_debug_review_payload(candidate)


@pytest.mark.parametrize('status,version,expected', [('recommended', 0, True), ('rejected', 0, False), ('rejected', 1, True)])
def test_resume_revisits_only_old_all_rejected_discovery(tmp_path, status, version, expected):
    shell = shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell required')
    root = Path(__file__).resolve().parents[1]
    source = (root / 'scripts/run_exercise_motion_workout_plan.ps1').read_text(encoding='utf-8-sig')
    function = source.split('function Test-DiscoveryStageReady {', 1)[1].split('function Test-MovementSkeletonIntegrity', 1)[0]
    candidate_path = tmp_path / 'candidates.json'
    candidate_path.write_text(json.dumps({'wrapperDiscoverySignature': {'schemaVersion': 1, 'policyVersion': 5,
        'exercisePlanSha256': 'plan', 'equipmentSha256': '', 'argumentsSha256': 'args'},
        'ranking': {'sourceRejectionReviewPolicyVersion': version},
        'exercises': [{'candidates': [{'status': status}]}]}))
    script = tmp_path / 'check.ps1'
    script.write_text('function Test-DiscoveryStageReady {' + function + '''
$discoveryStagePolicyVersion = 5
$item = [pscustomobject]@{ exerciseCandidatesPath = (Join-Path $PSScriptRoot 'candidates.json');
 exercisePlanSha256 = 'plan'; equipmentSha256 = ''; discoveryArgumentsSha256 = 'args'; bakeWorkspace = $PSScriptRoot }
Test-DiscoveryStageReady -WorkItem $item
''')
    result = subprocess.run([shell, '-NoProfile', '-File', str(script)], capture_output=True, text=True, check=True)
    assert result.stdout.strip().lower() == str(expected).lower()
