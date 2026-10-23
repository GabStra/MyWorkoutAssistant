# Similar session durations — 2026-10-23

For this user's program, the explicitly approved priority order is:

1. `demand_distribution`
2. `duration_balance`
3. `distribution`
4. `source_balance`
5. `progression`

This is a program preference, not a global default for other users. Hard volume, coverage, schedule, execution and session-duration constraints remain binding. No numerical tolerance for "similar" was invented.

`duration_balance` minimizes the longest-minus-shortest estimated session duration. It reuses the production audit coefficients already used for the hard duration cap, including prescribed work/rest, generated warm-up allowances, setup and first-exercise setup treatment. Fixed existing sessions participate in the comparison. Fractional seconds remain continuous auxiliary values; exercise selections and set counts remain integer decisions. The result and optimality status use the existing objective/priority receipts and numerical audit, without a new contract version or duplicated summary.

The ordinary allocation path now invokes the joint solver for this preference even when the numerical audit already passes and no other soft objective requests optimization. Approved rest ranges and other prescription bounds still govern choices; no artificial filler or idle-time operation was added. Similar estimates do not establish similar fatigue or actual execution time.

Scoped verification: five duration-specific cases plus the existing feasibility-domain regression passed (six cases total). They cover the approved ordering versus muscle-set equality, fractional seconds, fixed sessions, duration-only routing and unchanged hard feasibility identity. `py_compile` and scoped `git diff --check` passed.

## Fresh E2E before this preference was added

`build/workout_joint_priority_solver_20261023/fresh_concern_closure_e2e_20261023/validation_summary.json` records the fresh run: 13 provider calls, 710.16 seconds, estimated model-token cost USD 0.115972. Its numerical audit passed with session estimates 66.95 / 69.85 / 78.15 minutes. Runtime hashes matched all 52 generator files during that run; retained inputs were unchanged.

It did **not** export. Independent review failed JSON validation on an unsupported top-level `type` field. Offline inspection also found nine citations where eight were permitted, and two `warning` severities paired with a basis that deterministically implies `blocking`. The raw findings were not adjudicated or accepted. No unchanged paid retry was launched.

This E2E predates the new duration preference and does not validate it live. The source hashes distinguish that snapshot from the subsequent three-module duration implementation. The deeper review boundary still needs correction: the reasoning-enabled DeepSeek path uses locally validated JSON, and the current wire asks the model to supply severity despite code already deriving it from basis. Another prompt paragraph is not a solution.
