import threading
import json
import copy
from dataclasses import replace

import pytest

import workout_generator_pkg.cli as cli
import workout_generator_pkg.generation_pipeline as pipeline
from workout_generator_pkg.generation_pipeline import execute_workout_generation
from workout_generator_pkg.plan_contract import ContractValidationError






def test_approved_calibration_flags_use_full_original_library_evidence(monkeypatch, tmp_path):
    from workout_generator_pkg.planning_tools import library_fingerprint

    gear_id = '11111111-1111-4111-8111-111111111111'
    selected_id = 'selected-definition'
    equipment = {
        'equipments': [{'id': gear_id, 'name': 'Barbell', 'type': 'BARBELL'}],
        'accessoryEquipments': [],
        'exerciseDefinitions': [
            {'id': selected_id, 'name': 'Barbell Press', 'exerciseType': 'WEIGHT',
             'equipmentId': gear_id, 'requiredAccessoryEquipmentIds': [],
             'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
             'exerciseCategory': 'MODERATE_COMPOUND', 'movementRef': 'horizontal_push'},
            {'id': 'unselected-definition', 'name': 'Unused', 'exerciseType': 'WEIGHT',
             'equipmentId': gear_id, 'requiredAccessoryEquipmentIds': [],
             'muscleGroups': ['FRONT_CHEST'], 'secondaryMuscleGroups': [],
             'exerciseCategory': 'ISOLATION', 'movementRef': 'horizontal_push'},
        ],
    }
    history_fingerprint = 'history-fingerprint'
    evidence = {'historyFingerprint': history_fingerprint,
        'libraryFingerprint': library_fingerprint(equipment),
        'exercises': [{'definitionId': selected_id, 'status': 'comparable_records',
            'sessions': [{'performances': [{'record': {'setType': 'WeightSetData',
                'actualReps': 8, 'loadKg': 20}}]}]}]}
    messages = [
        {'role': 'assistant', 'tool_calls': [{'id': 'evidence', 'type': 'function',
            'function': {'name': 'get_training_evidence'}}]},
        {'role': 'tool', 'tool_call_id': 'evidence', 'content': json.dumps(evidence)},
        {'role': 'assistant', 'tool_calls': [{'id': 'draft', 'type': 'function',
            'function': {'name': 'audit_workout_plan'}}]},
    ]
    snapshot = {
        'planIndex': {'planName': 'Draft', 'equipments': [], 'accessoryEquipments': [],
            'auditTargets': {}, 'exercises': [{'id': 'EXERCISE_0', 'libraryDefinitionId': selected_id,
                'numWorkSets': 2, 'generateWarmUpSets': False, 'maxReps': 10,
                'requiresLoadCalibration': False}], 'workouts': []},
        'submittedDraft': {}, 'historyFingerprint': history_fingerprint, 'preview': 'Approved draft',
    }
    monkeypatch.setattr(pipeline, 'confirmed_draft', lambda *_args, **_kwargs: copy.deepcopy(snapshot))
    monkeypatch.setattr(pipeline, 'require_current_review', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, 'active_requirement_result', lambda *_: (0, {'requirements': {}}))
    monkeypatch.setattr(pipeline, 'validate_plan_index_contract', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, 'validate_audit_targets', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, 'plan_audit_package', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(pipeline, 'audit_workout_package',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('reached programming audit')))

    result = execute_workout_generation(None, messages, provided_equipment=equipment,
        script_dir=str(tmp_path), force_use_reasoner=False)

    assert 'reached programming audit' in result['error']
    assert 'calibration flags do not match' not in result['error']




def test_fix_set_errors_converts_distance_set_to_goal_encoding() -> None:
    from workout_generator_pkg.domain_ops import fix_set_errors

    fixed = fix_set_errors([{"id": "s1", "type": "DistanceSet", "distance": 500}])

    assert fixed == [
        {
            "id": "s1",
            "type": "EnduranceSet",
            "timeInMillis": 0,
            "autoStart": True,
            "autoStop": False,
            "targetDistanceMeters": 500.0,
        }
    ]
