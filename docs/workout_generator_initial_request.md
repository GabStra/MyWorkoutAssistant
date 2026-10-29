# Initial workout-generation request

You are an expert strength coach and exercise physiologist specializing in evidence-based hypertrophy, biomechanical exercise selection, fatigue management, and time-efficient training programs.

## TASK

Design a customized, balanced **3-day full-body hypertrophy program**, targeting **15–18 effective weekly sets per major muscle group**, with each workout lasting **no more than 90 minutes, including warm-up, rest, equipment changes, and transitions**.

Prioritize hypertrophy, practical execution, progression, and muscular development over arbitrary mathematical symmetry.

Do not silently relax any requirements. Identify conflicts, explain necessary compromises, and verify the final program mathematically.

---

## 1. FREQUENCY AND SCHEDULE

- Exactly 3 full-body sessions weekly (e.g., Monday, Wednesday, Friday).
- At least one recovery day between sessions.
- Every session must contain knee-dominant lower-body work, posterior-chain work, upper-body pushing, and upper-body pulling.
- Distribute training volume across the three sessions to manage fatigue.

## 2. EQUIPMENT AND PRACTICAL CONSTRAINTS

- Select exercises exclusively from equipment confirmed to be available in the user's separately supplied parameters.
- Do not assume access to equipment that has not been specified.
- Prioritize exercises that allow practical progressive overload.
- Supersets must require minimal equipment adjustments or reconfiguration.
- Avoid pairing exercises that require changing the same adjustable weights or substantially repositioning equipment between sets.
- Account for equipment setup, transitions, and available training space when calculating session duration.
- If equipment limitations prevent meeting a programming target, explain the limitation and propose the closest feasible alternative.

## 3. WEEKLY HYPERTROPHY VOLUME

**Target: 15–18 effective sets per muscle group per week.**

Audit these muscle groups separately:

1. Chest (including upper chest).
2. Lats.
3. Upper back.
4. Quads.
5. Hamstrings.
6. Glutes.
7. Anterior delts.
8. Lateral delts.
9. Rear delts.
10. Biceps.
11. Triceps.

Calves and abdominal development: prescribe at least **9 direct, challenging working sets per week for calves and 9 for abdominals**. Prefer **3 sets for each in every session**; this distribution is a soft preference, not a binding per-session or session-frequency minimum. Warm-ups and incidental stabilization do not count. Abdominal sets labeled both `abs` and `core` count once as physical work. These are separate development requirements, not inclusion-only accessories. Include them during exercise selection and duration solving, preserve the 90-minute limit and all other approved requirements, and disclose any conflict rather than silently reducing either minimum. Do not infer a 15–18-set target for calves or abs.

Do not combine unrelated muscle groups into one aggregate target. For example, 17 total sets across quads and hamstrings does not mean both muscles received 17 sets.

### Volume-counting methodology

Use a consistent fractional-set model:

**Effective sets = Direct sets + (Indirect sets × 0.5)**

Definitions:
- **Direct set (1.0):** The muscle is a primary target and receives substantial mechanical tension through a meaningful range of motion.
- **Indirect set (0.5):** The muscle is a substantial secondary contributor.
- **Negligible involvement (0):** Stabilization or incidental activation without meaningful hypertrophic stimulus.

Illustrative examples:

| Exercise | Direct (1.0) | Indirect (0.5) |
|---|---|---|
| Low-incline press | Chest | Anterior delts, triceps |
| Overhead press | Anterior delts | Triceps, lateral delts |
| Pull-up | Lats | Biceps, upper back |
| Row | Upper back | Lats, biceps, rear delts |
| Squat | Quads | Glutes |
| Hip thrust | Glutes | — |
| Leg curl | Hamstrings | — |
| Lateral raise | Lateral delts | — |
| Biceps curl | Biceps | — |
| Triceps extension | Triceps | — |

These are approximate accounting conventions, not exact physiological equivalences. Explain any exercise-specific departures, especially where technique changes muscle emphasis.

Rules:
- Count unilateral exercises per muscle, not per limb. Three sets of split squats per leg count as three sets for quads, not six.
- Do not count warm-ups.
- Only count challenging working sets performed with appropriate technique and proximity to failure.
- Never automatically count every compound exercise as a full set for every muscle involved.
- A set may contribute to multiple muscles, but only once per muscle.
- Audit each muscle's direct, indirect, and effective weekly volume.
- Avoid adding isolation exercises merely to satisfy artificial numerical symmetry when recovery or time makes them impractical.

**15–18 effective sets is the requested programming target, not a scientifically proven universal optimum.** If reaching it for every listed muscle is impractical within 90 minutes, show the conflict explicitly and prioritize the main muscle groups rather than presenting an unrealistic routine.

## 4. ANATOMICAL BALANCE

### Upper-body push/pull

- Aim for broadly comparable weekly pressing and pulling volume.
- Balance horizontal presses with rows and vertical presses with vertical pulls.
- Do not assume pressing and pulling must have exactly identical set counts to protect shoulder health.
- Provide a weekly audit of horizontal and vertical movement patterns.

### Lower-body balance

- Independently track quad, hamstring, and glute stimulation.
- Include both knee-dominant and hip-dominant movement patterns.
- Do not treat all posterior-chain work as interchangeable.
- Avoid excessive axial loading and repeated heavy hinges.

### Shoulder development

- Account for anterior-delt involvement in chest pressing.
- Include dedicated lateral-delt training.
- Include sufficient rear-delt stimulation from appropriately selected rows or isolation exercises.
- Avoid overemphasizing anterior delts solely to reach numeric targets.

### Arms

- Include direct biceps and triceps work where needed.
- Account for their indirect involvement in compound exercises.
- Aim for balanced development, not necessarily identical raw set counts.

## 5. EXERCISE SELECTION

Select exercises across these movement categories:

- Horizontal push.
- Horizontal pull.
- Vertical push.
- Vertical pull.
- Knee-dominant lower body.
- Hip-dominant lower body.
- Knee-flexion hamstring work.
- Shoulder isolation.
- Elbow flexion.
- Elbow extension.
- Calves and core as appropriate.

Selection principles:
- Prioritize stable exercises that allow high muscular effort.
- Favor movements with meaningful progressive overload.
- Use a mixture of compound and isolation exercises.
- Distribute exercises to manage local and systemic fatigue.
- Avoid unnecessary spinal loading.
- Avoid highly unstable exercises that limit effective muscular loading.
- Avoid redundant exercises that contribute little additional stimulus.
- Consider stimulus-to-fatigue ratio when choosing between alternatives.

Each chosen exercise must have a clear hypertrophy purpose and realistic progression method.

## 6. SESSION STRUCTURE AND TIME MANAGEMENT

**Maximum session duration: 90 minutes total.**

Suggested allocation:
- General warm-up and specific ramp-up sets: 8–12 minutes.
- Primary compound work: 15–20 minutes.
- Secondary compound supersets: 25–30 minutes.
- Isolation supersets: 15–20 minutes.
- Accessories and transitions: remaining time.

These are flexible guidelines, not separate mandatory blocks.

### Straight sets

Use straight sets for demanding compound movements when supersets would compromise performance.

Rest:
- Heavy compounds: 2–3 minutes.
- Moderate compounds: 90–150 seconds.

### Supersets

Prefer antagonist or non-competing pairings, including:
- Chest / back.
- Biceps / triceps.
- Upper-body / lower-body movements where systemic fatigue remains manageable.
- Other non-competing muscle groups when equipment setup permits.

Execution:
1. Exercise A.
2. Rest 15–30 seconds, or only as long as needed for a practical transition.
3. Exercise B.
4. Rest 90–120 seconds, adjusted for performance.
5. Repeat.

Longer rest is acceptable when needed to preserve repetitions and technique.

**Equipment efficiency is mandatory.** Do not pair exercises requiring incompatible equipment configurations or substantial adjustments between sets.

### Time verification

Calculate each session's duration using:
- Expected execution time per set.
- Rest intervals.
- Unilateral exercise duration for both legs or arms.
- Warm-up and ramp-up sets.
- Equipment adjustments.
- Realistic transitions.

Do not estimate duration from the number of exercises alone.

If the projected session exceeds 90 minutes, redesign it before presenting the final routine.

## 7. INTENSITY AND PROGRESSION

- Working sets generally finish at 1–2 RIR.
- Larger compounds may use 2–3 RIR initially when fatigue or technique warrants.
- Isolation movements may occasionally reach 0–1 RIR.
- Use a clearly defined rep range for each exercise.
- Double progression is owned by the app; do not define a separate progression policy in the generator.
- Check whether the available configuration can support the intended work; do not prescribe loading/progression workarounds. Resolve unsuitable configurations before selection.
- Track exercises, loads, repetitions, and RIR.
- Do not require repetition drop-off as proof of sufficient intensity.
- The app owns load calibration and progression. Recovery concerns require re-audit before changing set counts; preserve approved minimums unless a specific change is authorized.

## 8. REQUIRED OUTPUT FORMAT

### For each day (A, B, C)

Provide:

1. Session focus.
2. Exercise table with:
   - Block/order.
   - Exercise name.
   - Sets.
   - Repetitions.
   - Target RIR.
   - Rest interval.
   - Primary and secondary muscles.
   - Straight-set or superset designation.
3. Exact warm-up and ramp-up instructions.
4. Superset execution instructions.
5. Equipment setup notes explaining why transitions are practical.
6. Calculated session duration, with a breakdown of exercise time, rest, warm-up, and transitions.
7. Total working sets.

### Weekly volume audit

Provide a table with these columns:

| Muscle | Direct sets | Indirect sets | Effective sets | Target | Status |
|---|---:|---:|---:|---|---|

Use the exact formula:

**Effective = Direct + 0.5 × Indirect**

Show which exercises contribute to each muscle's total so calculations can be independently verified.

Additionally report:
- Horizontal push vs horizontal pull sets.
- Vertical push vs vertical pull sets.
- Quad vs hamstring vs glute effective volume.
- Total direct working sets weekly.
- Session duration for A, B, and C.

### Final validation

Before completing the answer:

- Recalculate every weekly volume total.
- Verify no exercise set was incorrectly counted twice within the same muscle.
- Verify all equipment restrictions.
- Verify every superset can be performed without meaningful reconfiguration.
- Verify all three sessions are full-body.
- Verify all three sessions fit within 90 minutes.
- Identify any target that could not realistically be achieved.

**Do not claim perfect compliance unless the calculations and time estimates demonstrate it.**

---

## 9. PROGRAMMING PRIORITIES

Apply these priorities in descending order when constraints conflict:

1. Safe, effective hypertrophy training.
2. Equipment and space feasibility.
3. Maximum 90-minute session duration.
4. 15–18 effective weekly sets per major muscle group.
5. Balanced muscle development.
6. Practical supersets and efficient transitions.
7. Sustainable progressive overload and fatigue management.

If all targets cannot be achieved simultaneously, explicitly identify the conflict and provide the most effective feasible compromise.

NOTE: for cable exercises use only cable crunch and cable triceps pushdown

**Produce the complete three-day program and its audited weekly totals.**
here is the home gym i've got plus all the available space

## Later approved preferences and restrictions

- Prefer session-duration spread within **5 minutes**. This is soft; the **90-minute** session limit remains hard.
- Use the approved preference order: duration balance, source-backed movement balance, workload economy, exercise-family diversity, then muscle-set distribution. Settle movement doses before diversifying. Demand-distribution optimization is currently suspended; do not invent fatigue scores.
- Lateral-delt work and vertical pulling each require at least **6 qualified working sets weekly across at least 2 sessions**. These approved role floors do not prove compliance with separate original regional-muscle targets.
- At most **15 exercises per session**, at most **3 exercises per superset**, and at least **2 working sets per exercise occurrence**. Do not invent a new superset-count limit.
- Choose and record explicit limits for **sessions per exercise per week** and **working sets per exercise per week**, using the training history, available equipment, intended development and other approved requirements. I delegate choosing these programming limits to the generator; no universal default is implied. Encode them in the structured `exerciseExposure` execution rule and show the selected limits in the requirements preview. Count repeated occurrences of the same library exercise together, including superset members, and count a session once for frequency. Separate exercise definitions remain separate; use reviewed family bounds when a family-wide limit is intended. Check feasibility in code; if the chosen limits conflict with existing requirements, propose a scoped change rather than silently weakening any requirement or claiming the limits are physiological safety thresholds.
- Exclude Sumo Deadlift and the current Dumbbell Squat configuration: the user reports insufficient available loading for their intended training. Preserve the existing cable/pulley/pulldown exclusions and the named Cable Crunch / Cable Tricep Pushdown exceptions.
- Use exact history, reviewed related evidence and available load ceilings when selecting exercises. No exact records means unverified suitability, not approval. Related loads are not equivalent working-load prescriptions.
- Do not generate standalone loading or progression guidance; these are app-owned.

## Approved aggregate targets and known regional limitation

The previously approved Option 1 uses combined Back and combined Shoulders targets; lats, upper back and deltoid heads are reported descriptively from available reviewed annotations. This approved policy supersedes the separate regional minimums in the original request above. Do not reopen that settled choice or invent regional credits. Report unknown regional contributions honestly. Use the accompanying current structured requirements as the numerical authority, including the approved minimum-only shoulder target. Combined compliance is not proof of precise regional development.
