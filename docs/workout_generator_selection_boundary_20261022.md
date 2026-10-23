# Selection before paid drafting — 2026-10-22

The operative brief remains `workout_generator_fix_brief_20261021.md`. This checkpoint changes the shared allocation/selection boundary. It does not change muscle credits, requirements, numerical objectives, independent-review gates or the exported baseline.

## Evidence and owning defect

The final export in `build/workout_complete_plan_fresh_e2e_20261022T162540/continuation4/` has 12 Nordic sets and three RDL sets. Its selected squat definitions credit both quads and glutes fully. With at least 15 quad sets and at most 18 glute sets, the selected menu has room for at most three RDL sets. The 15-set hamstring minimum consequently requires at least 12 Nordic sets. These are accounting dependencies, not physiological conclusions.

The existing preliminary allocator already explained minimum counts forced at individual occurrences. It did not explain a minimum weekly dose shared across occurrences: moving the same exercise among sessions could hide that dependency. More importantly, `interactive_shell.py` automatically dispatched prescription workers after preparation/history collection. The selector could not act on the computed allocation before those paid calls. Changing counts later cannot remove a menu-level dependency.

`build/workout_selection_boundary_20261022/replay.py` replays the retained final menu through the production preliminary allocator. Its saved report proves the 12-set lower bound without provider calls. The source conversation SHA-256 remains unchanged. The retained run's runtime hashes differ only in the three runtime files changed by this checkpoint; before this checkpoint they matched the worktree.

Eligible-library inspection also matters: the available zero-glute-credit hamstring definitions are Nordic variants. No eligible quad definition has zero glute credit. This does not prove that every imaginable program needs 12 Nordics, or authorize changing source-library credits; the lower bound above applies to the retained selected menu.

## Shared correction

- Extend the existing LP allocation diagnostics to minimize weekly exposure for each repeated definition across all its occurrences. Frequencies are included. These are conservative lower bounds from the volume relaxation, not a complete execution solve or optimal training dose.
- When preparation reports a weekly dependency, return control to the existing selector before automatic prescription drafting. It can choose the prepared menu, re-prepare a changed menu, search alternatives, or ask about a material capability uncertainty.
- Expose the existing `draft_workout_sessions` action as a bounded tool choice using the exact prepared ID. Do not open full-plan construction through `audit_workout_plan` at that choice point.
- Once drafting has started for that preparation, retain the existing resume path; a failed worker does not trigger another menu-selection call.

No extra mandatory review role, contract/version, invalidation rule, physiological quota, exercise-name exception or new optimization objective was added. This is fix category (a), correcting shared ownership and routing. The selector may need one additional planning call before workers; no paid acceptance run was made here.

## Verification and limits

Eight focused checks pass: weekly coupling under non-unit frequency, changed credits/bounds as synthetic controls, early selection/routing, worker resume, closed discovery outside selection, coupled infeasibility and distinction between occurrence-level and weekly dependencies. Edited Python files compile; the retained production replay completed in approximately 0.26 seconds of allocation time with zero provider calls.

The change makes the constraint visible and actionable early. It does not establish that the LLM chooses a better menu, that 12 Nordic sets are personally tolerable, or that a different menu meets every numerical, timing and semantic requirement. Aggregate muscle targets still cannot establish regional development. Personal capability/recovery and measured session duration remain unknown. A fresh paid E2E and semantic comparison are separate acceptance work.
