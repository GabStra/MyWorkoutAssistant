"""Cooperative discovery turns, checkpointed at completed review boundaries."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DiscoveryBudget:
    candidate_limit: int = 0
    seconds_limit: float = 0.0
    checkpoint_path: Path | None = None
    signature: str = ""
    started_at: float = field(default_factory=time.monotonic)
    yield_path: Path | None = None
    consumed: int = 0
    reviewed: dict[str, dict[str, Any]] = field(default_factory=dict)

    def load(self) -> None:
        if self.checkpoint_path is None:
            return
        try:
            payload = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if payload.get("signature") == self.signature and isinstance(payload.get("reviewed"), dict):
                self.reviewed = payload["reviewed"]
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def remaining(self, batch_size: int) -> int:
        if self.yield_path is not None and self.yield_path.exists():
            return 0
        if self.seconds_limit > 0 and time.monotonic() - self.started_at >= self.seconds_limit:
            return 0
        if self.candidate_limit > 0:
            return max(0, min(batch_size, self.candidate_limit - self.consumed))
        return batch_size

    @property
    def exhausted(self) -> bool:
        return self.remaining(1) == 0

    def record(self, candidates: dict[str, dict[str, Any]]) -> None:
        self.consumed += len(candidates)
        self.reviewed.update(candidates)
        if self.checkpoint_path is not None:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.checkpoint_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"signature": self.signature, "reviewed": self.reviewed}), encoding="utf-8")
            temporary.replace(self.checkpoint_path)

    def remaining_seconds(self) -> float | None:
        if self.yield_path is not None and self.yield_path.exists():
            return 0.0
        if self.seconds_limit <= 0:
            return None
        return max(0.0, self.seconds_limit - (time.monotonic() - self.started_at))
