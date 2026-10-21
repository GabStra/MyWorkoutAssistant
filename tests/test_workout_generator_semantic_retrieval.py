import hashlib
import json
import logging
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from workout_generator_pkg import semantic_retrieval


@pytest.mark.parametrize('extra_row,visible', [('', False), ('encoder.weight | MISSING', True),
                                             ('encoder.weight | UNEXPECTED', True)])
def test_model_notice_filter_preserves_actionable_loading_warnings(extra_row, visible):
    text = (f'BertModel LOAD REPORT from: {semantic_retrieval.MODEL_NAME}\n'
            'Key | Status\nembeddings.position_ids | UNEXPECTED\n' + extra_row)
    record = logging.LogRecord('transformers.modeling_utils', logging.WARNING, '', 0, text, (), None)
    assert semantic_retrieval._actionable_model_log(record) is visible
    record.msg = 'A different model warning'
    assert semantic_retrieval._actionable_model_log(record)


@pytest.mark.parametrize('fails', [False, True])
def test_model_loading_quiets_progress_and_restores_settings_on_failure(monkeypatch, fails):
    from transformers.utils import logging as model_logging
    logger = logging.getLogger('transformers.modeling_utils')
    previous_filters = list(logger.filters)
    progress = {'enabled': True}
    monkeypatch.setattr(model_logging, 'is_progress_bar_enabled', lambda: progress['enabled'])
    monkeypatch.setattr(model_logging, 'disable_progress_bar', lambda: progress.update(enabled=False))
    monkeypatch.setattr(model_logging, 'enable_progress_bar', lambda: progress.update(enabled=True))
    model = object()

    def load(*args, **kwargs):
        assert not progress['enabled']
        assert semantic_retrieval._actionable_model_log in logger.filters
        if fails:
            raise RuntimeError('Model loading failed')
        return model

    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=load))
    monkeypatch.setattr(semantic_retrieval, '_model', None)
    if fails:
        with pytest.raises(RuntimeError, match='Model loading failed'):
            semantic_retrieval._model_instance()
    else:
        assert semantic_retrieval._model_instance() is model
    assert progress['enabled'] and logger.filters == previous_filters


class FakeEmbeddingModel:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **_kwargs):
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vector = np.zeros(semantic_retrieval.MODEL_DIMENSION, dtype=np.float32)
            vector[:len(digest)] = np.frombuffer(digest, dtype=np.uint8).astype(np.float32) + 1
            vector /= np.linalg.norm(vector)
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float32)


def test_corpus_embeddings_are_cached_and_reused(monkeypatch, tmp_path):
    model = FakeEmbeddingModel()
    monkeypatch.setattr(semantic_retrieval, "_model_instance", lambda: model)
    monkeypatch.setattr(semantic_retrieval, "CACHE_DIRECTORY", tmp_path)
    entries = [{"name": "Barbell Squat", "equipmentName": "Barbell", "muscleGroups": ["FRONT_QUADRICEPS"]}]

    first = semantic_retrieval.rank(["squat"], entries)
    second = semantic_retrieval.rank(["squat"], entries)

    assert first == second
    assert len(model.calls) == 3  # corpus once, query once per lookup
    assert list(tmp_path.glob("exercise_embeddings_*.npz"))


def test_invalid_cached_embeddings_are_rebuilt(monkeypatch, tmp_path):
    model = FakeEmbeddingModel()
    monkeypatch.setattr(semantic_retrieval, "_model_instance", lambda: model)
    monkeypatch.setattr(semantic_retrieval, "CACHE_DIRECTORY", tmp_path)
    entries = [{"name": "Pull-Up"}]
    fingerprint = semantic_retrieval._fingerprint([semantic_retrieval._entry_text(entries[0])])
    path = tmp_path / f"exercise_embeddings_{fingerprint}.npz"
    path.write_bytes(b"not an npz cache")

    ranked = semantic_retrieval.rank(["vertical pull"], entries)

    assert list(ranked[0]) == [0]
    assert len(model.calls) == 2


def test_history_similarity_query_uses_candidate_metadata_not_purpose_prompt():
    candidate = {"name": "Dumbbell Romanian Deadlift", "equipmentName": "Dumbbell",
                 "muscleGroups": ["BACK_HAMSTRING", "BACK_GLUTEAL"], "secondaryMuscleGroups": []}
    query = json.dumps({"candidate": candidate, "purpose": "irrelevant injected instructions"})
    assert semantic_retrieval._query_text(query) == semantic_retrieval._entry_text(candidate)
    assert "irrelevant injected instructions" not in semantic_retrieval._query_text(query)
