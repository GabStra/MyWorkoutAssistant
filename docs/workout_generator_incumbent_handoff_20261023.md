# Validated incumbent handoff — 2026-10-23

The joint solver retained a feasible candidate in Python but each subsequent
objective called SciPy's MILP interface without that candidate. The installed
public SciPy interface has no incumbent argument. Later solves now pass the
validated candidate through the public HiGHS `setSolution` interface, exposed by
the new declared `highspy>=1.15.1` dependency. No SciPy private API is used.
Public backend reference: [HiGHS model/solution reuse](https://ergo-code.github.io/HiGHS/dev/guide/basic/).

`allocation._milp_solve` keeps its two-value return and adds an optional incumbent
argument. It reconstructs deviation, balance and activation auxiliary values,
then checks bounds, integrality and every current constraint before passing the
start. That includes the attained higher-priority objective locks. Invalid starts
fail before invoking HiGHS. Unseeded solves retain the existing SciPy path.
Seeded results pass the same local candidate validation and the final production
audit; raw termination and seed-supply diagnostics remain visible. A failed stage
still cannot waive requirements or discard the saved validated candidate.

This transfers a starting candidate. It does not introduce a persistent solver
session or claim to retain a branch-and-bound tree. No objective, target, quota,
call budget, timeout, prompt or contract version changed.

## Isolated verification

Eighteen focused checks passed, covering seed handoff, auxiliary reconstruction,
invalid seed rejection, production stage propagation, diagnostics and existing
incumbent retention. Edited Python files compile; TOML and scoped diff checks
pass.

The saved failing generation was reconstructed with zero provider calls. Its
first duration stage produced a validated incumbent. The following distribution
model was then solved cold and seeded using the **same HiGHS 1.15.1 backend**,
identical matrix, objective and 30-second limit. Both returned validated feasible
candidates with the same objective value (90), and both reached the time limit.
This verifies the handoff but **does not establish a speed or quality gain from
seeding**. The newer backend is a separate factor from the previous SciPy solve;
we do not attribute its different result solely to the incumbent.

A production-path replay reused that already-solved first-stage candidate after
checking the exact variable domain, constraint multiset and first objective
bound. Subsequent distribution, source-balance and preservation stages all
received an incumbent and returned locally validated candidates. The final
production audit reported zero errors. Final session estimates were
4,542 / 4,552 / 4,542 seconds (75.70 / 75.87 / 75.70 minutes), a ten-second range.
The first-stage candidate in this experiment had an attained 15-second duration
bound; this is a different bounded-search outcome from the earlier compaction
experiment's six-second bound. These results must not be compared as a controlled
change in workout quality.

All stages remain bounded searches and optimality is unproven. These estimates
are not measured session execution times. No semantic review or export was run.
Original conversations and backup hashes were unchanged. Evidence and runtime
hashes:
`build/workout_joint_priority_solver_20261023/incumbent_handoff_validation_20261023/result.json`
and `production_result.json` in that directory.
