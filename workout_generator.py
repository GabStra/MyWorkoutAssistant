"""Compatibility shim for legacy single-file imports and CLI execution.

This module re-exports public symbols from `workout_generator_pkg.cli`
so existing imports keep working.
"""

from workout_generator_pkg.cli import *  # noqa: F401,F403

if __name__ == "__main__":
    main()
