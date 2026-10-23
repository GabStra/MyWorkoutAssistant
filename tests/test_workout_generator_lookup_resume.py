import copy

import pytest

from workout_generator_pkg import interactive_shell as shell
from workout_generator_pkg import planner_context
from workout_generator_pkg.plan_review import REVIEW_VERSION
from workout_generator_pkg.review_assessment import VERSION, assessment_hash
from workout_generator_pkg.planning_tools import audit_workout_plan
from test_workout_generator_planning_tools import planning_case, requirement_messages
from test_workout_generator_planner_context import _state, _tool


@pytest.mark.parametrize('binding', ['current', 'stale', 'absent'])
def test_assessed_repair_owns_routing_without_waiving_unassessed_clarification(binding):
    equipment, _, stored, draft = planning_case()
    draft['workouts'][0]['exercises'][0]['numWorkSets'] = 3
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    finding = {'severity': 'blocking', 'basis': 'material_uncertainty',
        'path': '/draft/workouts/0', 'evidencePaths': ['/draft/workouts/0'],
        'message': 'The pairing needs assessment.', 'repair': 'Separate the pairing.',
        'action': 'clarify', 'decisionId': None, 'newConflictEvidencePaths': [], 'muscleTargets': []}
    review = {'version': REVIEW_VERSION, 'inputHash': 'pairing-review', 'findings': [finding]}
    if binding != 'absent':
        review['assessment'] = {'version': VERSION, 'inputHash': assessment_hash(review),
            'groups': [{'findingIndexes': [0], 'disposition': 'repair',
                'repairDimensions': ['exercise_selection', 'superset'], 'repairObjectives': [],
                'reason': 'The available compiler can separate the pairing.'}],
            'repairPlan': 'Select the corrected grouping.'}
    result.update(passed=False, review=review,
        assessmentDraftId=result['currentDraftId'] if binding == 'current' else 'OLD_REVISION',
        errors=[{'code': 'independent_review_finding', 'findingIndex': 0, **finding}])
    _tool(messages, 'audit_workout_plan', draft, result, 'pairing-review')
    before = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['planningDecisionNeeded'] is (binding != 'current')
    if binding == 'current':
        assert 'sessionBlocks' in state['repairTask']['instruction']
        assert any('Current backend work order: Follow repairTask.' in message.get('content', '')
            for message in shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert messages == before


def test_resume_progress_compares_valid_old_results_but_keeps_new_pages_available():
    facts = {('candidate', 'LIBRARY_1'), ('details', 'LIBRARY_1'),
             ('evidence', 'LIBRARY_1', 0, 1)}
    state = {'lastAudit': {'passed': False}, 'currentDraftId': 'REVISION_0'}
    batches = {1: facts, 6: {('evidence', 'LIBRARY_1', 0, 1)}}
    planner_context._focus_discovery(state, batches, epoch=5)
    assert 'get_training_evidence' in state['discoveryPaused']['blockedTools']

    newer_page = copy.deepcopy(state)
    newer_page.pop('discoveryPaused')
    batches[6] = {('evidence', 'LIBRARY_1', 1, 1)}
    planner_context._focus_discovery(newer_page, batches, epoch=5)
    assert 'discoveryPaused' not in newer_page

    # A changed draft/instruction reopens discovery; old batches alone do not pause it.
    reopened = {'lastAudit': {'passed': False}}
    planner_context._focus_discovery(reopened, batches, epoch=7)
    assert 'discoveryPaused' not in reopened
    pending_question = {'lastAudit': {'passed': False}, 'planningDecisionNeeded': True}
    planner_context._focus_discovery(pending_question, {1: facts, 6: facts}, epoch=5)
    assert 'discoveryPaused' not in pending_question


@pytest.mark.parametrize('old_review_hash', ['current-review', 'older-review'])
def test_refreshed_assessment_supersedes_historical_rejected_repair(old_review_hash):
    equipment, _, stored, draft = planning_case()
    messages = requirement_messages(stored)
    result = audit_workout_plan(draft, equipment, messages)
    finding = {'severity': 'warning', 'basis': 'uncertainty', 'action': 'repair',
        'path': '/draft/workouts/0', 'evidencePaths': ['/draft/workouts/0'],
        'message': 'Review the movement selection.', 'repair': 'Choose the corrected menu.',
        'decisionId': None, 'newConflictEvidencePaths': [], 'muscleTargets': []}
    review = {'version': REVIEW_VERSION, 'inputHash': 'current-review', 'findings': [finding]}
    fresh = {'version': VERSION, 'inputHash': assessment_hash(review),
        'groups': [{'findingIndexes': [0], 'disposition': 'repair',
            'repairDimensions': ['exercise_selection'], 'repairObjectives': [],
            'reason': 'The fresh assessment selects the menu repair.'}], 'repairPlan': 'Use menu selection.'}
    old_review = {**review, 'inputHash': old_review_hash}
    old = copy.deepcopy(fresh)
    old['inputHash'] = assessment_hash(old_review)
    old['groups'][0].update(repairDimensions=['ordering'], reason='Historical rejected ordering repair.')
    result.update(passed=False, review={**review, 'assessment': fresh},
        errors=[{'code': 'independent_review_finding', 'findingIndex': 0, **finding}])
    result['coordinatedRepairReceipt'] = {
        'status': 'rejected_before_materialization', 'baseDraftId': result['currentDraftId'],
        'currentDraftId': result['currentDraftId'], 'requirementsId': stored['requirementsId'],
        'submittedEdits': {'exerciseUpdates': []}, 'findingsAssessment': old,
        'reviewFindings': [finding], 'assessmentInputHash': old['inputHash'],
        'assessmentHash': assessment_hash({'inputHash': old['inputHash'], 'findings': [finding]}),
        'reviewVersion': REVIEW_VERSION, 'reviewInputHash': old_review_hash,
        'libraryFingerprint': result['libraryFingerprint'],
        'historyFingerprint': result.get('historyFingerprint'),
        'resolvedDecisions': result.get('resolvedDecisions', {}),
    }
    _tool(messages, 'audit_workout_plan', draft, result, 'refreshed-assessment')
    original = copy.deepcopy(messages)
    state = _state(shell._messages_for_api(messages, True, provided_equipment=equipment))
    assert state['repairTask']['findingsAssessment'] == fresh
    assert state['repairTask']['reviewFindings'] == [finding]
    assert 'sessionBlocks' in state['repairTask']['instruction']
    assert planner_context.planner_response_profile(state)['reasoning_effort'] is None
    assert messages == original


def test_changed_code_disclosure_reaudits_saved_case_before_coverage_repair():
    import json
    import hashlib
    from pathlib import Path
    from workout_generator_pkg.training_history import TrainingHistory
    source = Path('build/workout_joint_priority_solver_20261023/unified_evidence_continuation7_20261023/workouts/conversation_sessions/1aebdeec-44af-4c57-87e9-c4f73b10d4bf/messages.json')
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    messages = json.loads(source.read_text(encoding='utf-8'))
    original = copy.deepcopy(messages)
    backup = 'build/backup_conversion/workout_store_backup_2026-10-15_current_library_snapshot_evidence.json'
    gear = shell._load_exercise_library_payload(backup)
    state = planner_context.request_planning_state(shell._messages_for_api(messages, True,
        TrainingHistory.from_file(backup), gear))
    assert state['savedDraftReaudit'] == {'requirementsId': state['requirementsId'],
        'baseDraftId': 'REVISION_4', 'patch': []}
    assert not state.get('repairTask')
    assert messages == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    planner_context._reopen_capped_coordinated_repair(state)
    assert state['savedDraftReaudit']['patch'] == []
    # The live refreshed receipt is compacted without submittedDraft. It must
    # use the saved draft instead of falling back to historical repair intent.
    refreshed_source = Path('build/workout_joint_priority_solver_20261023/region_disclosure_continuation8_20261023/workouts/conversation_sessions/b893b7f7-f0d0-44e1-8be3-bc5fcd2626f2/messages.json')
    refreshed = json.loads(refreshed_source.read_text(encoding='utf-8'))
    current = planner_context.request_planning_state(shell._messages_for_api(refreshed, True,
        TrainingHistory.from_file(backup), gear))
    assert not current.get('savedDraftReaudit')
    assert current.get('repairTask')
    assert not any('agreed-disclosure gap' in finding.get('message', '')
        for finding in current['repairTask']['reviewFindings'])
