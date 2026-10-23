# Workout generator fix brief — 2026-10-21

Working brief distilled from the architecture-doc saga and run artifacts. Audience: the session that implements the fixes. Read this instead of re-deriving the analysis.

## Verdict

End-to-end generation is within LLM reach. The bottleneck is not model judgment — it is (1) a serial chain of dozens of must-succeed LLM calls, (2) asking the model to *construct* precise typed documents instead of *choose*, and (3) a compensation loop where every model failure added contract/version/invalidation machinery that now fails more often than the model. The Oct 21 run proves the converged shape works: 12 calls, 261 s, two validated alternatives, stopped only at the by-design human approval gate.

## Measured evidence (with sources)

- Fresh run Oct 19: **292 API calls, 14,960 s, 24.3M prompt tokens**, 161 calls inside "Repairing draft", review alone = 5 evidence scopes (~13 calls each) + execution (~22) + assessment (~15) → unresolved. `build/workout_generator_architecture_e2e_20261019T173635/e2e_result.json`
- Resume Oct 21: **12 calls, 261 s, 642K tokens** → two audit+review-passing alternatives; no export only because relaxing minimums requires human approval (correct gate). `build/architecture_goal_20261021/resume_outcome.json`
- Four more targeted E2Es later on Oct 21 (same retained conversation, not fresh generations): alternative-evaluation 10:37, redistribution-intent 11:54, confirmation-contract ×3 through 12:29. All ended `exported: false`. The latest (`build/confirmation_contract_e2e_20261021T122914/stop_diagnosis.json`) confirms the handoff machinery works (`confirmationPassed: true`, completed review reused) and stops at repair admission on **one** finding: `program_guidance` — disclosure prose (FACT_396) describing a rear-delt-fly/deltoid-credit distribution that no longer matches the code-computed plan facts. That is the construct-precise-documents failure class, not a judgment error: prose that must track code-owned arithmetic is still model-authored.
- Failure ledger attempts 16–25 (`docs/workout_generator_architecture.md`): ~6 orchestration bugs (timestamps, receipt ordering, `baseDraftId` binding, patch representation, stale stop flag, empty `repairDimensions`), ~3 model *form* errors (wrong-draft ID references, duplicated guidance field, invalid edit shapes), 1 billing, 1 real modeling insight (calibration-time conflict — eliminated deterministically by native calibration mode).
- Model: `deepseek-flash` everywhere; `response_format: json_object` only — JSON validity guaranteed, **schema conformance not enforced** by the provider, only policed after the fact.
- Package scale: ~36K lines, ~1,000 tests / 61 files, still growing today (new `repair_contract.py`, redistribution-intent and confirmation-contract test files on Oct 21). Contract churn: review v68, audit v41, policy v12 — each new version invalidates prior model output and forces refresh cycles.

## Current frontier — the first concrete target

As of the 12:29 confirmation-contract run, the distance to a first export is **one repair finding**: `program_guidance` (finding 7). The disclosure prose says each session has one rear-delt-fly set and credits the overhead press with indirect deltoid work, while the code-computed facts show the fly only in Session A and the indirect credit spread across close-grip bench, incline bench, incline rows and pull-up. Every gate before it passes (confirmation, review reuse, no solver rerun). The cheapest first win follows fix rule (b): render that disclosure from the same code that computes the FACT lines, or validate it deterministically against them — do not add a repair round or a new contract for it.

## Root causes, ranked

1. **Serial chain multiplication.** Per-call conformance compounds: 99% per call over 292 calls ≈ 5% end-to-end. Review×5 + assessment + repair + re-audit is dozens of must-succeed calls per generation.
2. **Construction where selection would do.** Repair asks the model to emit typed edit lists against stable occurrence IDs over a ~216K-char state projection; one wrong field rejects the whole submission and burns budget. Code already computes feasibility domains — it could enumerate the feasible edit space and let the model pick.
3. **Compensation loop.** Each failure class gained a contract + version + invalidation rule, adding failure surfaces that produced the next attempt's bug. The guardrails are now the dominant failure source (see ledger).
4. **Model tier vs task.** flash is fine for selection/cues; conformance-critical calls (assessment, repair) run on the cheapest tier with no schema enforcement.

## Target architecture — the simplification

Keep the philosophy (LLM judges, code computes, human approves); collapse seven interleaved LLM roles with versioned contracts into **two LLM roles over one plan object** (selector, reviewer), everything else solver runs and code rendering. Fresh generation ≈ six stages, ~8 LLM calls:

1. **Requirements intake** — one call, the existing `set_workout_requirements` tool. Ambiguity becomes a clarifying question, not a contract.
2. **Menu selection** — one/two calls. Model picks candidate exercises per movement role + intended roles. No prescriptions, no sets, no ID bookkeeping — pure choice.
3. **Solve** — zero calls. The existing joint solver assigns sets/reps/order/timing; on infeasibility it returns the conflict *and the negotiable knobs* (it already computes feasibility domains).
4. **Render** — zero calls. Code emits the plan document and ALL prose that must mirror arithmetic (guidance, disclosures, FACT lines) from the same computation. The stale-disclosure failure class becomes impossible.
5. **Review** — one call. Single semantic pass over rendered plan + code-computed facts, findings and dispositions in one schema.
6. **Repair** — zero/one call, by selection. Code enumerates feasible corrections from its domains, model picks, code compiles. Two rounds max, then stop with a human question.

**Deleted by this shape:** the five-scope incremental review + findings assessment + confirmation-handoff cluster (biggest call consumer, source of attempts 21/22 bugs — exists only because review output and repair input were separate conversations); the version/invalidation bureaucracy (review v68, audit v41, receipt lineage, refresh routing — polices shape drift between stages that no longer exists; "hash the inputs, if changed redo the call" replaces it); the per-item emission pipeline (solver + code templates emit deterministically; model authors only cues/notes as fields); most of the alternative/`evaluationContract` subsystem (an alternative becomes a solver run with different bounds on knobs the solver already reported — cheap runs don't need receipt-preservation machinery).

**Not simplified:** the solver and feasibility domains, code-owned arithmetic, bounded-menu discipline, resumable transcript, human gates. Oct 21 (12 calls to validated alternatives) is what these look like working.

## Invariants that already work — preserve, do not break

- **Intent-not-document**: model states small intents (`redistributionTargets`, repair objectives), code expands/compiles them. Every observed win has this shape.
- **Code-owned**: arithmetic, joint solve/feasibility, standard guidance, `requiresLoadCalibration` (deleted a whole failure class).
- **Human gates**: requirement-relaxation approval, preview confirmation. Stopping there is success, not failure.
- **Bounded menus, receipts, resumable state** (keep, but shrink).

## Fix program — ordered, each step has an exit criterion

1. **Instrument per-stage rejection rates.** Per stage: calls, rejected submissions, rejection reason class (schema / reference-ID / numerical / other). Zero behavior change.
   Exit: every run emits one JSON naming the top-2 stages by rejected-call count.
2. **Bank the first export.** The current-frontier disclosure fix; proves the existing machine end to end and gives a baseline export to diff against.
   Exit: verified export of the retained case.
3. **Collapse review to one call** (target step 5). Code-owned checks first; one semantic pass over the residue.
   Exit: one review cycle ≤ 2 LLM calls, finding quality non-regression on the retained conversations.
4. **Code-render guidance/disclosure prose** (target step 4).
   Exit: no model-authored prose that must mirror arithmetic survives to review.
5. **Repair by selection, not construction** (target step 6). Solver enumerates feasible edits/menus; model picks; code compiles. Then evaluate whether the per-item emission pipeline still earns its keep vs solver+templates.
   Exit: model repair submissions no longer contain hand-built occurrence-ID edit lists.
6. **Budget + routing.** Hard total-call budget per fresh generation (interim 40, target ~8; exceeding it stops the run and names the bottleneck stage). Strongest available model for the remaining conformance-critical calls; flash stays for selection/cues/notes.
   Exit: a fresh run exports or stops inside budget with a named bottleneck; config flag + one measured A/B on rejection rate.
7. **Anti-compensation rule for the implementing session.** A new failure is classified as (a) fix shared code, (b) shrink the model's output surface, or (c) accept + human gate. Adding a new contract version or invalidation rule requires stating why (a)–(c) all fail.
   Exit: diff review — new version constants need written justification.

Each step is independently shippable and verified against the retained-conversation harness (real model runs, not synthetic fixtures only).

## Out of scope for this fix program

Do not redesign the solver, relax validation, weaken safety gates, add more contract machinery, or rewrite the interactive shell. Verify with the retained harness + one fresh E2E; success = verified export within the call budget.

## Do-not-do list (from the ledger's most expensive lessons)

- Don't answer a model form-error with more prompt contract text; shrink the surface instead.
- Don't add timestamps, IDs, or lineage fields without offset-aware/unambiguous definitions (attempts 17, 21, 24).
- Don't mix active-draft and hypothetical-candidate references in one model-facing context (attempt 19).
- Don't treat a bounded-search timeout as proof of impossibility; route it to a human gate (existing rule — keep it).
