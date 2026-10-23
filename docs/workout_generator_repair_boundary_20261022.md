# Repair boundary correction — 2026-10-22

The retained successful generation exposed two shared ownership defects, independent of whether its exercise distribution was desirable:

- Assessed repair requests silently discarded `numWorkSets` before validation. A mixed request could therefore apply only part of the submitted intent. Unsupported count edits now fail validation; allocation remains code-owned.
- Subsequent corrections implicitly inherited rejected typed proposals and rejected metadata patch operations. Repairs now compile against the saved candidate using only the current complete submission. Prior rejected edits remain diagnostic evidence, never an implicit transaction base.

The correction reaches the common compiler, shell admission, alternative repair caller, metadata scope validation and planner context. The old replacement toggle is removed. Actionable finding coverage is still enforced; submitting an independent correction does not waive outstanding findings.

Verification: 13 focused tests passed; all seven edited runtime/test files passed `py_compile`. A zero-provider replay of the retained continuation2 request compiled the controller's one addition without inheriting the rejected request's two additions. The source conversation hash remained unchanged. Evidence: `build/workout_repair_boundary_20261022/retained_replay.json`.

No fresh paid E2E was run for this correction. The earlier successful export predates these changes. This establishes repair isolation, not improved training outcomes or fewer model calls. No exercise quota, optimization objective, requirement relaxation or prompt expansion was introduced. Desired portions of a rejected proposal must now be explicitly included in the next complete correction.
