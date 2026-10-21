"""Local semantic ranking with a fingerprinted on-disk exercise index."""

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import logging
import os
from pathlib import Path
import re
import threading
import zipfile

import numpy as np


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL_DIMENSION = 384
CACHE_DIRECTORY = Path(__file__).resolve().parents[1] / "build" / "workout_generator_cache"
_model = None
_model_lock = threading.Lock()
_cache_lock = threading.Lock()


def _actionable_model_log(record):
    text = re.sub(r'\x1b\[[0-9;]*m', '', record.getMessage())
    if f'LOAD REPORT from: {MODEL_NAME}' not in text:
        return True
    rows = [(key, status) for key, status in re.findall(r'(?m)^\s*(\S+)\s*\|\s*(\S+)', text)
            if key != 'Key']
    return rows != [('embeddings.position_ids', 'UNEXPECTED')]


def _model_instance():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                from transformers.utils import logging as model_logging
                model_logger = logging.getLogger('transformers.modeling_utils')
                progress_enabled = model_logging.is_progress_bar_enabled()
                model_logger.addFilter(_actionable_model_log)
                model_logging.disable_progress_bar()
                try:
                    _model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cpu")
                finally:
                    model_logger.removeFilter(_actionable_model_log)
                    if progress_enabled:
                        model_logging.enable_progress_bar()
    return _model


def _package_version():
    try:
        return version("sentence-transformers")
    except PackageNotFoundError:
        return "missing"


def _fingerprint(texts):
    package_version = _package_version()
    payload = json.dumps({"model": MODEL_NAME, "revision": MODEL_REVISION,
                          "packageVersion": package_version, "texts": texts},
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _encode(texts):
    if not texts:
        return np.empty((0, 384), dtype=np.float32)
    return np.asarray(_model_instance().encode(
        texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True,
        normalize_embeddings=True,
    ), dtype=np.float32)


def _entry_vectors(texts, progress=None):
    fingerprint = _fingerprint(texts)
    path = CACHE_DIRECTORY / f"exercise_embeddings_{fingerprint}.npz"
    with _cache_lock:
        try:
            with np.load(path, allow_pickle=False) as cached:
                vectors = cached["vectors"]
                if (cached["fingerprint"].item() == fingerprint
                        and cached["model"].item() == MODEL_NAME
                        and cached["revision"].item() == MODEL_REVISION
                        and cached["packageVersion"].item() == _package_version()
                        and vectors.shape == (len(texts), MODEL_DIMENSION)
                        and vectors.dtype == np.float32
                        and np.isfinite(vectors).all()
                        and np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)):
                    return vectors
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile):
            pass

        if progress:
            progress(0, 1)
        vectors = _encode(texts)
        if (vectors.shape != (len(texts), MODEL_DIMENSION) or not np.isfinite(vectors).all()
                or not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)):
            raise ValueError("Local semantic model returned an invalid exercise index")
        CACHE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with temp_path.open("wb") as output:
                np.savez_compressed(output, fingerprint=np.asarray(fingerprint), model=np.asarray(MODEL_NAME),
                                    revision=np.asarray(MODEL_REVISION), packageVersion=np.asarray(_package_version()),
                                    vectors=vectors)
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
        if progress:
            progress(1, 1)
        return vectors


def _entry_text(entry):
    def words(value):
        if isinstance(value, dict):
            value = value.get("primary", [])
        if isinstance(value, str):
            return [value]
        return value if isinstance(value, list) else []

    name = entry.get("name") or ""
    equipment = entry.get("equipmentName") or ""
    accessories = words(entry.get("accessoryNames"))
    muscles = entry.get("muscleGroups", [])
    secondary = entry.get("secondaryMuscleGroups", [])
    return (f"Exercise: {name}. Equipment: {equipment}. Required accessories: {', '.join(accessories)}. "
            f"Primary training muscles: {', '.join(words(muscles))}. Secondary training muscles: {', '.join(words(secondary))}. "
            f"Category: {entry.get('exerciseCategory') or ''}. Movement identity: {entry.get('movementRef') or ''}.")


def _query_text(query):
    if not isinstance(query, str):
        return str(query)
    try:
        structured = json.loads(query)
    except (TypeError, ValueError):
        return query
    if isinstance(structured, dict) and isinstance(structured.get("candidate"), dict):
        return _entry_text(structured["candidate"])
    return query


def rank(queries, entries, progress=None):
    """Return complete cosine rankings as query -> {entry index: score}."""
    if not queries or not entries:
        return [{} for _ in queries]
    corpus = [_entry_text(entry) for entry in entries]
    entry_vectors = _entry_vectors(corpus, progress)
    query_vectors = _encode([_query_text(query) for query in queries])
    similarities = query_vectors @ entry_vectors.T
    return [
        {int(index): float(score) for index, score in enumerate(row)}
        for row in similarities
    ]
