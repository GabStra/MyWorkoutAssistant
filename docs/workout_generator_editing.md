# Editing a generated workout

Open a separate editing copy from the shell:

```text
/edit
/edit <conversation_id>
/edit "C:\plans\workout_plan.json"
/edit "C:\plans\workouts\conversation_sessions\<id>\messages.json"
```

`/edit` uses the current saved complete plan, or the latest complete conversation if the current one has no plan. `/list-conversations` shows saved IDs. An exported JSON must be the original file linked to its saved generator conversation. The loader checks its exercises, prescriptions, order and rests against that saved plan; it does not silently import modifications made outside the generator.

You can also open it when starting the script:

```powershell
python workout_generator.py --edit-plan "C:\plans\workout_plan.json"
```

New conversations remember the library, history-backup and equipment file paths used to generate them. `--edit-plan` reuses those paths and the selected user profile. Older conversations without saved paths need the inputs supplied explicitly:

```powershell
python workout_generator.py --edit-plan "C:\plans\workout_plan.json" --exercise-library-file "C:\plans\library.json" --history-backup-file "C:\plans\history.json" --require-load-calibration
```

The same full library/equipment is required to preserve saved exercise references. A partial exercise list from an exported workout is not a substitute for the original full library. Keep its conversation folder and original input files available.

Once loaded, describe the change normally, for example:

- “Replace floor press with bench press everywhere; keep the rest of the plan.”
- “Move calf raises to the first session and check the session balance again.”
- “Change this exercise's rep range to 8–12.”
- “Make these sessions shorter while preserving my movement coverage.”
- “Change my preferred session budget to 60 minutes.”

Use `/view` to inspect the saved preview. The existing editor preserves untouched prescriptions, retrieves evidence for replacements, and rechecks the whole week. Requirement changes use the existing requirements review and approval process. Questions can be answered without mutating the plan.

The original conversation and export remain separate. Edits are saved under a new conversation ID, which can later be reopened with `/resume-conversation <id>`. The edited workout must pass current audit/review and receive fresh `CONFIRM GENERATE` before a new export. `/clear` starts a fresh generation instead.

This entry point loads generator plans with their saved context. It does not infer missing requirements or history from an arbitrary third-party workout JSON.
