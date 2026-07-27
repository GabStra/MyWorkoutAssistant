package com.gabstra.myworkoutassistant.shared.workout.assembly

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.util.UUID

class WorkoutSupersetAssemblyService {
    fun assemblePreparedPreviewChildStates(
        superset: Superset,
        bodyWeightKg: Double,
        getEquipmentById: (UUID) -> WeightLoadedEquipment?,
        getAvailableTotals: (WeightLoadedEquipment) -> kotlin.collections.Set<Double>,
    ): List<WorkoutState> {
        val setPreparationService = WorkoutSetPreparationService()
        val priorExercises = mutableListOf<Exercise>()
        val preparedExercises = superset.exercises.map { exercise ->
            val equipment = exercise.equipmentId?.let(getEquipmentById)
            val preparedExercise = exercise.copy(
                sets = setPreparationService.prepareExerciseSets(
                    exercise = exercise,
                    priorExercises = priorExercises,
                    equipment = equipment,
                    bodyWeightKg = bodyWeightKg,
                    getAvailableTotals = getAvailableTotals,
                )
            )
            priorExercises += exercise
            preparedExercise
        }
        return assemblePreviewChildStates(superset.copy(exercises = preparedExercises))
    }

    /**
     * Builds a history-free superset sequence for editors and previews, then routes it through
     * the same scheduler used by an active workout.
     */
    fun assemblePreviewChildStates(superset: Superset): List<WorkoutState> {
        val setStateFactory = WorkoutSetStateFactory()
        val queues = superset.exercises.map { exercise ->
            exercise.sets
                .filterNot { it is RestSet }
                .flatMapIndexed { setIndex, set ->
                    val isWarmup = setStateFactory.isWarmupSet(set)
                    val isCalibration = setStateFactory.isCalibrationSet(set)
                    val setData = initializeSetData(set)
                    val setState = setStateFactory.buildWorkoutSetState(
                        exercise = exercise,
                        set = set,
                        setIndex = setIndex,
                        previousSetData = null,
                        currentSetData = setData,
                        historySet = null,
                        plateChangeResult = null,
                        exerciseInfo = null,
                        progressionState = null,
                        isWarmupSet = isWarmup,
                        bodyWeightKg = 0.0,
                        isUnilateral = setStateFactory.isUnilateralExercise(exercise),
                        isCalibrationSet = isCalibration,
                        isCalibrationManagedWorkSet = false,
                        getEquipmentById = { null }
                    )
                    setStateFactory.buildUnilateralSetBlock(exercise, setState, setIndex)
                        ?.childStates
                        ?: listOf(setState)
                }
                .toMutableList()
        }
        return assembleSupersetChildStates(superset, queues)
    }

    fun assembleSupersetChildStates(
        superset: Superset,
        queues: List<MutableList<WorkoutState>>
    ): MutableList<WorkoutState> {
        val out = mutableListOf<WorkoutState>()

        // Calibration load selection is a required pre-workout step. Keep one selection per
        // superset member ahead of warm-ups and work rounds so the normal confirmation flow can
        // insert that exercise's warm-ups and calibration execution states into this container.
        for (queue in queues) {
            while (queue.firstOrNull() is WorkoutState.CalibrationLoadSelection) {
                out.add(queue.removeAt(0))
            }
        }

        var anyWarmups = true
        while (anyWarmups) {
            anyWarmups = false
            for (q in queues) {
                if (q.isEmpty() || q.first() !is WorkoutState.Set) continue
                val s = q.first() as WorkoutState.Set
                if (!isWarmupSet(s)) continue

                anyWarmups = true
                out.addAll(removeNextSetBlock(q))
                removeLeadingRests(q)
            }
        }

        var anyCalibrationSets = true
        while (anyCalibrationSets) {
            anyCalibrationSets = false
            for (queue in queues) {
                if (queue.isEmpty() || queue.first() !is WorkoutState.Set) continue
                val setState = queue.first() as WorkoutState.Set
                if (!setState.isCalibrationSet) continue

                anyCalibrationSets = true
                out.addAll(removeNextSetBlock(queue))
                removeLeadingRests(queue)
            }
        }

        for (q in queues) {
            while (q.isNotEmpty() && q.first() is WorkoutState.Rest) q.removeAt(0)
        }

        val rounds = queues.minOfOrNull { workCount(it) } ?: 0

        for (round in 0 until rounds) {
            for (q in queues) {
                while (q.isNotEmpty() && q.first() !is WorkoutState.Set) q.removeAt(0)
                if (q.isEmpty()) continue

                val s = q.first() as WorkoutState.Set
                if (s.isWarmupSet) {
                    q.removeAt(0)
                    continue
                }

                out.addAll(removeNextSetBlock(q))

                val restSec = superset.restSecondsByExercise[s.exerciseId] ?: 0
                if (restSec > 0) {
                    val restSet = RestSet(UUID.randomUUID(), restSec)
                    out.add(
                        WorkoutState.Rest(
                            set = restSet,
                            order = (round + 1).toUInt(),
                            currentSetDataState = mutableStateOf(initializeSetData(restSet)),
                            exerciseId = s.exerciseId
                        )
                    )
                }

                removeLeadingRests(q)
            }
        }

        return cleanupRedundantRests(out)
    }

    private fun cleanupRedundantRests(states: List<WorkoutState>): MutableList<WorkoutState> {
        val cleaned = mutableListOf<WorkoutState>()
        for (state in states) {
            if (state is WorkoutState.Rest) {
                if (cleaned.isEmpty() || cleaned.last() is WorkoutState.Rest) continue
            }
            cleaned.add(state)
        }
        while (cleaned.firstOrNull() is WorkoutState.Rest) cleaned.removeAt(0)
        while (cleaned.lastOrNull() is WorkoutState.Rest) cleaned.removeAt(cleaned.lastIndex)
        return cleaned
    }

    private fun workCount(queue: MutableList<WorkoutState>): Int {
        return queue.count {
            it is WorkoutState.Set &&
                !isWarmupSet(it) &&
                !it.isCalibrationSet &&
                (!it.isUnilateral || it.intraSetCounter == 1u)
        }
    }

    /**
     * Removes one logical set from a flattened exercise queue.
     *
     * A unilateral set is represented as left side, intra-set rest, right side. Superset
     * scheduling must keep that entire sequence together before moving to the next exercise.
     */
    private fun removeNextSetBlock(queue: MutableList<WorkoutState>): List<WorkoutState> {
        val firstSide = queue.removeAt(0) as WorkoutState.Set
        if (!firstSide.isUnilateral || firstSide.intraSetCounter != 1u) {
            return listOf(firstSide)
        }

        val block = mutableListOf<WorkoutState>(firstSide)
        if (queue.firstOrNull() is WorkoutState.Rest &&
            (queue.first() as WorkoutState.Rest).isIntraSetRest
        ) {
            block.add(queue.removeAt(0))
        }
        val secondSide = queue.firstOrNull() as? WorkoutState.Set
        if (secondSide?.isUnilateral == true && secondSide.set.id == firstSide.set.id) {
            block.add(queue.removeAt(0))
        }
        return block
    }

    private fun removeLeadingRests(queue: MutableList<WorkoutState>) {
        while (queue.firstOrNull() is WorkoutState.Rest) queue.removeAt(0)
    }

    private fun isWarmupSet(state: WorkoutState.Set): Boolean {
        return when (val set = state.set) {
            is BodyWeightSet -> set.subCategory == SetSubCategory.WarmupSet
            is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
            else -> false
        }
    }
}


