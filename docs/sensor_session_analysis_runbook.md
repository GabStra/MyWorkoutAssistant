# Sensor Session Capture → Analysis Runbook

How to get from a real workout to the offline analysis (rep counts, phases, 3D path,
per-exercise coverage map).

## On the watch (automatic)

Nothing to do. Motion capture runs during every workout by default (accelerometer,
gyroscope, rotation vector, heart rate, gravity, linear acceleration, pressure @ 50 Hz).
The session is gzipped when the workout completes and sent to the phone automatically
(with retries; a startup resend covers missed transfers).

Optional: "Motion dataset: On/Off" on the workout detail screen disables capture or
marks a session as deliberately started (stored as `userInitiated` in the session
metadata). Turning it off stops capture mid-workout (session is marked ABANDONED).

## Getting the session off the phone

1. Phone → drawer menu → **Advanced → Sensor sessions** — confirm the session arrived
   (list shows date, device, duration, segment count).
2. Open the session → **export icon (share)** in the top bar. The app zips the session
   into `Android/data/<pkg>/files/sensor_session_exports/<sessionId>.zip` and opens the
   system share sheet. Send it anywhere reachable from your PC (email, Drive, etc.).
   "Copy path" is still available for adb workflows.
3. Alternatively via adb (works for debug builds, or where shell can access app
   external files):

   ```bash
   adb pull /sdcard/Android/data/com.gabstra.myworkoutassistant/files/sensor_session_exports/
   ```

## Running the analysis on PC

```bash
pip install -e ".[analysis]"   # once: adds scipy + matplotlib
python -m motion_annotation_pkg.cli analyze-session --session-dir <unzipped-session-dir>
```

Outputs land in `<session-dir>/analysis/`:

- `metrics.json` — per-rep table, per-set metrics (rep count, tempo, phase durations,
  velocity/ROM proxies, drift), and the **coverage map**:
  - `coverage.by_exercise` / `coverage.by_exercise_type` — per movement class:
    sets analyzed, count error vs ground truth, tempo quality, low-confidence ids.
  - per set: `ground_truth_source` (`"event"` = reps you entered in the app; `"file"`
    = a provided gt.json), `detector_confidence.band` (high ≥ 0.7 / medium ≥ 0.4 / low).
- `<prefix>_trajectory.png` — phase-colored 3D wrist path per set.
- `<prefix>_timeseries.png` — raw vs filtered signals with rep boundaries.
- `<prefix>_path.csv` / `.npz` — reconstructed path for replays.

Optional: `--ground-truth-reps gt.json` (setId → reps) only as fallback; the app's
entered reps already ride inside each session as `SET_COMPLETED,actualReps` events.

## What to look at (honesty gates)

- Which movement classes reach **high band + small count error** — those are the
  candidates for live on-watch counting (Phase 4). Low-band classes are expected for
  machines/static-wrist lifts; that is the wrist-only physics boundary, not a bug.
- `drift` metrics per set: ZUPT-controlled double integration is bounded, not exact.
- A session where you entered no reps has no ground truth — enter reps normally
  during workouts; that IS the ground truth.
