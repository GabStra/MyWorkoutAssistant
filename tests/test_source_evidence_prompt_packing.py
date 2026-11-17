"""Compact source-evidence prompt keeps semantics, strict schema and prior cache reuse."""

from pathlib import Path

from exercise_motion_pkg.review_questions import answer_question
from exercise_motion_pkg.source_evidence import (
    evidence_prompt, evidence_prompt_inventory, evidence_schema,
)


def requirements():
    return [
        {'id': 'action', 'description': 'lift the load', 'minimumDistinctFrameCount': 2},
        {'id': 'equipment_1', 'description': 'use one dumbbell', 'minimumObjectCount': 1},
    ]


def frames():
    return [
        {'id': 'uniform:1', 'sampling': 'uniform', 'image': 1, 'tileNumber': 1,
         'timestampSeconds': 0.0, 'sheetSha256': 'a' * 64},
        {'id': 'motion:1', 'sampling': 'motion', 'image': 1, 'tileNumber': 2,
         'timestampSeconds': 0.5, 'sheetSha256': 'b' * 64},
    ]


def test_compact_prompt_preserves_frame_identity_without_hash_provenance():
    inventory = frames()
    compact = evidence_prompt(requirements(), inventory, semantic_labels=True)
    legacy = evidence_prompt(requirements(), inventory, semantic_labels=True, legacy_wire=True)
    assert len(compact) < len(legacy)
    assert 'Schema:' not in compact and 'Schema:' in legacy
    assert 'sheetSha256' not in compact and 'sheetSha256' in legacy
    for frame in inventory:
        assert frame['id'] in compact
        assert f'"timestampSeconds":{frame["timestampSeconds"]}' in compact.replace(' ', '')
    assert '"observations"' in compact and '"evidenceFrameIds"' in compact
    assert '"verdict"' in compact and '"observedObjectCount"' in compact
    projected = evidence_prompt_inventory(inventory)
    assert [row['id'] for row in projected] == [frame['id'] for frame in inventory]
    assert all('sheetSha256' not in row for row in projected)


def test_compact_prompt_keeps_authoritative_strict_schema_supplied_separately():
    schema = evidence_schema(requirements(), frames(), semantic_labels=True)
    assert schema['additionalProperties'] is False
    observation = schema['properties']['observations']['items']['oneOf'][0]
    assert observation['additionalProperties'] is False
    assert 'evidenceFrameIds' in observation['properties']
    # The decoder receives this object as response_format.json_schema; the
    # prompt must not inject a second, duplicate copy of it.
    prompt = evidence_prompt(requirements(), frames(), semantic_labels=True)
    assert '"oneOf"' not in prompt and '"additionalProperties"' not in prompt


def test_prior_prompt_cache_is_reused_only_under_matching_identity(tmp_path: Path):
    image = tmp_path / 'frame.jpg'
    image.write_bytes(b'jpeg-bytes')
    legacy = evidence_prompt(requirements(), frames(), semantic_labels=True, legacy_wire=True)
    compact = evidence_prompt(requirements(), frames(), semantic_labels=True)
    identity = {'model': {'name': 'source-review'}, 'sourceEvidencePolicyVersion': 15}

    def seed():
        return 'legacy-raw', {'observations': []}

    raw, parsed = answer_question(directory=tmp_path, name='structured', prompt=legacy,
                                  frames=[image], max_tokens=128, operation=seed,
                                  reusable=lambda value: isinstance(value, dict), identity=identity)
    assert (raw, parsed) == ('legacy-raw', {'observations': []})

    def must_not_run():
        raise AssertionError('matching legacy identity should be reused')

    raw, parsed = answer_question(directory=tmp_path, name='structured', prompt=compact,
                                  frames=[image], max_tokens=128, operation=must_not_run,
                                  reusable=lambda value: isinstance(value, dict), identity=identity,
                                  legacy_prompt=legacy)
    assert (raw, parsed) == ('legacy-raw', {'observations': []})

    calls = []

    def mismatched_identity_operation():
        calls.append('called')
        return 'new-raw', {'observations': []}

    answer_question(directory=tmp_path, name='structured', prompt=compact, frames=[image],
                    max_tokens=128, operation=mismatched_identity_operation,
                    reusable=lambda value: isinstance(value, dict),
                    identity={**identity, 'model': {'name': 'different-review'}},
                    legacy_prompt=legacy)
    assert calls == ['called']
