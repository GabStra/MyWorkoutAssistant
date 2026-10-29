# History configuration selection — 2026-10-28

The previous check let a model-proposed rep target change whether a recorded loading-setup concern existed. Retained Nordic evidence flagged six proposed reps but not seven, without any new capacity evidence. The local worker-repair path also offered rep edits for this setup-level concern.

The shared fix separates the recorded setup observation from prescriptions:

- `training_history.py` derives the observation from the latest same-definition session and actual equipment snapshots. Proposed reps and RIR do not enter this decision. Changed definitions and inferred equipment do not establish the observation; a newer unweighted session can supersede older loaded work.
- Existing `loadSuitabilityConcerns` carries the structured observation before prescription drafting. Exact-load comparability remains separate; historical loads are never transferred into a prescription by this change.
- Selection queries local history directly, rather than depending on model-selected lookups. Explicit choices require scoped configuration reassessment; unresolved supplemental configurations are omitted from the recipe pool. Cached preparations are checked before worker reuse.
- Setup concerns route to the existing selection repair, not rep-only worker repair. Actual audit/export validation enforces the same evidence. Native load calibration remains app-owned for supported adjustable configurations.
- Existing retained-evidence refresh restores current setup metadata without rewriting saved session pages or changing version constants. Validation refreshes locally once per batch and copies concern lists before appending prescription-specific findings.

The invariant is: changing a proposed prescription cannot, by itself, resolve a recorded setup-choice concern. A loading configuration must be reconsidered, or the existing human gate must resolve the choice. A clean check does not establish personal suitability.

Verification: 44 focused pytest cases and scoped compilation passed. Provider-free replay of both retained runs is recorded in `build/workout_history_configuration_fix_20261028/validation.json`, with a rerunnable `validate.py`. It tests the actual raw saved responses, rep targets 5/6/7/12, the early preparation gate, a supported configuration replacement, and isolated production solves. Retained conversations, exports and source inputs remain unchanged.

One fresh live run is retained under `build/workout_history_configuration_fix_20261028/fresh_e2e/`. The history gate caught explicit fixed-configuration choices before workers; scoped selection removed those choices, and the solved candidate contained none of them. Runtime source hashes matched throughout. No new export resulted: a separate semantic-review finding falsely attributed 13 weekly Front Squat sets to the unchanged artifact, which has 5/3/0 (8 total), and attempted repairs failed admission. Delegated acceptance of the earlier disclosed execution/recovery uncertainties changed no prescriptions or hard requirements. This live result verifies the repaired history paths, not full-generation success; see `fresh_e2e/e2e_report.json`.

Limits: evidence is scoped to the exact stored movement and recorded setup. Bilateral Nordic history does not establish single-leg capability, current working load, recovery capacity, or effective stimulus at a new prescription. This change adds no exercise-family equivalence, volume quota, requirement relaxation, prompt contract, or version constant.
