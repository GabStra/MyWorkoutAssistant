# Solver boundary fix — 2026-10-28

The retained fresh run failed because the backend and its consumers disagreed on numerical feasibility. The captured distribution incumbent exceeded an auxiliary role-concentration row by 1.0140662709545722e-7; the backend accepted it within its 1e-6 MIP tolerance, while downstream code used 1e-7. This was not a workout constraint violation.

Shared solver code now canonicalizes integer and bound noise and checks original rows with one solver tolerance. The objective-epigraph consumer uses that same policy, including unscored derived helpers. Material violations still fail with variable or row identity, activity and bounds. The strict native workout audit and approved requirements are unchanged. Integral count results retain their Python integer type for patch consumers.

Model construction now traverses sparse count-series incidences instead of repeatedly scanning every row against every series. On the captured model, the compiled objective, integrality, bounds and sparse matrix match the baseline exactly. The isolated model-build benchmark improved from 11.521 to 0.868 seconds.

Independent review now selects compact semantic evidence references rather than numeric FACT identifiers. Unknown references remain invalid. A citation-only correction can repair advisory references without changing the underlying judgment or disposition. This does not establish that every semantic judgment is correct; in particular, the earlier superset-transition/rest interpretation remains a review-quality limitation.

## Verification

- Frozen baseline replay: 330.390 seconds; final distribution incumbent rejected.
- Current native replay: 205.350 seconds; all eight lexicographic stages optimal, distribution score 38, strict native audit errors empty. Earlier priority scores unchanged. Model-building time fell from 92.356 to 5.324 seconds.
- Captured incumbent accepted under the shared policy; a controlled 2e-6 row violation rejected. Physical integer decisions unchanged.
- Focused combined checkpoint: 30 tests passed. Final integer-type check: 2 tests passed; edited runtime and test files compile; scoped diff check passed.
- No provider calls, fresh semantic review or export were performed for these replays. Single-run timings are evidence for this fixture, not a universal speed guarantee.

Evidence is retained under `build/workout_solver_fix_20261028/`: `baseline/`, `current/`, `captured_solution_validation.json`, `epigraph_validation.json`, and `model_build_benchmark.json`. The native replay hashes precede the final integer-return-type preservation change; that change received the final focused check separately.
