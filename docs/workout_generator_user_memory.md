# Workout generator user memory

User memory is an optional, profile-scoped store of durable facts and preferences. The workout history MCP exposes it read-only through `workout-history://user-memory` and `get_user_memory(kind?)`; it has no write operation. The generator can read an explicitly selected profile with `MYWORKOUT_PROFILE_ID` or `--user-profile`.

## Create and bind a profile

Create a profile with the local memory command:

```powershell
python -m workout_user_memory create "My profile"
```

The command prints its profile UUID. Bind the current backup explicitly so later history access resolves to that profile:

```powershell
python -m workout_user_memory bind-history <PROFILE_UUID> "$env:MYWORKOUT_BACKUP_PATH"
```

For a generator run, select a profile directly:

```powershell
$env:MYWORKOUT_PROFILE_ID = "<PROFILE_UUID>"
python workout_generator.py --user-profile "$env:MYWORKOUT_PROFILE_ID" --history-backup-file "$env:MYWORKOUT_BACKUP_PATH"
```

The MCP accepts an explicit `MYWORKOUT_PROFILE_ID` and/or the backup's `bind-history` association. If both are present, they must identify the same profile. With neither, memory is unconfigured and returns no facts. It never guesses identity from a name, measurements, or workout history. A path binding records which profile owns that path; it cannot detect if someone later replaces the file with another person's backup, so rebind only after verifying ownership. Set `MYWORKOUT_USER_MEMORY_DIR` to use a non-default memory-store root.

## Review and manage facts

Show a profile and review its facts against the current library before using them:

```powershell
python -m workout_user_memory show <PROFILE_UUID> --library <CURRENT_LIBRARY_JSON>
```

The store supports `shared_station` and `setup_access` facts about equipment and exercise setup, plus `standing_restriction` and `standing_preference` text. Record only information the user explicitly confirmed. For example:

```powershell
python -m workout_user_memory confirm --profile <PROFILE_UUID> --kind standing_preference --value '"Keep exercises consistent enough to track progress."' --source 'Keep exercises consistent enough to track progress.'
```

Equipment facts describe stable, verifiable setup; restrictions and preferences describe how training should be designed. Generator-run approvals authorize one specific generated plan or action and must remain separate from durable memory. A remembered preference does not approve a run.

With a profile selected, the generator automatically saves new typed physical facts only after the existing independent decision/source review passes. It does not automatically save delegated programming choices, model guesses, exercise capability assumptions or approvals. Use the explicit local `confirm` command for standing preferences/restrictions. Those become source-backed intake context, not an automatic rewrite of approved numerical requirements.

Physical `confirm` commands require `--library` with the current library or AppBackup JSON. Their values use stable resource/definition IDs: `shared_station` takes a resource-ID array; `setup_access` takes an object with `independentDefinitionIds` and `retainedResourceIds`. Names and unrelated history/load updates do not invalidate a fact; changed dependencies are surfaced for clarification. Existing confirmed facts are applied natively, without another model request to reconstruct their identity or quantity.

The generator injects only the current profile's scoped fact summaries. Original statements and question context remain in the local store and can be inspected through the CLI or read-only MCP. Historical physical confirmations do not reintroduce old workout goals from their original intake. Current user instructions can correct memory, but a conflicting physical assertion requires explicit supersession or forgetting before it replaces the stored fact.

Use `show` to review the source and current status. Scoped equipment facts are returned as unavailable when their referenced library configuration changes; MCP includes those in `unavailableFacts`. Explicitly confirm corrections or replacements. Supersede an active fact when confirming its replacement, and forget a fact that should no longer be used:

```powershell
python -m workout_user_memory forget <PROFILE_UUID> <FACT_UUID>
```

To supersede a fact, repeat `confirm` with `--supersedes <OLD_FACT_UUID>`.

Treat MCP results as read-only context. Ask the generator to surface relevant facts for review when a remembered item could materially affect the plan; the MCP cannot confirm, edit, or forget facts.

In the generator shell, `/memory` shows the selected profile's facts, `/memory reload` refreshes them, and `/memory forget FACT_UUID` forgets one fact. Forgetting removes it from the active profile store; it does not rewrite retained conversation transcripts.

Changed memory requires the requirements to be checked and approved against the current context. `/clear` starts with current memory and leaves prior conversation decisions behind. `/clear keep-requirements` preserves memory as historical facts rather than manufacturing user turns, and requires reapproval when the remembered context changed.

Restart an already running history MCP server to load the new read-only endpoint. This first implementation uses explicit local profile/history-path associations; it does not add an identity field to the app backup format. Outside-process changes are loaded on the next conversation/startup or `/memory reload`. If a writer crashes and leaves `.write.lock`, verify no memory writer is running before removing that lock.
