"""Maps parsed movements onto the app's exercise definitions and equipment.

Resolution order per movement:
1. synonym table (WOD slang -> canonical definition name)
2. exact/normalized-substring match against the user's exported library
3. auto-create a definition (and equipment when the movement implies a machine
   or implement), with deterministic uuid5 ids shared across all packages.

The library file is the user's export (exercise_libraries/*.json); it only supplies
existing ids — auto-created entries always merge cleanly on import.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

REPO = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = REPO / "exercise_libraries" / "exercise_library_2026-08-17_164507_with_movements.json"


def stable_id(kind: str, name: str) -> str:
    return str(uuid.uuid5(NS, f"myworkoutassistant:wod:{kind}:{name}"))


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


# WOD slang -> canonical definition name. Entries here intentionally include
# movements the library does not have yet; the auto-creator makes those.
SYNONYMS: list[tuple[str, str]] = [
    (r"\bgtoh\b.*\bplate|plate.*g2oh|ground.to.overhead", "Plate G2OH"),
    (r"\bshuttle", "Shuttle Run"),
    (r"\brow\b|\browing\b|\bcal.*row", "Rowing"),
    (r"\bbike\b|\bAB\b", "Bike Erg"),
    (r"\bski\s*erg", "Ski Erg"),
    (r"\bburpees?\b", "Burpee"),
    (r"\bwall\s*ball", "Wall Ball"),
    (r"\bbox\s*jump", "Box Jump"),
    (r"\bpush[\s-]?ups?\b|\bpushups?\b", "Push-Up"),
    (r"\bair\s*squat|\bsynchro\s*air\s*squat", "Air Squat"),
    (r"\bdouble\s*under|\bdubs\b", "Double Under"),
    (r"\bsled\s*push", "Sled Push"),
    (r"\bsled\s*pull", "Sled Pull"),
    (r"\bwall\s*walk", "Wall Walk"),
    (r"\bdevil\s*press", "Devil Press"),
    (r"\bbar\s*muscle[\s-]?up", "Bar Muscle-Up"),
    (r"\bmuscle[\s-]?up", "Bar Muscle-Up"),
    (r"\bfarmers?\s*carry|farmers?\s*walk", "Dumbbell Farmer's Walk"),
    (r"\btoes\s*to\s*(bar|kb)", "Toes-to-Bar"),
    (r"\bdeadlift", "Deadlift"),
    (r"\bpower\s*clean", "Power Clean"),
    (r"\bsquat\s*clean|\bclean\b", "Power Clean"),
    (r"\bsnatch", "Dumbbell Snatch"),
    (r"\bpush\s*jerk|split\s*jerk", "Push Jerk"),
    (r"\blunge", "Weighted Lunge"),
    (r"\brun\b|\brunning\b", "Run"),
    (r"\bpull[\s-]?ups?\b|\bpullups?\b", "Pull-Up"),
    (r"\bsit[\s-]?ups?\b", "Sit-Up"),
    (r"\bthruster", "Thruster"),
    (r"\bkettlebell\s*swing|\bkb\s*swing", "Kettlebell Swing"),
    (r"\bjump\s*rope", "Double Under"),
]

# Equipment implied by movement text; matched before per-movement equipment guesses.
_EQUIPMENT_HINTS: list[tuple[str, str, str]] = [
    (r"\brow\b", "Rower", "CARDIO_MACHINE"),
    (r"\bbike\b|\bAB\b", "Bike Erg", "CARDIO_MACHINE"),
    (r"\bski\s*erg", "Ski Erg", "CARDIO_MACHINE"),
    (r"\bwall\s*ball|\bmed\s*ball", "Medicine Ball", "GENERIC"),
    (r"\bplate\b", "Weight Plate", "GENERIC"),
    (r"\bkettlebell|\bkb\b", "Kettlebell", "GENERIC"),
    (r"\bsled\b", "Sled", "GENERIC"),
    (r"\bdbl?\b|\bdumbbell", "Dumbbell", "DUMBBELL"),
    (r"\bbarbell", "Barbell", "BARBELL"),
]

_MACHINE_NAME_RE = re.compile(r"\b(row|bike|ski|erg)\b", re.I)
_BARBELL_MOVEMENT_RE = re.compile(
    r"\b(deadlift|clean|snatch|jerk|press|thruster|squat|row|carry|lunge)\b", re.I
)

# Library variants that are NOT the default way to perform a generic WOD movement:
# "push ups" must not resolve to "Ring Push-Up", "burpees" not to "Weighted Burpee".
# "Barbell" is deliberately allowed (a gym WOD deadlift IS the barbell deadlift).
_EXCLUDED_QUALIFIERS = (
    "ring", "weighted", "incline", "decline", "feet", "feetelevated", "assisted",
    "rack", "rackassisted", "sa", "single", "singlearm", "cable", "smith", "band",
    "kettlebell", "seated", "nordic", "dumbbell", "dumbbells",
)


def _is_qualified_variant(library_key: str, canonical_key: str) -> bool:
    del canonical_key  # candidates starting with a qualifier token are variants
    return any(library_key.startswith(qualifier) for qualifier in _EXCLUDED_QUALIFIERS)


@dataclass
class DefinitionResolution:
    definition: dict          # full definition dict (existing or auto-created)
    equipment: dict | None    # auto-created equipment, None when existing/reused
    source: str               # "synonym" | "library" | "created"
    weight: float | None      # prescribed kg parsed from the hint, if any


@dataclass
class MovementMapper:
    library_path: Path = DEFAULT_LIBRARY
    definitions_by_name: dict[str, dict] = field(default_factory=dict)
    equipment_by_id: dict[str, dict] = field(default_factory=dict)
    created_definitions: dict[str, dict] = field(default_factory=dict)
    created_equipment: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.definitions_by_name or self.library_path is None:
            return
        with open(self.library_path, encoding="utf-8") as handle:
            library = json_load(handle)
        for definition in library.get("exerciseDefinitions", []):
            self.definitions_by_name[_normalize(definition["name"])] = definition
        for equipment in library.get("equipments", []):
            self.equipment_by_id[equipment["id"]] = equipment

    def resolve(self, movement_name: str, weight_hint: str | None) -> DefinitionResolution:
        cleaned = re.sub(r"\b(synchro|kipping|strict|alternating|alt\.?|one|single)\b", " ", movement_name, flags=re.I)
        cleaned = re.sub(r"\bdbl?s?\b", "dumbbell", cleaned, flags=re.I)
        normalized = _normalize(cleaned)

        for pattern, canonical in SYNONYMS:
            if re.search(pattern, movement_name, re.I):
                return self._resolve_canonical(canonical, weight_hint, movement_name)

        if normalized in self.definitions_by_name:
            return DefinitionResolution(self.definitions_by_name[normalized], None, "library", self._prescribed_weight(weight_hint))

        for key, definition in self.definitions_by_name.items():
            if len(normalized) >= 5 and (normalized in key or key in normalized):
                return DefinitionResolution(definition, None, "library", self._prescribed_weight(weight_hint))

        canonical = _title_case(cleaned)
        return self._resolve_canonical(canonical, weight_hint, movement_name)

    def _resolve_canonical(self, canonical: str, weight_hint: str | None, raw: str) -> DefinitionResolution:
        key = _normalize(canonical)
        if key in self.definitions_by_name:
            return DefinitionResolution(self.definitions_by_name[key], None, "synonym", self._prescribed_weight(weight_hint))

        # Prefer an existing library variant of the canonical movement
        # ("Deadlift" -> "Barbell Deadlift") over creating a duplicate,
        # excluding qualified variants the WOD did not ask for.
        candidates = [
            d for k, d in self.definitions_by_name.items()
            if key and key in k and not _is_qualified_variant(k, key)
        ]
        if candidates:
            best = min(candidates, key=lambda d: len(_normalize(d["name"])))
            return DefinitionResolution(best, None, "library", self._prescribed_weight(weight_hint))

        equipment, weight = self._implied_equipment(canonical, raw, weight_hint)
        exercise_type, body_weight_percentage = self._implied_type(canonical, equipment, raw)
        definition = {
            "id": stable_id("definition", canonical),
            "name": canonical,
            "exerciseType": exercise_type,
            "equipmentId": equipment["id"] if equipment else None,
            "bodyWeightPercentage": body_weight_percentage,
            "requiredAccessoryEquipmentIds": [],
            "muscleGroups": [],
            "secondaryMuscleGroups": [],
            "exerciseCategory": None,
        }
        self.created_definitions[key] = definition
        self.definitions_by_name[key] = definition
        return DefinitionResolution(definition, equipment, "created", weight)

    def _implied_equipment(self, canonical: str, raw: str, weight_hint: str | None) -> tuple[dict | None, float | None]:
        for pattern, equipment_name, equipment_type in _EQUIPMENT_HINTS:
            if re.search(pattern, raw, re.I):
                return self._equipment(equipment_name, equipment_type), self._prescribed_weight(weight_hint)
        if _MACHINE_NAME_RE.search(canonical):
            return self._equipment(_title_case(_MACHINE_NAME_RE.search(canonical).group(1)) + " Erg" if _MACHINE_NAME_RE.search(canonical).group(1).lower() == "ski" else canonical, "CARDIO_MACHINE"), None
        if _BARBELL_MOVEMENT_RE.search(canonical) and re.search(r"\bbars?\b|@\s*\d", raw, re.I):
            return self._equipment("Barbell", "BARBELL"), self._prescribed_weight(weight_hint)
        return None, self._prescribed_weight(weight_hint)

    def _implied_type(self, canonical: str, equipment: dict | None, raw: str) -> tuple[str, float | None]:
        if equipment and equipment["type"] == "CARDIO_MACHINE":
            return "COUNTDOWN", None
        if equipment and equipment["type"] in ("GENERIC", "BARBELL", "DUMBBELL", "DUMBBELLS", "MACHINE"):
            return "WEIGHT", None
        if re.search(r"\brun\b|\bsprint|\bshuttle", canonical, re.I):
            return "BODY_WEIGHT", 100.0
        return "BODY_WEIGHT", 0.0

    def _equipment(self, name: str, equipment_type: str) -> dict:
        key = _normalize(name)
        if key in self.created_equipment:
            return self.created_equipment[key]
        for equipment in self.equipment_by_id.values():
            if _normalize(equipment["name"]) == key and equipment["type"] == equipment_type:
                return equipment
        equipment = {"id": stable_id("equipment", name), "type": equipment_type, "name": name}
        self.created_equipment[key] = equipment
        self.equipment_by_id[equipment["id"]] = equipment
        return equipment

    @staticmethod
    def _prescribed_weight(weight_hint: str | None) -> float | None:
        if not weight_hint:
            return None
        match = re.match(r"\s*(\d+(?:[.,]\d+)?)", weight_hint)
        if not match:
            return None
        return float(match.group(1).replace(",", "."))


def _title_case(text: str) -> str:
    words = re.sub(r"[^A-Za-z0-9\s/-]", " ", text).split()
    titled = []
    for index, word in enumerate(words):
        if word.lower() in ("to", "the", "and", "of") and index > 0:
            titled.append(word.lower())
        else:
            titled.append(word[0].upper() + word[1:] if word else word)
    name = " ".join(titled)
    return re.sub(r"\s+", " ", name).strip()


def json_load(handle) -> dict:
    import json

    return json.load(handle)
