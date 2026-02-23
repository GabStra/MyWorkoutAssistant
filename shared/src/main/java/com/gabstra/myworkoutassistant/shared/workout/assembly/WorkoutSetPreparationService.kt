package com.gabstra.myworkoutassistant.shared.workout.assembly

import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.WarmupPlanner
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.util.UUID

class WorkoutSetPreparationService {
    fun prepareExerciseSets(
        exercise: Exercise,
        priorExercises: List<Exercise>,
        equipment: WeightLoadedEquipment?,
        bodyWeightKg: Double,
        getAvailableTotals: (WeightLoadedEquipment) -> kotlin.collections.Set<Double>
    ): List<Set> {
        val exerciseAllSets = mutableListOf<Set>()
        val exerciseSets = exercise.sets

        if (exercise.generateWarmUpSets &&
            !exercise.requiresLoadCalibration &&
            equipment != null &&
            (exercise.exerciseType == ExerciseType.BODY_WEIGHT || exercise.exerciseType == ExerciseType.WEIGHT)
        ) {
            val (workWeightTotal, workReps) = exerciseSets.first().let {
                when (it) {
                    is BodyWeightSet -> {
                        val relativeBodyWeight = bodyWeightKg * (exercise.bodyWeightPercentage!! / 100)
                        Pair(it.getWeight(relativeBodyWeight), it.reps)
                    }

                    is WeightSet -> Pair(it.weight, it.reps)
                    else -> throw IllegalArgumentException("Unknown set type")
                }
            }

            val availableTotals: kotlin.collections.Set<Double> = when (exercise.exerciseType) {
                ExerciseType.WEIGHT -> getAvailableTotals(equipment)
                ExerciseType.BODY_WEIGHT -> {
                    val relativeBodyWeight = bodyWeightKg * (exercise.bodyWeightPercentage!! / 100)
                    val extraTotals = getAvailableTotals(equipment)
                    extraTotals.map { relativeBodyWeight + it }.toSet() + setOf(relativeBodyWeight)
                }

                else -> throw IllegalArgumentException("Unknown exercise type")
            }

            fun toSetInternalWeight(desiredTotal: Double): Double {
                return when (exercise.exerciseType) {
                    ExerciseType.BODY_WEIGHT -> {
                        val relativeBodyWeight = bodyWeightKg * (exercise.bodyWeightPercentage!! / 100)
                        desiredTotal - relativeBodyWeight
                    }

                    ExerciseType.WEIGHT -> desiredTotal
                    else -> throw IllegalArgumentException("Unknown exercise type")
                }
            }

            fun makeWarmupSet(id: UUID, total: Double, reps: Int): Set {
                val internalWeight = toSetInternalWeight(total)
                return when (exercise.exerciseType) {
                    ExerciseType.BODY_WEIGHT -> BodyWeightSet(id, reps, internalWeight, subCategory = SetSubCategory.WarmupSet)
                    ExerciseType.WEIGHT -> WeightSet(id, reps, internalWeight, subCategory = SetSubCategory.WarmupSet)
                    else -> throw IllegalArgumentException("Unknown exercise type")
                }
            }

            val warmups: List<Pair<Double, Int>> = if (equipment is Barbell && exercise.exerciseType == ExerciseType.WEIGHT) {
                WarmupPlanner.buildWarmupSetsForBarbell(
                    availableTotals = availableTotals,
                    workWeight = workWeightTotal,
                    workReps = workReps,
                    barbell = equipment,
                    exercise = exercise,
                    priorExercises = priorExercises,
                    initialSetup = emptyList(),
                    maxWarmups = 3
                )
            } else {
                WarmupPlanner.buildWarmupSets(
                    availableTotals = availableTotals,
                    workWeight = workWeightTotal,
                    workReps = workReps,
                    exercise = exercise,
                    priorExercises = priorExercises,
                    equipment = equipment,
                    maxWarmups = 3
                )
            }

            warmups.forEach { (total, reps) ->
                exerciseAllSets.add(makeWarmupSet(UUID.randomUUID(), total, reps))
                exerciseAllSets.add(RestSet(UUID.randomUUID(), 60))
            }

            exerciseAllSets.addAll(exerciseSets)
        } else {
            exerciseAllSets.addAll(exerciseSets)
        }

        insertCalibrationSetIfRequired(exercise, equipment, exerciseAllSets)
        return exerciseAllSets
    }

    private fun insertCalibrationSetIfRequired(
        exercise: Exercise,
        equipment: WeightLoadedEquipment?,
        exerciseAllSets: MutableList<Set>
    ) {
        if (!exercise.requiresLoadCalibration) return
        if (exercise.progressionMode == ProgressionMode.AUTO_REGULATION) return
        val supportsCalibration =
            exercise.exerciseType == ExerciseType.WEIGHT ||
                (exercise.exerciseType == ExerciseType.BODY_WEIGHT && equipment != null)
        if (!supportsCalibration) return

        val firstWorkSetIndex = exerciseAllSets.indexOfFirst { set ->
            when (set) {
                is RestSet -> false
                is BodyWeightSet -> set.subCategory == SetSubCategory.WorkSet ||
                    set.subCategory == SetSubCategory.CalibrationPendingSet
                is WeightSet -> set.subCategory == SetSubCategory.WorkSet ||
                    set.subCategory == SetSubCategory.CalibrationPendingSet
                else -> false
            }
        }
        if (firstWorkSetIndex < 0) return

        val firstWorkSet = exerciseAllSets[firstWorkSetIndex]
        val calibrationSet = when (firstWorkSet) {
            is WeightSet -> WeightSet(
                id = UUID.randomUUID(),
                reps = firstWorkSet.reps,
                weight = firstWorkSet.weight,
                subCategory = SetSubCategory.CalibrationSet
            )

            is BodyWeightSet -> BodyWeightSet(
                id = UUID.randomUUID(),
                reps = firstWorkSet.reps,
                additionalWeight = firstWorkSet.additionalWeight,
                subCategory = SetSubCategory.CalibrationSet
            )

            else -> null
        }
        calibrationSet?.let { exerciseAllSets.add(firstWorkSetIndex, it) }
    }
}

