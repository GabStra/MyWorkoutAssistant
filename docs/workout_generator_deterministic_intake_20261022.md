# Deterministic requirements intake

This implements the user-approved intake redesign after the fresh E2E stalled in requirements review. The operative fix brief remains `workout_generator_fix_brief_20261021.md`. No solver redesign or numerical requirement relaxation is part of this change.

## Ownership

The first extraction proposes typed fields. After a source-reviewed candidate exists, the live tool accepts only `baseRequirementsId` and sparse typed `updates`, plus optional source-backed planning interpretations. Python copies the stored candidate, recursively merges object fields, replaces explicitly supplied arrays and validates the complete result. Omitted fields remain unchanged. Null clears a non-nullable optional field; schema-supported null remains a value. Deleting required fields fails validation. A stale base is rejected.

The live shell validates the currently offered schema before executing an intake call. A model cannot bypass the sparse-update surface by submitting an old full extraction. Python renders the exact field changes and complete resulting preview. A source-reviewed candidate is not user-approved: fresh confirmation is still required before planning under changed requirements.

Unchanged exercise restrictions reuse their resolved policy only when the actual library fingerprint and restriction-resolution version match. A duration or coverage clarification cannot silently reinterpret exercise exclusions.

## Permissions and qualitative intent

New intake no longer requires a model-written `requirementAccounting` paraphrase ledger. The original instructions remain authoritative qualitative source. Exercise qualification receives those sources even when no ledger exists. Semantic workout review assesses verbatim user-source blocks, using backend source references and the existing supported / needs correction / insufficient evidence statuses. This removes a redundant representation; it does not prove every qualitative judgment is correct.

Numeric relaxation permissions are explicit `relaxationPermissions` entries. The live tool enumerates supported target paths; code validates the exact path, permitted direction and optional ordering rank. New records default to no permissions. An explicit empty list authorizes no relaxation and overrides any old ledger. The preview displays these permissions in plain language. Permission allows an alternative to be proposed, never applied or approved automatically. Exercise restrictions and equipment are outside this numeric permission surface.

## Review routing

Source review compares structured proposals against original instructions. Scoped updates include code-computed changed paths, new source references and outstanding concerns. Prior passing fields are context, not fresh construction tasks. A failed base still has unresolved concerns to check.

Source-review concerns cannot directly mutate requirements. Blocking concerns stop at the existing user-question gate with the exact findings displayed. Informational findings accompany the preview. Malformed or failed source-review output stops for explicit retry rather than launching a model-authored finding-patch call. These boundaries prevent the prior automatic extraction/review loop; they do not make interpretation deterministic.

## Acceptance

Offline evidence lives in `build/workout_deterministic_intake_20261022/`. The retained clarification replay must preserve all structured fields, while an explicit shoulder-ceiling update must change only that leaf and require fresh review/confirmation. Focused checks cover sparse updates, explicit clears, restrictions, permissions, source preservation, source-review stops and qualitative source assessment.

The user explicitly chose a fresh rerun over historical receipt compatibility. Saved conversations and exports remain untouched. An old review receipt may correctly be stale under the changed review context; it is not reissued or silently approved by this redesign.

No paid E2E is part of this implementation checkpoint. Fresh-generation completion, model judgment quality and user tolerance remain unverified until the fresh acceptance run and actual training observations. Ordinary double progression remains app-owned.

## Subsequent user-authorized fresh E2E

The supervised fresh-origin run completed with a verified export: `build/workout_deterministic_intake_fresh_e2e_20261022T145332/continuation4/workouts/workout_plan_2026-10-22_153415.json`, SHA-256 `7f20b610e1e2f6c86998533892b2a2e0bf09b38ea5b2d105e68ed09e629ff1cb`. The independent verifier established exact reviewed-artifact parity, schema-v2 links, execution-schema validation, unique runtime UUIDs, unchanged provided equipment, recomputed numerical audit, unchanged source conversation and matching final runtime hashes.

The run used 40 Flash calls and 2,628,993 reported tokens across the fresh attempt and its continuations, within the 64-call harness budget. The complete logged token-rate cost estimate is $0.380471454. Per-stage rejections and every snapshot comparison are in `fresh_e2e_outcome.json`; the top rejecting stages were Repairing draft and Expanding candidate menu. This was not an unattended single-pass success: delegated intake corrections, bounded repair continuations and a controller-authored typed correction were required. No numerical targets were relaxed.

One shared ownership bug blocked continuation: a rejected, numerically infeasible redistribution's 12-set total was inherited as a validated conserved outcome, preventing a feasible 15-set correction. Both carry-forward consumers now select audited outcomes with matching requirements/library/history/decisions rather than promoting failed proposals. Four focused regression cases, the exact retained rejected-proposal replay, compilation and scoped diff checks passed. The failed requests remain intact; continuation resumed from the checkpoint before the affected admission failures. No contract version or invalidation rule was added.

The export contains 83 working sets (27/29/27), estimated at 75.85/83.43/77.3 minutes. Effective weekly targets are chest 15, back 15, quadriceps 15, hamstrings 15, glutes 18, shoulders 21, biceps 16.5 and triceps 15. Remaining advisory limitations include repeated squat selection and one weekly set each for calves and abdominal work. Personal tolerance and actual execution duration remain unverified. Passing semantic review does not establish better training outcomes.
