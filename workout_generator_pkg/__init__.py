"""Workout generator package."""

__all__ = ["main"]


def main():
    from .cli import main as _main

    return _main()
