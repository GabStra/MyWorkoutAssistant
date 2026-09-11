"""Requirements derived from the requested name, never from model assertions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Literal


@dataclass(frozen=True)
class ContractField:
    value: Any
    origin: Literal["exercise_name", "generated_expectation"]
    required: bool
    evidence: str


def contract_field_authority(exercise_name: str, generated: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = {key: ContractField(value, "generated_expectation", False, "")
              for key, value in generated.items()}
    name = re.sub(r"[-_]", " ", exercise_name.lower())
    # Implement count and acting limb count are different: one dumbbell may be held in two hands.
    for key, pattern, value in (
        ("implementCount", r"\bsingle\s+(?:dumbbell|kettlebell)\b", 1),
        ("actingArmCount", r"\b(?:single|one)\s+arm\b|\bone\s+handed\b", 1),
    ):
        match = re.search(pattern, name)
        if match:
            fields[key] = ContractField(value, "exercise_name", True, match.group())
    return {key: asdict(value) for key, value in fields.items()}
