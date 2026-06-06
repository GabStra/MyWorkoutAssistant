from __future__ import annotations

import inspect
from collections import namedtuple


def ensure_legacy_inspect_getargspec() -> None:
    if hasattr(inspect, "getargspec"):
        return

    arg_spec = namedtuple("ArgSpec", ["args", "varargs", "keywords", "defaults"])

    def _getargspec(func):
        full = inspect.getfullargspec(func)
        return arg_spec(full.args, full.varargs, full.varkw, full.defaults)

    inspect.getargspec = _getargspec  # type: ignore[attr-defined]


def ensure_legacy_numpy_aliases() -> None:
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return

    aliases = {
        "bool": bool,
        "int": int,
        "float": float,
        "complex": complex,
        "object": object,
        "unicode": str,
        "str": str,
    }
    for alias, target in aliases.items():
        if not hasattr(np, alias):
            setattr(np, alias, target)


def ensure_legacy_smpl_runtime_compat() -> None:
    ensure_legacy_numpy_aliases()
    ensure_legacy_inspect_getargspec()
