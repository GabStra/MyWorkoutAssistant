package com.gabstra.myworkoutassistant.shared.utils

import android.util.Log
import com.gabstra.myworkoutassistant.shared.ExerciseCategory
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlin.math.abs
import kotlin.math.max

data class WarmupContext(
    val isFirstExerciseInWorkout: Boolean,
    val muscleOverlapRatio: Double,
    val previousExerciseSameEquipment: Boolean,
    val isSupersetFollowUp: Boolean,
)

object WarmupPlanner {
    private const val TAG = "WarmupPlanner"

    private data class WarmupProfile(
        val targetFractions: List<Double>,
        val fixedReps: List<Int>,
    )

    private fun resolveWarmupProfile(
        workReps: Int,
        maxWarmups: Int,
        exercise: Exercise,
        priorExercises: List<Exercise>,
        equipment: Equipment?
    ): WarmupProfile {
        // Category-driven profiles (NSCA/ACSM). When set, use evidence-based volume; otherwise fall back to legacy heuristics.
        val category = exercise.exerciseCategory
        if (category != null) {
            return resolveWarmupProfileByCategory(
                category = category,
                workReps = workReps,
                maxWarmups = maxWarmups,
                equipment = equipment,
                priorExercises = priorExercises,
                exercise = exercise
            )
        }

        // Fallback: legacy logic (workReps + equipment + repeated lift) for exercises without exerciseCategory
        val baseCount = when {
            workReps >= 12 -> 2
            workReps >= 8 -> 2
            workReps >= 5 -> 3
            else -> 3
        }

        var count = baseCount.coerceAtMost(maxWarmups)

        if (equipment != null) {
            val isIsolation = equipment.type == EquipmentType.MACHINE ||
                    equipment.type == EquipmentType.DUMBBELL ||
                    equipment.type == EquipmentType.DUMBBELLS
            if (isIsolation) {
                count -= 1
            }
        }

        val isRepeatedLift = priorExercises.any { it.id == exercise.id }
        if (isRepeatedLift) {
            count = max(2, count)
        }

        count = count.coerceIn(2, maxWarmups)

        return when (count) {
            4 -> WarmupProfile(
                targetFractions = listOf(0.0, 0.40, 0.60, 0.75, 0.90),
                fixedReps = listOf(6, 4, 2, 1)
            )
            3 -> WarmupProfile(
                targetFractions = listOf(0.0, 0.40, 0.60, 0.80),
                fixedReps = listOf(6, 3, 1)
            )
            else -> WarmupProfile(
                targetFractions = listOf(0.0, 0.50, 0.70),
                fixedReps = listOf(5, 2)
            )
        }
    }

    /**
     * Evidence-based warm-up profile by exercise category (NSCA/ACSM).
     * Heavy: 2-3 sets, ≤9 total reps. Moderate: 1-2 sets, 4-6 reps. Isolation: 0-1 sets, 2-4 reps.
     */
    private fun resolveWarmupProfileByCategory(
        category: ExerciseCategory,
        workReps: Int,
        maxWarmups: Int,
        equipment: Equipment?,
        priorExercises: List<Exercise>,
        exercise: Exercise
    ): WarmupProfile {

        val isRepeatedLift = priorExercises.any { it.id == exercise.id }
        val includeEmptyBar = equipment is Barbell

        // Utility helpers
        fun cap(steps: List<Pair<Double, Int>>): List<Pair<Double, Int>> =
            steps.take(maxWarmups.coerceAtLeast(0))

        fun reduceForRepeat(steps: List<Pair<Double, Int>>): List<Pair<Double, Int>> =
            if (!isRepeatedLift || steps.size <= 1) steps else steps.drop(1)

        return when (category) {

            ExerciseCategory.HEAVY_COMPOUND -> {
                /*
                * Canonical heavy compound warm-up
                * ≤9 total reps, monotonic load, optional primer
                *
                * Base:
                *   0.0 × 5   (empty bar)
                *   0.50 × 5
                *   0.70 × 3
                * Optional:
                *   0.85 × 1  (only if workReps < 8)
                */

                val includePrimer = workReps < 8

                val base = buildList {
                    if (includeEmptyBar) add(0.0 to 5)
                    add(0.50 to 5)
                    add(0.70 to 3)
                    if (includePrimer) add(0.85 to 1)
                }

                val adjusted = reduceForRepeat(base)

                WarmupProfile(
                    targetFractions = cap(adjusted).map { it.first },
                    fixedReps = cap(adjusted).map { it.second }
                )
            }

            ExerciseCategory.MODERATE_COMPOUND -> {
                /*
                * Moderate compound
                * 4–6 total warm-up reps
                *
                * Base:
                *   0.0 × 3
                *   0.70 × 3
                */

                val base = buildList {
                    if (includeEmptyBar) add(0.0 to 3)
                    add(0.70 to 3)
                }

                val adjusted = reduceForRepeat(base)

                WarmupProfile(
                    targetFractions = cap(adjusted).map { it.first },
                    fixedReps = cap(adjusted).map { it.second }
                )
            }

            ExerciseCategory.ISOLATION -> {
                /*
                * Isolation
                * Often no warm-up if muscle already trained
                * Otherwise minimal neural rehearsal
                *
                * Base:
                *   0.65 × 4
                */

                val muscleAlreadyTrained = priorExercises.any { prior ->
                    exercise.muscleGroups != null &&
                    prior.muscleGroups != null &&
                    exercise.muscleGroups.intersect(prior.muscleGroups).isNotEmpty()
                }

                if (muscleAlreadyTrained) {
                    WarmupProfile(
                        targetFractions = emptyList(),
                        fixedReps = emptyList()
                    )
                } else {
                    WarmupProfile(
                        targetFractions = listOf(0.65),
                        fixedReps = listOf(4)
                    )
                }
            }
        }
    }

    /**
     * Gap-based warm-up planner (device-agnostic) with optional barbell-style convenience filtering.
     *
     * Inputs are TOTALS (already include bar/handles or BW for bodyweight work):
     * - availableTotals: feasible totals for the implement, sorted (e.g., [BW, BW+1, ...] or [20, 25, 30, ...]).
     * - workWeight: planned working total (already BW+extra, or bar+plates, etc.).
     * - workReps: target reps of the working set.
     *
     * Options:
     * - convenienceStepKgTotal: if set (e.g., 5.0 for barbells = 2.5/side), keep only totals aligned to this step from the anchor.
     * - baseAnchorTotal: anchor to compute convenience steps from (e.g., 20.0 empty bar). Defaults to the minimal feasible total < work.
     *
     * Policy:
     * - Choose up to [maxWarmups] checkpoints strictly below work, at ~40-50%, 60-70%, 75-80% (and optional 90%) of the gap.
     * - Snap each checkpoint DOWN to the nearest feasible total.
     * - Use fixed rep counts that scale only with warmup step order, not work reps.
     */
    fun buildWarmupSets(
        availableTotals: Collection<Double>,
        workWeight: Double,
        workReps: Int,
        exercise: Exercise,
        priorExercises: List<Exercise>,
        equipment: Equipment?,
        maxWarmups: Int = 3,
        baseAnchorTotal: Double? = null,
        convenienceStepKgTotal: Double? = null,
    ): List<Pair<Double, Int>> {
        if (availableTotals.isEmpty()) return emptyList()

        val choicesRaw = availableTotals
            .filter { it < workWeight }
            .distinct()
            .sorted()
        if (choicesRaw.isEmpty()) return emptyList()

        val anchor = baseAnchorTotal ?: choicesRaw.first()

        // Optional barbell-style convenience filter (e.g., 5 kg total jumps)
        val choices = if (convenienceStepKgTotal != null && convenienceStepKgTotal > 0.0) {
            val tol = 0.125 // kg tolerance for float rounding
            val filtered = choicesRaw.filter { isMultipleOfStep(anchor, it, convenienceStepKgTotal, tol) }
            if (filtered.size >= 2) filtered else choicesRaw // fall back if too aggressive
        } else {
            choicesRaw
        }

        val minVal = choices.first()
        val gap = (workWeight - minVal).coerceAtLeast(0.0)

        // Resolve warmup profile with new logic
        val profile = resolveWarmupProfile(
            workReps = workReps,
            maxWarmups = maxWarmups,
            exercise = exercise,
            priorExercises = priorExercises,
            equipment = equipment
        )

        val targetFractions = profile.targetFractions
        if (targetFractions.isEmpty()) return emptyList()

        val targets = targetFractions
            .map { f -> minVal + gap * f }
            .map { t -> floorToChoice(choices, t) ?: minVal }
            .filter { it < workWeight }
            .distinct()

        if (targets.isEmpty()) return emptyList()

        val selected = targets

        // Use fixed reps from profile (no scaling with work reps)
        val fixedReps = profile.fixedReps
        val warmups = selected.mapIndexed { i, total ->
            val reps = fixedReps.getOrElse(i) { fixedReps.lastOrNull() ?: 1 }
            total to reps
        }

        return warmups
    }

    private fun isMultipleOfStep(anchor: Double, value: Double, step: Double, tol: Double): Boolean {
        val diff = value - anchor
        if (diff < -tol) return false
        val rem = diff % step
        return abs(rem) <= tol || abs(rem - step) <= tol
    }

    private fun floorToChoice(choices: List<Double>, target: Double): Double? {
        var lo = 0
        var hi = choices.lastIndex
        var ans: Double? = null
        while (lo <= hi) {
            val mid = (lo + hi) ushr 1
            val v = choices[mid]
            if (v <= target) { ans = v; lo = mid + 1 } else hi = mid - 1
        }
        return ans
    }

    /**
     * Barbell-specific warm-up planner that optimizes weights to minimize plate changes
     * while staying close to desired work weight percentages.
     *
     * This function combines the percentage-based warm-up planning with plate change optimization
     * specifically for barbell exercises. It uses the new optimizeWeightsForPercentages method
     * which provides two-phase optimization (add-only first, then fallback).
     *
     * @param availableTotals Feasible totals for the barbell (including bar weight), sorted
     * @param workWeight Planned working total (bar + plates)
     * @param workReps Target reps of the working set
     * @param barbell The barbell equipment instance
     * @param exercise The exercise for which warmups are being generated
     * @param priorExercises List of exercises that appeared before this one in the workout
     * @param initialSetup List of plates already on one side of the bar before the first set
     * @param maxWarmups Maximum number of warm-up sets to generate
     * @param baseAnchorTotal Anchor to compute convenience steps from (e.g., 20.0 empty bar)
     * @param convenienceStepKgTotal If set (e.g., 5.0 for barbells = 2.5/side), keep only totals aligned to this step
     * @param additionalWorkWeights Optional list of known work weights after the first (e.g. set 2, set 3). The optimizer minimizes plate changes across warmups → workWeight → additionalWorkWeights.
     * @return List of optimized warm-up sets as (weight, reps) pairs
     */
    fun buildWarmupSetsForBarbell(
        availableTotals: Collection<Double>,
        workWeight: Double,
        workReps: Int,
        barbell: Barbell,
        exercise: Exercise,
        priorExercises: List<Exercise>,
        initialSetup: List<Double> = emptyList(),
        maxWarmups: Int = 3,
        baseAnchorTotal: Double? = null,
        convenienceStepKgTotal: Double? = null,
        additionalWorkWeights: List<Double> = emptyList(),
    ): List<Pair<Double, Int>> {
        if (workWeight <= barbell.barWeight) return emptyList()

        // Resolve warmup profile with new logic
        val profile = resolveWarmupProfile(
            workReps = workReps,
            maxWarmups = maxWarmups,
            exercise = exercise,
            priorExercises = priorExercises,
            equipment = barbell
        )

        val targetFractions = profile.targetFractions
        val fixedReps = profile.fixedReps

        // Filter out 0.0 (empty bar) to get work weight percentages
        val workWeightPercentages = targetFractions.filter { it > 1e-9 }

        // Try using the new optimizeWeightsForPercentages method
        try {
            if (workWeightPercentages.isNotEmpty()) {
                val optimizedWeights = PlateCalculator.optimizeWeightsForPercentages(
                    workWeight = workWeight,
                    weightPercentages = workWeightPercentages,
                    barbell = barbell,
                    initialPlates = initialSetup,
                    toleranceBandPercent = 0.05,
                    additionalWorkWeights = additionalWorkWeights
                )

                // Check if we got valid results
                if (optimizedWeights.isNotEmpty() && optimizedWeights.size == workWeightPercentages.size) {
                    // Map optimized weights back to (weight, reps) pairs using fixed reps
                    val optimizedWarmups = mutableListOf<Pair<Double, Int>>()

                    // Handle empty bar (0.0 percentage) if it was in the original profile
                    var weightIndex = 0
                    var repIndex = 0

                    for (fraction in targetFractions) {
                        if (abs(fraction) < 1e-9) {
                            // Empty bar - use bar weight only
                            val reps = fixedReps.getOrElse(repIndex) { fixedReps.lastOrNull() ?: 1 }
                            optimizedWarmups.add(barbell.barWeight to reps)
                            repIndex++
                        } else {
                            // Use optimized weight
                            if (weightIndex < optimizedWeights.size) {
                                val reps = fixedReps.getOrElse(repIndex) { fixedReps.lastOrNull() ?: 1 }
                                optimizedWarmups.add(optimizedWeights[weightIndex] to reps)
                                weightIndex++
                                repIndex++
                            }
                        }
                    }

                    return optimizedWarmups
                }
            }
        } catch (e: Exception) {
            // Fall through: return empty (no fallback)
        }

        Log.d(TAG, "No warmups: percentage-within-band path did not produce warmups")
        return emptyList()
    }
}
