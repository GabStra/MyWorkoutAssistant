"""Progress persistence for resumable workout generation."""

from __future__ import annotations

import glob
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .paths import get_progress_dir


def save_generation_progress(
    session_id: str,
    step_number: int,
    step_data: Dict[str, Any],
    custom_prompt: str,
    conversation_hash: str,
    id_manager: Any,
    script_dir: Optional[str] = None,
    timing_data: Optional[Dict[str, Any]] = None,
    use_reasoner_for_emitting: Optional[bool] = None,
) -> Tuple[Optional[str], float]:
    """Save generation progress after a step completes."""
    save_start_time = time.time()
    try:
        progress_dir = get_progress_dir(script_dir)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        short_session_id = session_id[:8] if len(session_id) >= 8 else session_id
        filename = f"progress_{timestamp}_{short_session_id}.json"
        filepath = os.path.join(progress_dir, filename)

        progress_data: Dict[str, Any] = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "custom_prompt": custom_prompt,
            "conversation_hash": conversation_hash,
            "current_step": step_number,
            "id_manager_state": id_manager.get_state(),
        }

        if use_reasoner_for_emitting is not None:
            progress_data["use_reasoner_for_emitting"] = use_reasoner_for_emitting

        for step_key, step_value in step_data.items():
            progress_data[step_key] = step_value

        if timing_data:
            timing_copy = {
                "total_time_seconds": timing_data.get("total_time_seconds", 0.0),
                "step_times": timing_data.get("step_times", {}).copy(),
                "save_times": timing_data.get("save_times", []).copy(),
                "session_start_time": timing_data.get("session_start_time"),
                "last_step_time": datetime.now().isoformat(),
            }
            progress_data["timing"] = timing_copy

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=2, ensure_ascii=False)

        save_time = time.time() - save_start_time

        if timing_data is not None:
            if "save_times" not in timing_data:
                timing_data["save_times"] = []
            timing_data["save_times"].append(save_time)

        return filepath, save_time
    except Exception as e:
        print(f"Warning: Failed to save generation progress: {e}", file=os.sys.stderr)
        save_time = time.time() - save_start_time
        return None, save_time


def load_generation_progress(session_id: str, script_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load generation progress by session ID."""
    try:
        progress_dir = get_progress_dir(script_dir)

        pattern = os.path.join(progress_dir, f"progress_*_{session_id[:8]}*.json")
        matches = glob.glob(pattern)

        if not matches:
            pattern = os.path.join(progress_dir, f"progress_*_{session_id}.json")
            matches = glob.glob(pattern)

        if not matches:
            return None

        best_match = None
        best_step = -1

        for filepath in matches:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    progress_data = json.load(f)

                if "session_id" not in progress_data or "current_step" not in progress_data:
                    continue

                current_step = progress_data["current_step"]
                if current_step > best_step:
                    best_step = current_step
                    best_match = (filepath, progress_data)
            except Exception:
                continue

        if best_match is None:
            return None

        filepath, progress_data = best_match

        step_data = {}
        for key, value in progress_data.items():
            if key.startswith("step_"):
                step_data[key] = value

        timing_data = progress_data.get("timing")
        if timing_data is None:
            timing_data = {
                "total_time_seconds": 0.0,
                "step_times": {},
                "save_times": [],
                "session_start_time": progress_data.get("timestamp", datetime.now().isoformat()),
                "last_step_time": progress_data.get("timestamp", datetime.now().isoformat()),
            }

        return {
            "session_id": progress_data["session_id"],
            "current_step": progress_data["current_step"],
            "step_data": step_data,
            "custom_prompt": progress_data.get("custom_prompt", ""),
            "conversation_hash": progress_data.get("conversation_hash", ""),
            "id_manager_state": progress_data.get("id_manager_state", {}),
            "timing": timing_data,
            "filepath": filepath,
        }
    except Exception as e:
        print(f"Warning: Failed to load generation progress: {e}", file=os.sys.stderr)
        return None


def list_available_progress(script_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all available progress files."""
    progress_dir = get_progress_dir(script_dir)
    pattern = os.path.join(progress_dir, "progress_*.json")
    files = glob.glob(pattern)

    progress_list = []
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                progress_data = json.load(f)

            session_id = progress_data.get("session_id", "unknown")
            current_step = progress_data.get("current_step", -1)
            timestamp = progress_data.get("timestamp", "")

            progress_list.append(
                {
                    "session_id": session_id,
                    "short_id": session_id[:8] if len(session_id) >= 8 else session_id,
                    "timestamp": timestamp,
                    "current_step": current_step,
                    "filepath": filepath,
                    "status": "complete" if current_step >= 7 else "incomplete",
                }
            )
        except Exception:
            continue

    progress_list.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return progress_list


def delete_progress_file(session_id: str, script_dir: Optional[str] = None) -> bool:
    """Delete progress file(s) for a given session ID."""
    progress_dir = get_progress_dir(script_dir)

    pattern = os.path.join(progress_dir, f"progress_*_{session_id[:8]}*.json")
    matches = glob.glob(pattern)

    if not matches:
        pattern = os.path.join(progress_dir, f"progress_*_{session_id}.json")
        matches = glob.glob(pattern)

    if not matches:
        return False

    deleted = False
    for filepath in matches:
        try:
            os.remove(filepath)
            deleted = True
        except Exception:
            pass

    return deleted
