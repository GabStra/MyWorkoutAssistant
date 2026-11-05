import copy
import json

import pytest

from workout_generator_pkg import plan_review as review
from test_workout_generator_single_review import setup_case, request_data, response_for


def test_current_review_reuses_content_across_version_metadata_changes(monkeypatch):
    equipment, messages, audited, _ = setup_case()
    calls = []

    def respond(client, request, **options):
        calls.append(request)
        return json.dumps(response_for(request_data(request), options['output_schema'])), None, None

    monkeypatch.setattr(review, '_review_call', respond)
    approved = review.review_draft(None, audited, messages, equipment)
    assert approved['passed'], approved.get('errors')
    approved['review']['version'] -= 1
    approved['review']['assessment']['version'] -= 1
    messages.extend([
        {'role': 'assistant', 'tool_calls': [{'id': 'current-review',
            'function': {'name': 'audit_workout_plan'}}]},
        {'role': 'tool', 'tool_call_id': 'current-review', 'content': json.dumps(approved)},
    ])
    monkeypatch.setattr(review, 'REVIEW_VERSION', review.REVIEW_VERSION + 1)

    reused = review.review_draft(None, audited, messages, equipment)

    assert reused['passed'] and len(calls) == 1
    review._require_review_receipt(reused, messages, equipment)
    monkeypatch.setitem(review.GUIDELINE_POLICY, 'currentEvidencePolicy', 'Changed semantic policy')
    with pytest.raises(ValueError, match='missing or stale'):
        review._require_review_receipt(reused, messages, equipment)


@pytest.mark.parametrize('field', ['requirements', 'finalArtifact', 'history', 'programmingGuidelines'])
def test_review_identity_binds_current_authority_candidate_evidence_and_policy(field):
    _, _, _, context = setup_case()
    changed = copy.deepcopy(context)
    changed[field]['changedCurrentInput'] = True
    assert review._review_base_hash(changed) != review._review_base_hash(context)
    changed = {**context, 'reviewVersion': review.REVIEW_VERSION + 10}
    assert review._review_base_hash(changed) == review._review_base_hash(context)
