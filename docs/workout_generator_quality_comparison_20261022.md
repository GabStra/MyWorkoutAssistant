# Programming-quality implementation checkpoint

The goal is to improve selection without turning controller choices into requirements or treating numerical optimization as proof of programming quality. Evidence is retained under `build/workout_programming_quality_comparison_20261022/`. The original verified 87-set export and its conversation remain unchanged.

## Shared fixes

- Exercise substitutions no longer inherit a different movement's load unless the edit explicitly supplies a replacement prescription. Repetitions and other unaffected fields remain intact; native app calibration handles missing loads. The previous compiler could transfer a legal but unrelated load and still pass validation.
- The equipment-headroom objective now weights weekly working-set exposure. Previously splitting four sets across two occurrences doubled the penalty without changing the dose. Consolidated, split and twice-weekly representations now have the same cost. This does not implement double progression; the app still owns it.

The authority audit found no safe runtime text filter for historical controller instructions: they entered through actual user turns. Retained conversations were not rewritten. This experiment submits candidate changes through the existing typed compiler instead of adding them as user requirements.

## What the evidence establishes

The equipment/library audit found no available non-Nordic leg-curl definition. Most alternative hamstring work also consumes the approved glute budget. That explains part of the concentration; it does not prove 17 Nordic sets are appropriate. No muscle credits or genuine requirements were changed.

One targeted source candidate passes shared numerical and execution audits: 84 sets, including 12 Nordics, three RDL sets, three lateral-raise sets and supported dumbbell-row substitutions. The new row lacks comparable performance history and a fresh recipe-qualification receipt, so this is research material, not an accepted export.

One bounded local solve changed that candidate to 81 sets, including 14 Nordics, one RDL and one lateral-raise set. All numerical objectives were optimal. This demonstrates the difference between optimizing aggregate distribution and preserving a feasible programming choice; it does not establish which workout is better.

The saved requirements explicitly authorize distribution/progression objectives. Consequently this reallocation is not evidence of a solver bug. Bypassing those objectives to retain preferred counts would change the approved decision policy. That policy trade-off remains explicit; no speculative qualification bypass or new fatigue/region score was added.

One Flash advisory comparison favored the exact 84-set candidate modestly over the retained export because of its more substantive lateral-delt and hip-hinge work. It also identified weaker vertical pressing and uncertainty around new loads and personal tolerance. Both candidates meet the original audited numerical bounds. The assessment used one presentation order and is neither a production independent-review receipt nor evidence of training outcomes.

The request completed in 54.47 seconds, with 63,162 input and 9,599 output tokens, no validation rejection and a logged token-rate estimate of $0.0152337. Runtime hashes matched throughout; the source conversation was unchanged. No additional generation or export was performed. Full request, response, metrics and hashes are retained in `semantic_comparison/`.

## Validation and limits

The substitution compiler's 20 focused menu-selection tests passed. Two focused progression-objective tests passed, including an independently solved segmentation control. Edited runtime/test files compiled. Saved failed and passing reviewer-boundary replays preserve findings and uncertainty without turning approval into positive quality evidence.

Actual recovery, exercise capacity, technique and execution duration remain unknown. The comparison supports a programming direction, not a guarantee of suitability. No new quality score, contract version, invalidation rule, mandatory model stage or generator-owned double-progression algorithm was added.
