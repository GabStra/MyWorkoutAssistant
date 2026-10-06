"""Heuristic parser: raw WOD text -> WodIR.

The gym publishes formulaic CrossFit-style text (AMRAPs, EMOMs, rounds-for-time,
timed Hyrox blocks, chippers, interval ON/OFF schemes). This parser recognizes
those constructs line-by-line; anything it cannot classify lands in WodIR.unparsed
so callers can see exactly what was dropped — nothing is silently lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_BULLET_RE = re.compile(r"^[\s•·\-*]*[•·]\s*|\s*[•·]\s*")
_NOISE_LINES = {"wod", "wod:", "metcon", "conditioning", "alternate:", "alternate", "alt. between:"}
# Title-case prose lines that are section headers, not movements. Deliberately a
# whitelist: a generic "Title Case without digits" rule would swallow real
# movement lines like "Max Effort Double Unders".
_SECTION_HEADERS = {"strength & gymnastics", "hyrox prep", "lifting club", "the bip"}
_SECTION_HINT_RE = re.compile(r"^[A-Z][A-Za-z&' ]{2,40}$")
_FROM_RANGE_RE = re.compile(r"from\s+(\d+(?:[.,]\d+)?)\s*'?\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*'", re.I)
_EMOM_RE = re.compile(r"emom\s+(\d+(?:[.,]\d+)?)\s*'", re.I)
_ROUNDS_FOR_TIME_RE = re.compile(r"(\d+)\s+rounds?\s+for\s+time", re.I)
_AMRAP_RE = re.compile(r"^\s*(?:\w\)\s*)?amrap\b", re.I)
_INTERVALS_RE = re.compile(r"(\d+)\s+intervals?\s*[–,-]?\s*(\d+(?:[.,]\d+)?)\s*'\s*on\s*(?::|/)\s*(\d+(?:[.,]\d+)?)\s*'\s*off", re.I)
_TEAM_RE = re.compile(r"in team of \d", re.I)
_FOR_TIME_RE = re.compile(r"^for time\b", re.I)
_CAP_RE = re.compile(r"time\s*cap[:\s]*(\d+(?:[.,]\d+)?)\s*'", re.I)
_IN_CAP_RE = re.compile(r"in\s+(\d+(?:[.,]\d+)?)\s*'\s*time\s*cap", re.I)
_THEN_RE = re.compile(r"^then\b|^then\s*[-–]", re.I)
_REST_LINE_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*'\s*rest\b", re.I)
_SLOT_RE = re.compile(r"^(\d)\)\s*(.*)$")
_LABEL_RE = re.compile(r"^([AB])\)\s*(.*)$")
_BARE_LABEL_RE = re.compile(r"^([AB])$")
_REP_PREFIX_RE = re.compile(r"^(\d+)(?:\s*/\s*(\d+))?\s*(cal|mt|m|meter|metres|meters)?\s+(.+)$", re.I)
_MAX_PREFIX_RE = re.compile(r"^max(?:\s+(cal\b|mt\b|m\b|meters?\b))?(?:\s+effort)?\s*(.*)$", re.I)
_REP_SUFFIX_RE = re.compile(r"(\d+)(?:\s*[-–]\s*(\d+))?\s*reps?\b", re.I)
_WEIGHT_HINT_RE = re.compile(r"@\s*([0-9].*|.*%.*1\s*rm.*)$", re.I)
_LEAD_WEIGHT_RE = re.compile(r"@\s*(.+)$")
_SPLIT_PLUS_RE = re.compile(r"\s+\+\s+")
_SPLIT_DASH_RE = re.compile(r"\s+-\s+")
_TIME_SPLIT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*'\s*([A-Za-z][^+]*?)(?=\s*\+|$)")
_FIND_HEAVY_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*'\s*to find a heavy\s+(.+)$", re.I)
_REPS_TOKEN_RE = re.compile(r"\breps?\b", re.I)


@dataclass
class Movement:
    raw: str
    name: str
    reps: int | None = None
    reps_text: str | None = None
    unit: str = "reps"  # reps | m | cal
    weight_hint: str | None = None
    sub_splits_seconds: list[int] | None = None  # e.g. bike: [60, 60] standing+seated
    max_effort: bool = False
    note: str | None = None
    rest_seconds: int | None = None


@dataclass
class Block:
    kind: str  # timed | amrap | rft | emom | chipper | rest
    movements: list[Movement] = field(default_factory=list)
    label: str | None = None
    rounds: int | None = None
    minutes: float | None = None  # emom length or timed block duration
    start_min: float | None = None
    end_min: float | None = None
    cap_min: float | None = None
    on_minutes: float | None = None
    off_minutes: float | None = None
    note: str | None = None


@dataclass
class WodIR:
    date: str
    title: str
    wod_type: str
    blocks: list[Block] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


def _to_float(value: str) -> float:
    return float(str(value).replace(",", "."))


def _strip_bullet(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^[•·]\s*", "", line)
    return line.strip()


def _parse_movement(text: str) -> Movement | None:
    """Parses one movement line; returns None when it is not a movement."""
    raw = text.strip()
    if not raw:
        return None

    rest_match = _REST_LINE_RE.match(raw)
    if rest_match:
        rest = Movement(raw=raw, name="rest", rest_seconds=int(_to_float(rest_match.group(1)) * 60))
        tail = raw[rest_match.end():].lstrip(" ,-–")
        tail = re.sub(r"^then\b\s*[-–,:]?\s*", "", tail, flags=re.I)
        if tail:
            tail_movement = _parse_movement(tail)
            if tail_movement:
                return [rest] + (tail_movement if isinstance(tail_movement, list) else [tail_movement])
        return rest

    find_heavy = _FIND_HEAVY_RE.search(raw)
    if find_heavy:
        return Movement(
            raw=raw,
            name=find_heavy.group(2).strip(),
            reps=1,
            max_effort=True,
            note=f"{find_heavy.group(1)}' to find heavy",
        )

    # Weight hint is always stripped (even when the line also carries "rep"),
    # so names stay clean; "% of 1 rm" hints are preserved verbatim.
    weight_hint = None
    body = raw
    weight_match = _LEAD_WEIGHT_RE.search(body)
    if weight_match:
        weight_hint = weight_match.group(1).strip()
        body = body[: weight_match.start()].strip()

    sub_splits = None
    time_splits = _TIME_SPLIT_RE.findall(body)
    if "'" in body and len(time_splits) >= 2:
        sub_splits = [int(_to_float(minutes) * 60) for minutes, _ in time_splits]
        first_match = re.search(r"\d+(?:[.,]\d+)?'\s*\w", body)
        prefix = body[: first_match.start()].strip(" -–") if first_match else ""
        parts = " - ".join(part.strip() for _, part in time_splits)
        body = f"{prefix} ({parts})".strip() if prefix else parts

    max_effort = False
    reps = None
    reps_text = None
    unit = "reps"
    name_part = body

    max_match = _MAX_PREFIX_RE.match(body)
    if max_match:
        max_effort = True
        unit_token = (max_match.group(1) or "").lower()
        if unit_token.startswith("cal"):
            unit = "cal"
        elif unit_token:
            unit = "m"
        name_part = max_match.group(2).strip() or body

    prefix = _REP_PREFIX_RE.match(body)
    if prefix and not max_effort:
        first, second, unit_token, rest_of_line = prefix.groups()
        # "24/20" is the male/female pairing: default to the first (male) value.
        reps = int(first)
        if second:
            reps_text = f"{first}-{second}"
        if unit_token and unit_token.lower() in ("cal",):
            unit = "cal"
        elif unit_token:
            unit = "m"
        name_part = rest_of_line.strip()
    else:
        suffix = _REP_SUFFIX_RE.search(body)
        if suffix:
            reps = int(suffix.group(1))
            if suffix.group(2):
                reps_text = f"{suffix.group(1)}-{suffix.group(2)}"
                reps = int(suffix.group(2))
            name_part = (body[: suffix.start()].strip() + " " + body[suffix.end():].strip()).strip()

    # Compound lines: "20 gtoh plate + 20 mt shuttle run",
    # "24/20 cal row - 150 mt farmers carry"
    for splitter in (_SPLIT_PLUS_RE, _SPLIT_DASH_RE):
        if splitter.search(name_part) and reps is not None and not sub_splits:
            left, right = splitter.split(name_part, maxsplit=1)
            first = _parse_movement(f"{reps}{' cal' if unit == 'cal' else ''} {left.strip()}".strip())
            second = _parse_movement(right.strip())
            if first and second and not isinstance(first, list) and not isinstance(second, list):
                first.raw = raw
                second.raw = raw
                if first.unit != "reps":
                    second.unit = second.unit if second.unit != "reps" else "reps"
                return [first, second]

    target_note = None
    target = re.search(r"\(target\s+([^)]+)\)", name_part, re.I)
    if target:
        target_note = f"target {target.group(1).strip()}"
        name_part = (name_part[: target.start()] + " " + name_part[target.end():]).strip()

    name = name_part.strip(" -–")
    if not name:
        return None
    if _REPS_TOKEN_RE.search(name) and reps is None:
        name = _REPS_TOKEN_RE.sub("", name).strip()

    movement = Movement(
        raw=raw,
        name=name,
        reps=reps,
        reps_text=reps_text,
        unit=unit,
        weight_hint=weight_hint,
        sub_splits_seconds=sub_splits,
        max_effort=max_effort,
        note=target_note,
    )
    return movement if (reps or max_effort or unit != "reps" or sub_splits) else None


def parse_wod(text: str, date: str = "", title: str = "", wod_type: str = "") -> WodIR:
    ir = WodIR(date=date, title=title, wod_type=wod_type)
    current: Block | None = None
    pending_label: str | None = None
    interval_rounds: int | None = None

    def close_block() -> None:
        nonlocal current
        if current and current.movements:
            ir.blocks.append(current)
        current = None

    for raw_line in text.splitlines():
        line = _strip_bullet(raw_line)
        if not line:
            continue
        lowered = line.lower().strip()

        if lowered in _NOISE_LINES:
            continue
        if lowered in _SECTION_HEADERS:
            continue
        if lowered.startswith("*") and "cap" not in lowered:
            continue
        if _SECTION_HINT_RE.match(line) and line.isupper() and not re.search(r"\d", line):
            continue

        from_match = _FROM_RANGE_RE.search(line)
        if from_match:
            close_block()
            start, end = _to_float(from_match.group(1)), _to_float(from_match.group(2))
            current = Block(kind="timed", start_min=start, end_min=end, minutes=end - start)
            rest_of_line = line[from_match.end():].strip(" -–:")
            if rest_of_line:
                movement = _parse_movement(rest_of_line)
                if movement:
                    current.movements.extend(movement if isinstance(movement, list) else [movement])
            continue

        emom_match = _EMOM_RE.search(line)
        if emom_match:
            close_block()
            current = Block(kind="emom", minutes=_to_float(emom_match.group(1)))
            continue

        intervals_match = _INTERVALS_RE.search(line)
        if intervals_match:
            close_block()
            interval_rounds = int(intervals_match.group(1))
            current = Block(
                kind="chipper",
                rounds=interval_rounds,
                on_minutes=_to_float(intervals_match.group(2)),
                off_minutes=_to_float(intervals_match.group(3)),
                note="intervals — ON/OFF timed by athlete",
            )
            continue

        rft_match = _ROUNDS_FOR_TIME_RE.search(line)
        if rft_match:
            close_block()
            current = Block(kind="rft", rounds=int(rft_match.group(1)))
            rest_of_line = line[rft_match.end():].strip(" :of")
            if rest_of_line:
                movement = _parse_movement(rest_of_line)
                if movement:
                    current.movements.extend(movement if isinstance(movement, list) else [movement])
            continue

        if _AMRAP_RE.match(lowered):
            inherited = None
            if current is not None and current.kind == "timed" and not current.movements:
                inherited = current  # "From 8'-12'" window whose content is the AMRAP
            close_block()
            label_match = _LABEL_RE.match(line)
            current = Block(
                kind="amrap",
                label=label_match.group(1) if label_match else pending_label,
                start_min=inherited.start_min if inherited else None,
                end_min=inherited.end_min if inherited else None,
                minutes=inherited.minutes if inherited else None,
                cap_min=inherited.minutes if inherited else None,
            )
            pending_label = None
            rest_of_line = re.sub(r"^\s*(?:\w\)\s*)?amrap\b\s*(of)?\s*[:\-]?\s*", "", line, flags=re.I)
            if rest_of_line.strip():
                movement = _parse_movement(rest_of_line.strip())
                if movement:
                    current.movements.extend(movement if isinstance(movement, list) else [movement])
            continue

        cap_match = _CAP_RE.search(line) or _IN_CAP_RE.search(line)
        if cap_match:
            cap = _to_float(cap_match.group(1))
            if current is not None:
                current.cap_min = cap
            else:
                current = Block(kind="chipper", cap_min=cap)
            if cap_match.re is _IN_CAP_RE:
                remainder = re.split(r"time\s*cap,?\s*perform:?\s*", line, maxsplit=1, flags=re.I)
                rest_of_line = remainder[1].strip() if len(remainder) > 1 else ""
            else:
                rest_of_line = line[: cap_match.start()].strip(" *") or line[cap_match.end():].strip(" *")
            if rest_of_line:
                movement = _parse_movement(rest_of_line)
                if movement:
                    current.movements.extend(movement if isinstance(movement, list) else [movement])
            continue

        bare_label_match = _BARE_LABEL_RE.match(line)
        if bare_label_match:
            pending_label = bare_label_match.group(1)
            continue

        label_match = _LABEL_RE.match(line)
        if label_match and not line[1:2].isdigit():
            label, remainder = label_match.group(1), label_match.group(2).strip()
            if remainder:
                movement = _parse_movement(remainder)
                if movement:
                    if current is None:
                        current = Block(kind="chipper")
                    current.movements.extend(movement if isinstance(movement, list) else [movement])
                    continue
            pending_label = label
            continue

        if _THEN_RE.match(lowered) or _TEAM_RE.search(lowered) or _FOR_TIME_RE.match(lowered):
            remainder = re.sub(r"^then\b\s*[-–,:]?\s*", "", line, flags=re.I)
            remainder = re.sub(r"^in team of \d,?\s*complete:?\s*", "", remainder, flags=re.I)
            remainder = re.sub(r"^for time:?\s*", "", remainder, flags=re.I).strip()
            # "then:" starts a follow-up section even with no inline movement.
            close_block()
            current = Block(kind="chipper")
            if remainder:
                movement = _parse_movement(remainder)
                if movement:
                    current.movements.extend(movement if isinstance(movement, list) else [movement])
            continue

        rest_in_line = _REST_LINE_RE.search(line)
        if rest_in_line and current is None:
            close_block()
            current = Block(kind="chipper")
            current.movements.append(
                Movement(raw=line, name="rest", rest_seconds=int(_to_float(rest_in_line.group(1)) * 60))
            )
            rest_tail = line[rest_in_line.end():].lstrip(" ,-–")
            if rest_tail:
                movement = _parse_movement(rest_tail)
                if movement:
                    current.movements.extend(movement if isinstance(movement, list) else [movement])
            continue

        slot_match = _SLOT_RE.match(line)
        if slot_match:
            movement = _parse_movement(slot_match.group(2))
            if movement:
                if current is None:
                    current = Block(kind="chipper")
                current.movements.extend(movement if isinstance(movement, list) else [movement])
                continue

        movement = _parse_movement(line)
        if movement:
            if current is None:
                current = Block(kind="chipper")
            current.movements.extend(movement if isinstance(movement, list) else [movement])
            continue

        ir.unparsed.append(line)

    close_block()
    return ir
