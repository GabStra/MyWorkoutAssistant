# Remaining-issue fixes — 2026-10-27

## Shared recovery boundary

`session_drafting.py` now checks the executable prepared recipe pool after valid worker results are assembled, requests only missing recipe occurrences through the existing prescription worker and validation path, and preserves healthy prescriptions. Recovery chooses a prepared session that can supply the required maximum multiplicity; a global missing count is not mistaken for that session's local deficit. A remaining gap stays resumable without weakening pool completeness or regenerating the healthy workers.

The focused two-worker replay recovers the missing recipe with one additional fixture response. Explicit `/continue` reuses the completed pool with zero additional responses. A separate variant makes the first scoped recovery fail, then proves `/continue` retries only the missing recipe and the solver waits until the pool is complete. Original failure evidence remains at `build/workout_remaining_investigation_20261027/worker_gap_continue_result.json`; fixed evidence is saved separately as `worker_gap_fixed_continue_result.json`.

## Partial evidence remains partial

`joint_planning.py` and the shared final-guidance renderer now explicitly describe demand optimality as conditional on the fully classified groups. Final guidance names unclassified groups. Raw solver statuses and approved priorities are unchanged; an optimal count objective is not a complete demand, fatigue or personal-suitability finding. The focused regression exercises final `render_program_guidance`, not only the intermediate summary.

No unsupported exercise-property annotations, fatigue weights, Nordic-specific caps, new contracts or requirement relaxations were introduced.

## Correction to the preceding investigation

The attempted retained-run missing-recipe probe reached the solver with **zero provider calls**. Tracing the actual path showed that Bulgarian Split Squat (`LIBRARY_191`, immutable ID `9cadcbaf-2d08-580c-9565-9921d6a06755`) is intentionally removed before worker scheduling: its current definition is `BODY_WEIGHT`, has no equipment, and cannot satisfy the approved native warm-up rule. The original prepared menu and effective executable menu are different domains.

The synthetic missing-recipe recovery bug was real, but this particular retained absence was not an instance of it. The earlier assertion that the real pool needed a missing Bulgarian recipe was incorrect. Do not force this definition into the solve or relax the warm-up requirement to make the investigation's expectation true.

The shared drafting receipt now records native-warm-up exclusions with their definition identity and reason. This discloses the effective search domain rather than leaving an investigator or reviewer to infer it from differing recipe counts.

The prior Nordic frontier remains a bounded executable-pool result: unsupported-trunk peak 17 requires at least 14 weekly Nordic sets; a ceiling of 13 has optimum 18. This says nothing about a universal safe Nordic dose. Current personal tolerance and recovery remain unknown. Improving variety under a different ordering requires an explicit policy comparison, not another repair attempt under the same binding hierarchy.

## Verification

- Eight focused tests passed: five recovery/exclusion cases and three demand-evidence cases covering available, partial and unavailable evidence.
- `py_compile` passed for the four edited runtime files and the two edited test files; scoped `git diff --check` passed.
- `build/workout_remaining_fixes_20261027/effective_pool_replay_result.json` proves the retained production path reuses the 39/39/38 effective recipes, discloses all three warm-up exclusions, and reaches the solver boundary without model calls. Solver execution was deliberately intercepted; this replay is not a new optimized workout.
- Runtime source hashes are in `build/workout_remaining_fixes_20261027/verification.json`. Retained transcript hash remains `624705d042be3ab94bfca3f7886d5a7cdea6beeee8de51e2b3d18cb20d94f5c3`.

No fresh E2E, new semantic-model review or export is established by these scoped checks. Personal suitability and actual duration remain unverified.

## Concrete priority alternative

A provider-free same-pool comparison changes only the copied objective order to duration similarity, movement relationships, exercise-family distribution, verified demand distribution, workload economy and session distribution. It does not rewrite the retained approval or introduce a production Nordic cap.

The candidate passes native numerical and execution audits: 12 Nordic sets (2/5/5), 91 weekly physical sets, and estimates 4798/4840/4830 seconds (42-second spread). Lateral and vertical-pull floors remain satisfied. The same-pool family objective improves from 58 to 37 and movement-relationship cost from 6 to 0, while the unsupported-trunk peak worsens from 17 to 20. This is an explicit preference tradeoff, not proof of lower fatigue. The first five alternative objectives are optimal; final placement tie-break and muscle distribution remain feasible without an optimality proof.

The saved msg32 baseline has an old superset member-order defect under the current audit; that does not make the retained final export invalid. The alternative is a solver candidate, not a freshly reviewed or exported workout. See `build/workout_remaining_fixes_20261027/policy_alternative/comparison.json` and the raw receipt beside it. An initial harness attempt lost its feasible result at an inappropriate approval check; the corrected attempt saves its solver receipt before direct numerical audit. Both were offline and made zero provider calls.

After that replay, missing-recipe task iteration was sorted for stable request ordering. It does not affect the completed-pool solver comparison; its focused recovery tests and compilation were rerun successfully. Final runtime hashes are recorded in `verification.json`.
