# Workout History MCP Server

Read-only FastMCP server for exposing a MyWorkoutAssistant `AppBackup` JSON to ChatGPT custom MCP connectors.

This v1 does not enforce authentication. Only use it with short-lived local/ngrok testing because anyone with the public URL can read the exposed workout history.

## Install

The easiest setup path is the PowerShell script:

```powershell
cd C:\Users\gabri\Documents\MyWorkoutAssistant
.\scripts\setup_workout_history_mcp.ps1
```

That creates `.venv` if needed, installs the MCP package, and prints the local connector URL.

To configure a custom backup path, host, or port:

```powershell
.\scripts\setup_workout_history_mcp.ps1 `
  -BackupPath "C:\Users\gabri\Downloads\workout_store_backup_2026-04-26_18-30-00.json" `
  -HostName "127.0.0.1" `
  -Port 8000
```

To install and immediately start the server:

```powershell
.\scripts\setup_workout_history_mcp.ps1 -StartServer
```

To install without a virtual environment:

```powershell
.\scripts\setup_workout_history_mcp.ps1 -NoVenv
```

To install only runtime dependencies, without pytest:

```powershell
.\scripts\setup_workout_history_mcp.ps1 -WithoutTestDependencies
```

## Configure

Configuration is read from environment variables in the shell that starts the server. The setup script sets these variables for its own PowerShell process before it starts the server. There is no config file for v1.

If you do nothing, the server reads this repo file:

```text
C:\Users\gabri\Documents\MyWorkoutAssistant\merged_workout_store_backup.json
```

To use a different phone-generated `AppBackup` JSON, set `MYWORKOUT_BACKUP_PATH` before starting the server:

```powershell
$env:MYWORKOUT_BACKUP_PATH = "C:\Users\gabri\Downloads\workout_store_backup_2026-04-26_18-30-00.json"
```

Optional bind settings:

```powershell
$env:MYWORKOUT_MCP_HOST = "127.0.0.1"
$env:MYWORKOUT_MCP_PORT = "8000"
```

Environment variables only apply to the current PowerShell window. If you open a new terminal, set them again before starting the server.

## Start

If you used `-StartServer`, the script already started it. Otherwise, after running the setup script, start it with the command printed by the script.

Manual start command:

```powershell
python -m workout_history_mcp.server
```

Keep this PowerShell window open while using the connector.

Local MCP endpoint:

```text
http://127.0.0.1:8000/mcp
```

## Expose With Ngrok

In a second PowerShell window, run:

```powershell
ngrok http 8000
```

Ngrok prints a public HTTPS forwarding URL. Add `/mcp` to that URL for ChatGPT:

```text
https://<ngrok-host>/mcp
```

Configure the connector with no authentication for this short-lived test setup.

## Quick Test

With the server installed, run:

```powershell
pytest tests/test_workout_history_mcp.py
```

## Exposed Data

The server exposes broad context as resources and targeted retrieval as tools:

- `workout-history://athlete`: athlete profile, training date range, totals, and equipment names.
- `workout-history://summary`: compact workout and exercise index.
- `workout-history://exercises`: searchable exercise index.
- `workout-history://current-plan`: active workouts, exercise prescriptions, progression settings, planned sets/rests, muscle groups, HR targets, and structured equipment.
- `list_workout_sessions`: paged completed sessions with duration, set counts, and heart-rate summary.
- `get_session_markdown`: one completed session by workout history id.
- `list_exercises`: exercises with ids, current config, planned sets, equipment, and history counts.
- `get_exercise_history_markdown`: chronological history for one exercise.

There is intentionally no full-history dump tool; use `list_workout_sessions` and `get_session_markdown` to fetch only the sessions needed.
