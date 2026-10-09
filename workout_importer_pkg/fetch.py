"""Fetches WOD entries from the GymAutoBook dashboard endpoint.

The GymAutoBook Windows service (separate project) exposes GET /api/wod?date=...
on 127.0.0.1:8787, guarded by a Host check and an X-Requested-With header. The
response carries the whole published window, so one fetch serves a date range.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

DASHBOARD_BASE = "http://127.0.0.1:8787"
DASHBOARD_HEADERS = {"X-Requested-With": "dashboard", "Host": "127.0.0.1:8787"}


@dataclass(frozen=True)
class WodEntry:
    board: str
    title: str
    wod_type: str
    text: str


def fetch_wod_window(date_iso: str, base_url: str = DASHBOARD_BASE) -> dict[str, list[WodEntry]]:
    """Returns {yyyy-mm-dd: [WodEntry, ...]} covering the gym's published window."""
    url = f"{base_url}/api/wod?date={date_iso}"
    request = urllib.request.Request(url, headers=DASHBOARD_HEADERS)
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"GymAutoBook /api/wod returned ok=false for {date_iso}")
    window: dict[str, list[WodEntry]] = {}
    for day, entries in payload.get("days", {}).items():
        window[day] = [
            WodEntry(
                board=entry.get("board", ""),
                title=entry.get("title", "WOD"),
                wod_type=entry.get("type", ""),
                text=(entry.get("text") or "").strip(),
            )
            for entry in entries
            if (entry.get("text") or "").strip()
        ]
    return window


def fetch_wod(date_iso: str, base_url: str = DASHBOARD_BASE) -> WodEntry:
    """Returns the primary WOD entry for one date (longest text wins)."""
    entries = fetch_wod_window(date_iso, base_url).get(date_iso) or []
    if not entries:
        raise RuntimeError(f"No WOD published for {date_iso}")
    return max(entries, key=lambda entry: len(entry.text))
