# Structured requirement authority and avoidable supervision

## Finding

The October 28 fresh run needed user intervention because the source reviewer incorrectly treated exact values in the user's structured requirements as unapproved. This is a verified current-worktree failure, not a missing-input issue: `result.json` records `runtimeHashesMatch: true` and `inputsUnchanged: true`.

The original source in `build/workout_initial_requirements_e2e_20261028/fresh_e2e/input.md` contains the marked section `Current approved structured requirements for extraction (the numerical authority)`. Its JSON explicitly specifies both the weekly `horizontal_pull`/`vertical_pull` balance and the per-exercise `workSets` range 2–20. These fields also appear in the submitted requirements in `messages.json` tool call 4. Yet tool result 5 reports the balance pair as invented and asks whether the maximum 20 is user intent. The source review also asks the user to verify the direct abs/calf accounting of two recorded decisions. The exact structured values are present in the source; the abs/calf validation is already code-owned.

The follow-up user message 7 explicitly reaffirms the values and scopes the Dumbbell Squat exclusion. The scoped update is submitted at message 8 and source review passes at message 9. That proves this source review caused the avoidable clarification round. The Dumbbell Squat name/configuration ambiguity itself was genuine and appropriately remained for user clarification.

## Owning flow

`plan_review._requirements_context` sends the extracted requirements, the original source text, resolved decisions, and application policy together to the model (`workout_generator_pkg/plan_review.py:1345`). `_REQUIREMENTS_PROMPT` asks the model to compare fields to source instructions (`plan_review.py:478`). The code checks that a finding references the original source, but it does not validate that the referenced source entails the model's assertion. It then makes `established_violation` and `clarify` findings blocking (`plan_review.py:1949-1963`). The initial correction path accepts only a supported repair set; a mixed set of false mismatches and genuine clarification findings is routed to the blocking question instead (`plan_review.py:1466`, `1991-2021`).

This leaves a model judgment as the authority for whether a machine-readable user value was actually supplied, even when the original message contains a dedicated structured-authority block. The model's claim can therefore reopen a settled value and ask the user to resolve a false conflict.

## Code-owned checks that do not need a user answer

`recipe_contracts.canonical_qualified_roles` derives `abs` and `calves` from primary library muscle groups; model-proposed role labels cannot qualify those roles (`workout_generator_pkg/recipe_contracts.py:24-25, 91-99`). `generation_audit.audit_coverage_minimums` checks approved weekly-set and session-frequency floors (`generation_audit.py:1696-1721`). The audit reports physical weekly working sets once (`generation_audit.py:120`), and the existing coverage regression verifies that a primary exercise may qualify for abs/core while a secondary-only claim does not qualify abs/calves (`tests/test_workout_generator_coverage_minimums.py:34-45`). These facts can be computed and shown in the approval preview. A user should decide actual training suitability when asked; they should not be asked to verify whether the code applies its own counting rule.

Regional anatomy is different: where reviewed library annotations cannot distinguish lats from upper back or shoulder heads, report that as unknown. Do not convert the missing evidence into invented credits or ask the user to validate a deterministic accounting rule.

## Recommended authority boundary

1. Treat only a clearly marked, user-authored structured requirements payload as machine-readable authority. Validate its schema and seed/merge its explicit numeric fields directly into the requirements record in code; do not ask the LLM to restate those values and then compare its copy. The model should return qualitative intent and only policy choices that the user has delegated it to propose.
2. Keep the LLM review for qualitative source meaning, real ambiguity, and contradictions between active prose and the structured payload. A disagreement between these active sources remains blocking and requires user clarification; code must not silently choose one. Apply explicit source precedence and supersession so obsolete prose clauses do not reopen settled requirements.
3. For amendments to an approved record, apply only the authorized sparse changes and review the changed fields plus newly supplied user source. Preserve all other passed requirements and prior decisions. Do not re-evaluate unchanged values against old prose on every update. The existing scoped-review fields (`changedPaths`, `newSourceMessageIds`) are the right boundary to preserve and honor.
4. Do not infer trust from arbitrary JSON embedded in conversation history or from model-authored output. The payload must have explicit source provenance at intake (prefer a structured request object; a documented user-authored marker is acceptable for this existing prompt format). If provenance is absent or unclear, retain the current review gate.
5. Compute code-owned compliance evidence before the user-facing approval question. Show pass/fail and supporting counts in the preview; reserve user questions for choices code cannot answer, such as personal suitability or a genuinely ambiguous exclusion.

The new delegation to have the generator choose exercise-exposure limits is a **policy choice**, not a missing exact number in the source. It authorizes the model to express the requested choice qualitatively and code to enumerate feasible frequency and weekly-set caps. No particular cap value is user-approved yet. Show concrete candidates, feasibility and tradeoffs in a reviewable preview; a cap becomes binding only through the existing explicit approval gate. Do not ask the model to reproduce code-enumerated numbers, treat the lack of a user-selected cap as a source omission, silently activate a proposed cap, or present it as already approved.

## Risks and limits

- Trusting any parsed JSON would let assistant-generated or quoted examples become requirements. Keep provenance restricted to a user-authored structured block or a separately supplied structured input.
- Ignoring all reviewer findings that point at structured fields would hide real prose/JSON contradictions. Seed only schema-valid user-authored fields directly; keep active conflicts and unauthorized changes blocking, while scoped updates leave unchanged approved fields alone.
- A code-owned pass confirms that the approved rule was applied; it does not establish physiological adequacy or personal recovery capacity.
- Parsing a marker without checking the author/turn boundary could accept copied or quoted data. The parser must bind the payload to a user source message and preserve the exact source boundary in the saved requirements receipt.

## Focused regression criteria for implementation

- Given the retained marked user payload, the balance pair and `maximumSets: 20` are seeded directly and do not depend on model transcription or trigger false confirmation.
- A changed candidate field that conflicts with the marked payload is rejected or corrected deterministically; active contradictory prose still reaches the user gate.
- An approved scoped amendment reviews its changed fields and new source only; unchanged approved values do not reopen against superseded prose.
- An assistant-authored or quoted JSON block is not elevated to authority.
- The abs/calf role qualification and physical-set accounting appear as code-computed evidence, without a user question asking them to validate the implementation.
- A proposed exercise-exposure limit has explicit `proposed` status until the ordinary requirement/preview approval is recorded.

No runtime code was changed and no paid call was made for this investigation.

## Implementation — 2026-10-29

The shared intake now recognizes the exact standalone user-authored marker shown above, validates its JSON, and loads supplied fields in code. Assistant content, blockquotes and fenced examples are not authority. Duplicate keys, nonfinite values and schema errors fail closed. The latest explicit current payload supersedes earlier payloads. Source provenance records the user message index and payload hash.

The extraction tool omits supplied fields and offers only additional execution-rule kinds, so the model need not repeat approved quantities. A new marked amendment is merged into the existing record through the existing scoped-update path. Direct review also rejects a forged candidate that changes a marked value. Default balance semantics and code-rendered descriptions do not create false mismatches.

Structured-source review uses a smaller typed check selection: authorization, an additional prose omission, a real source conflict, qualitative scope ambiguity, or a code-owned implementation check. Exact source-authorization matches and known implementation checks receive deterministic answers; they are not user questions. Real source conflicts, ambiguous exclusions, and additional prose instructions remain reviewable. Unchanged source-checked fields stay outside an amendment's authorization scope. User annotations remain visible even though the duplicate numeric JSON is removed from the review source projection.

The normal requirement confirmation and export gates remain. Proposed exposure caps do not become approved merely because intake or source review passed. Accounting disclosures say that exercise-level compliance is still pending the plan audit; they do not claim that a plan already exists or that personal suitability is established.

Validation uses the retained October 28 finding content with explicit typed check classifications, plus controlled input and conflict variants. This verifies code routing and preservation of gates; it does not establish that a live reviewer will always choose the right classification. No paid model call or fresh E2E was run for this fix.
