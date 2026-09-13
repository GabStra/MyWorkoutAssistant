"""Phase topology shared by cycle proposals and repetition validation."""
import math


def major_phase_runs(values):
    if len(values) < 5 or not all(math.isfinite(float(value)) for value in values):
        return []
    minimum, maximum = min(values), max(values)
    span = maximum - minimum
    if span <= 1e-8:
        return []
    runs = []
    for index, value in enumerate(values):
        ratio = (value - minimum) / span
        phase = 'low' if ratio <= .30 else 'high' if ratio >= .70 else None
        if phase is not None:
            if not runs or runs[-1][0] != phase:
                runs.append([phase, index, index])
            else:
                runs[-1][2] = index
    return runs


def major_phase_sequence(values):
    return [phase for phase, _start, _end in major_phase_runs(values)]


def complete_repetition(values, *, exactly_one=True):
    """Recognize extreme-to-extreme returns and continuous mid-phase returns.

    A mid-phase start visits only two extreme bands. Require close endpoints,
    equal direction at the seam and a full excursion on both sides of it;
    visiting both extremes alone does not establish a repetition.
    """
    sequence = major_phase_sequence(values)
    count = len(sequence)
    if count >= 3:
        # A source may contain a complete return followed by more motion.
        # Only the selected output must contain exactly one repetition.
        return (count == 3 if exactly_one else True), sequence
    if count != 2:
        return False, sequence
    span = max(values) - min(values)
    start = (values[0] - min(values)) / span
    end = (values[-1] - min(values)) / span
    window = max(1, round((len(values) - 1) * .08))
    entry = values[window] - values[0]
    exit_delta = values[-1] - values[-1 - window]
    passed = (.30 < start < .70 and .30 < end < .70
              and abs(start - end) <= .10
              and entry * exit_delta > 0
              and min(abs(entry), abs(exit_delta)) > .01 * span)
    return passed, sequence
