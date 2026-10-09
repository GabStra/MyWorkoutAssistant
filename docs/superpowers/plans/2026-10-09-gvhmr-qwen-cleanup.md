# GVHMR and Qwen generator cleanup

Approved scope: Qwen handles exercise contracts and visual review; GVHMR is the only reconstruction backend. Remove Gemma/LiteRT and WHAM inference tooling. Rename backend-independent reconstruction utilities rather than misrepresenting their implementation as GVHMR inference. Retain existing artifacts and allow legacy metadata/result filenames to load; never reuse a result without its existing identity checks.

## Implementation

- [x] Add a focused default/CLI regression and observe the current failures.
- [x] Rename shared reconstruction modules and callers; retain worker locking, deadlines, cancellation and result validation.
- [x] Remove WHAM-specific inference, checkpoint setup, Docker tooling and backend options. Update GVHMR defaults, CLI and PowerShell wrappers together.
- [x] Remove Gemma/LiteRT paths and use Qwen for contracts and visual review.
- [x] Adapt legacy artifact reads at explicit compatibility boundaries; update current documentation and affected fixtures/tests.
- [x] Run Python compilation, CLI help, PowerShell parsing, and focused reconstruction/worker/cache/wrapper tests. Inspect the final diff and remaining references.

Execution: continue in this session under the user's `yes go` authorization. Independent wrapper and vision cleanup may run in parallel with disjoint file ownership. No commits, model downloads, cache deletion or expensive generation runs are part of this cleanup.

## Verification

Compiled 121 Python files and checked that local package imports resolve. Combined focused reconstruction/worker/cache tests: 91 passed, 4 skipped because the test interpreter lacks smplx. Final CLI/default/compatibility/motion-fusion selection: 28 passed. Parsed 9 PowerShell scripts; metadata compatibility and wave isolation PowerShell tests passed. Scoped wrapper default/flag/shutdown checks passed.

Two unrelated wrapper integration checks remain failing on owning behavior unchanged from HEAD: `test_library_wrapper_runs_bounded_then_deferred_and_resumes_phase` expects the second pass not to defer, while the existing library always supplies that flag; `test_workout_plan_wrapper_builds_mobile_package_directly` produces no approved movement in its fake run and reaches the existing incomplete-selection gate. No acceptance gate or assertion was weakened. No full model inference run was performed.

Historical artifacts remain explicitly loadable. Automatic cache reuse requires current layout and identity; old stages may be recomputed. The old WHAM checkout remains on disk, ignored and unregistered as a submodule.
