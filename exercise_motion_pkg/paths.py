from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def slugify(value: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return collapsed or "exercise-motion"


@dataclass(frozen=True)
class PipelinePaths:
    root: Path
    input_dir: Path
    raw_dir: Path
    cleaned_dir: Path
    preview_dir: Path
    logs_dir: Path

    @classmethod
    def create(cls, workspace: Path, exercise_slug: str) -> "PipelinePaths":
        root = workspace / slugify(exercise_slug)
        input_dir = root / "input"
        raw_dir = root / "raw"
        cleaned_dir = root / "cleaned"
        preview_dir = root / "preview"
        logs_dir = root / "logs"
        for path in (root, input_dir, raw_dir, cleaned_dir, preview_dir, logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            input_dir=input_dir,
            raw_dir=raw_dir,
            cleaned_dir=cleaned_dir,
            preview_dir=preview_dir,
            logs_dir=logs_dir,
        )
