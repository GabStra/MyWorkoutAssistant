"""Read historical reconstruction metadata without rewriting retained artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def normalize_reconstruction_metadata(value: Any) -> Any:
    if isinstance(value, list):
        return [normalize_reconstruction_metadata(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {}
    for key, item in value.items():
        current_key = (
            key.replace("WHAM", "RECONSTRUCTION")
            .replace("Wham", "Reconstruction")
            .replace("wham", "reconstruction")
            if isinstance(key, str) else key
        )
        # An explicitly current field takes precedence over an old alias.
        if current_key != key and current_key in value:
            continue
        normalized[current_key] = normalize_reconstruction_metadata(item)
    return normalized


def loads_reconstruction_metadata(*args: Any, **kwargs: Any) -> Any:
    return normalize_reconstruction_metadata(json.loads(*args, **kwargs))


def retained_reconstruction_path(path: Path) -> Path:
    """Prefer a current artifact, then its historical WHAM-named counterpart."""
    if path.exists():
        return path
    legacy = Path(*(
        part.replace("reconstruction", "wham", 1)
        if part in {"reconstruction", "reconstruction-cache", "reconstruction_spinepose"}
        or part.startswith(("reconstruction.", "reconstruction_output.", "reconstruction_inference_"))
        else part
        for part in path.parts
    ))
    return legacy if legacy.exists() else path
