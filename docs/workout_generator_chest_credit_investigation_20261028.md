# Chest-credit investigation — 2026-10-28

## Finding

The exported chest total is arithmetically reproducible, but it is not a source-verified measure of 15 equivalent chest-training sets. The code records **12 direct credits plus 3 fractional indirect credits = 15 effective credits/week**. That result follows the current library fields and accounting convention exactly; it does not establish that the selected work provides a particular hypertrophy dose.

The verified export contains the same pattern in each of three sessions:

| Exercise | Working sets/week | Exported library role | Chest credit/week |
|---|---:|---|---:|
| Barbell Bench Press | 6 | Primary `FRONT_CHEST` | 6 direct |
| Dumbbell Pullover | 6 | Primary `FRONT_CHEST` and `BACK_UPPER_BACK` | 6 direct |
| Barbell Overhead Press | 6 | Secondary `FRONT_CHEST` | 3 indirect |
| **Total** | | | **12 direct + 3 indirect = 15 effective** |

The prescription is two working sets of each exercise in each session. Per session, the audit therefore reports four direct chest credits and one indirect credit, or five effective credits. The approved audit target is 15–18 `weeklyEffectiveSets`; it is not represented as a direct-only floor.

## What supports the assignments

- **Bench press:** The app library marks chest as primary and its reviewed anatomy annotation cites a study that measured pectoralis regions during flat and incline presses. This supports chest as a principal target. The annotation itself cautions that acute EMG does not establish hypertrophy dose.
- **Dumbbell pullover:** The app library marks chest as primary. A small acute study found greater pectoralis-major than latissimus EMG during a barbell pullover; a second study found no EMG difference between barbell and dumbbell pullovers in 11 trained men. These support pectoralis involvement in the movement and make a chest role plausible. They do **not** show that every pullover work set produces the same adaptation as one bench-press set. The retained library annotation for this definition only supports pullover-family identity; it has no reviewed anatomy/credit annotation.
- **Overhead press:** The app library marks chest as secondary. A small acute EMG study found pectoralis-major activity differed by press variation, with the front press producing more than the behind-the-neck variant. This supports possible assistance in a front press, but does not validate a universal 0.5 chest-set value for this exercise or the particular execution in the export.
- **Fractional counting:** The generator explicitly assigns primary muscles 1.0 and secondary muscles 0.5 per working set. A recent multi-level meta-regression found that counting indirect sets fractionally (0.5) had the strongest relative evidence among the tested total, fractional and direct-only methods for modelling training-study outcomes. That supports fractional counting as a population-level accounting method; it does not calibrate each exercise-muscle pair or make 0.5 a measured physiological conversion.

## Proven versus unresolved

**Proven:** the active code maps library `muscleGroups` to one direct credit per set and `secondaryMuscleGroups` to one-half indirect credit per set, with primary precedence. The retained exact export and native audit agree on 6 + 6 + 3 = 15. The chest requirement is a 15–18 weekly *effective-set* range.

**Not proven:** that the six pullover sets should count as six full chest sets for hypertrophy, that the overhead press contributes exactly half a chest set each, or that this particular plan is physiologically adequate for the user. The data are app-saved muscle-role labels plus a general scoring convention, not an exercise-specific dose validation. No inspected source establishes a set-for-set adaptation equivalence among pullover, bench press, and overhead press.

## Recommendation

Do not change the pullover role or the 0.5 coefficient from this audit alone: the available evidence supports pectoral involvement but cannot supply a defensible replacement coefficient. Keep the machine-readable distinction between direct and indirect credits visible in reviewer context and output, and describe the target as **“15 effective credits under the approved library convention”**, not as 15 verified chest sets or proven adequacy. If the intended requirement is specifically 15 direct chest-target sets, that is a different requirement and must be stated explicitly before changing the solver target. The fresh E2E should proceed with the current approved 15–18 effective-set definition and report this limitation; this investigation makes no runtime, library, requirement, or retained-artifact changes.

## Evidence checked

- `build/workout_review_subject_fix_20261028/live_resume4/verified_export.json` and its exact export `workouts/workout_plan_2026-10-28_185436.json`.
- Exact audited session credits in the matching `.audit.json`: per session, bench 2 direct, pullover 2 direct, overhead press 1 indirect; three sessions total.
- `workout_generator_pkg/generation_audit.py`: `MUSCLES`, `ASSUMPTIONS`, `muscle_credits_per_set`, and `muscle_metadata_policy` define the aggregate mapping and its limitations.
- `workout_generator_pkg/exercise_family_annotations.json`: bench has a reviewed chest-region annotation; pullover has only a family annotation, whose cited study concerns barbell/dumbbell variation and acute EMG; the overhead-press anatomy annotation covers deltoid regions, not chest.
- `build/workout_demand_suspended_20261028/next_run_requirements.json`: chest target is 15–18 under `weeklyEffectiveSets`.

Primary research:

- [Marchetti & Uchida, 2011 — pullover EMG of pectoralis major and latissimus dorsi](https://pubmed.ncbi.nlm.nih.gov/21975179/): eight male participants; one barbell-pullover set; acute EMG, not longitudinal hypertrophy.
- [Campos et al. — barbell versus dumbbell pullover EMG](https://repositorio.ufla.br/items/6617a7f9-0715-43c2-b46e-81ead7a40c6a/full): 11 trained men; one 90%-10RM series per variation; no detected activation difference, not adaptation equivalence.
- [Coratella et al., 2022 — front/back and barbell/machine overhead press EMG](https://pubmed.ncbi.nlm.nih.gov/35936912/): eight competitive bodybuilders; variation-specific acute muscle excitation, including pectoralis major.
- [Pelland et al., 2026 — resistance-training volume/frequency meta-regression](https://pubmed.ncbi.nlm.nih.gov/41343037/): compared total, fractional and direct-only indirect-set counting at the study-model level; supports the fractional convention comparatively, not exercise-specific coefficients.
