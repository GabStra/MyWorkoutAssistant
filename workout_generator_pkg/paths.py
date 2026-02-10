"""Path utilities for workout generator runtime files."""

from __future__ import annotations

import os
from typing import Optional


def get_progress_dir(script_dir: Optional[str] = None) -> str:
    """
    Get the directory path for generation progress files.

    Args:
        script_dir: Directory where script is located (defaults to current directory)

    Returns:
        str: Path to progress directory
    """
    if script_dir is None:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except (NameError, AttributeError):
            script_dir = os.getcwd()

    progress_dir = os.path.join(script_dir, "workouts", "generation_progress")
    os.makedirs(progress_dir, exist_ok=True)
    return progress_dir


def get_log_dir(script_dir: Optional[str] = None) -> str:
    """
    Get the directory path for conversation log files.

    Args:
        script_dir: Directory where script is located (defaults to current directory)

    Returns:
        str: Path to logs directory
    """
    if script_dir is None:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except (NameError, AttributeError):
            script_dir = os.getcwd()

    log_dir = os.path.join(script_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def conversation_meta_path(script_dir: Optional[str] = None) -> str:
    """Get path to conversation metadata file."""
    if script_dir is None:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except (NameError, AttributeError):
            script_dir = os.getcwd()
    return os.path.join(script_dir, "conversation_meta.json")
