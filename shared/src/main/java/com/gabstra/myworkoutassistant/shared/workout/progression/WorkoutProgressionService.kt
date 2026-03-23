package com.gabstra.myworkoutassistant.shared.workout.progression

import android.util.Log
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.applySetHistoryToProgrammedSet
import com.gabstra.myworkoutassistant.shared.removeRestAndRestPause
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.toSets
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set as WorkoutSet
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.PlateauDetectionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters
import java.util.UUID

data class SessionDecision(
    val progressionState: ProgressionState,
    val shouldLoadLastSuccessfulSession: Boolean,
    val lastSuccessfulSession: ExerciseSessionSnapshot
)

data class ProgressionGenerationResult(
    val progressionByExerciseId: Map<UUID, Pair<DoubleProgressionHelper.Plan, ProgressionState>>,
    val plateauReasonByExerciseId: Map<UUID, String?>
)

class WorkoutProgressionService(
    private val exerciseInfoDao: () -> ExerciseInfoDao,
    private val setHistoryDao: () -> SetHistoryDao,
    private val workoutHistoryDao: () -> WorkoutHistoryDao,
    private val exerciseSessionProgressionDao: () -> ExerciseSessionProgressionDao
) {
    suspend fun computeSessionDecision(exerciseId: UUID): SessionDecision {
        val exerciseInfo = exerciseInfoDao().getExerciseInfoById(exerciseId)
        val fails = exerciseInfo?.sessionFailedCounter?.toInt() ?: 0
        val lastWasDeload = exerciseInfo?.lastSessionWasDeload ?: false
        val today = LocalDate.now()
        var weeklyCount = 0

        exerciseInfo?.weeklyCompletionUpdateDate?.let { lastUpdate ->
            val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
                weeklyCount = exerciseInfo.timesCompletedInAWeek
            }
        }

        val shouldDeload = false
        val shouldRetry = !lastWasDeload && (fails >= 1 || weeklyCount > 1)
        val shouldLoadLastSuccessfulSession = lastWasDeload || shouldRetry
        val progressionState =
            if (shouldDeload) ProgressionState.DELOAD else if (shouldRetry) ProgressionState.RETRY else ProgressionState.PROGRESS

        return SessionDecision(
            progressionState = progressionState,
            shouldLoadLastSuccessfulSession = shouldLoadLastSuccessfulSession,
            lastSuccessfulSession = exerciseInfo?.lastSuccessfulSession ?: ExerciseSessionSnapshot()
        )
    }

    suspend fun generateProgressions(
        selectedWorkout: Workout,
        bodyWeightKg: Double,
        getEquipmentById: (UUID) -> WeightLoadedEquipment?,
        getWeightByEquipment: (WeightLoadedEquipment?) -> kotlin.collections.Set<Double>,
        weightsByEquipment: MutableMap<WeightLoadedEquipment, kotlin.collections.Set<Double>>
    ): ProgressionGenerationResult {
        val progressions = mutableMapOf<UUID, Pair<DoubleProgressionHelper.Plan, ProgressionState>>()
        val plateauReasons = mutableMapOf<UUID, String?>()
        val exercises = selectedWorkout.workoutComponents.filterIsInstance<Exercise>() +
            selectedWorkout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }

        exercises.filter { it.enabled && it.equipmentId != null }.forEach { exercise ->
            val equipment = exercise.equipmentId?.let(getEquipmentById)
            if (equipment != null && !weightsByEquipment.containsKey(equipment)) {
                weightsByEquipment[equipment] = equipment.getWeightsCombinations()
            }
        }

        val validExercises = exercises
            .filter {
                it.enabled &&
                    it.progressionMode != ProgressionMode.OFF &&
                    !it.requiresLoadCalibration
            }
            .filter { it.exerciseType == ExerciseType.WEIGHT || it.exerciseType == ExerciseType.BODY_WEIGHT }

        validExercises.forEach { exercise ->
            val progression = processExercise(
                exercise = exercise,
                bodyWeightKg = bodyWeightKg,
                getEquipmentById = getEquipmentById,
                getWeightByEquipment = getWeightByEquipment,
                weightsByEquipment = weightsByEquipment,
                plateauReasonByExerciseId = plateauReasons
            )
            progressions[exercise.id] = progression
        }

        return ProgressionGenerationResult(
            progressionByExerciseId = progressions,
            plateauReasonByExerciseId = plateauReasons
        )
    }

    fun buildExerciseWithProgression(
        exercise: Exercise,
        plan: DoubleProgressionHelper.Plan,
        bodyWeightKg: Double
    ): Exercise {
        val validSets = removeRestAndRestPause(
            sets = exercise.sets,
            isRestPause = {
                when (it) {
                    is BodyWeightSet -> it.subCategory == SetSubCategory.RestPauseSet
                    is WeightSet -> it.subCategory == SetSubCategory.RestPauseSet
                    else -> false
                }
            },
            isRestSet = { it is RestSet }
        )
        val distributedSets = plan.sets
        val newSets = mutableListOf<WorkoutSet>()
        val exerciseSets = validSets.filter { it !is RestSet }
        val restSets = validSets.filterIsInstance<RestSet>()

        for ((index, setInfo) in distributedSets.withIndex()) {
            if (index > 0) {
                val previousRestSet = restSets.getOrNull(index - 1)
                if (previousRestSet != null) {
                    newSets.add(previousRestSet)
                }
            }

            val setId = exerciseSets.getOrNull(index)?.id ?: UUID.randomUUID()
            val newSet = when (exercise.exerciseType) {
                ExerciseType.BODY_WEIGHT -> {
                    val relativeBodyWeight = bodyWeightKg * (exercise.bodyWeightPercentage!! / 100)
                    BodyWeightSet(setId, setInfo.reps, setInfo.weight - relativeBodyWeight)
                }

                ExerciseType.WEIGHT -> WeightSet(setId, setInfo.reps, setInfo.weight)
                else -> throw IllegalArgumentException("Unknown exercise type")
            }
            newSets.add(newSet)
        }

        return exercise.copy(
            sets = newSets,
            requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList()
        )
    }

    fun buildPreProcessedSets(
        exercise: Exercise,
        latestSetHistoryByKey: Map<Pair<UUID, UUID>, SetHistory>,
        sessionDecision: SessionDecision
    ): List<WorkoutSet> {
        val derivedSets = exercise.sets.map { set ->
            applySetHistoryToProgrammedSet(set, latestSetHistoryByKey[exercise.id to set.id])
        }
        if (!sessionDecision.shouldLoadLastSuccessfulSession) {
            return derivedSets
        }
        val historySets = sessionDecision.lastSuccessfulSession.toSets()
        if (historySets.isEmpty()) {
            return derivedSets
        }
        return mergeLastSuccessfulSessionIntoTemplate(derivedSets, historySets)
    }

    /**
     * Overlays last-successful work-set targets onto the programmed template by set id.
     * Template structure (including every [RestSet] position and duration) is preserved; extra
     * snapshot-only work sets are ignored; template work sets missing from the snapshot are unchanged.
     */
    private fun mergeLastSuccessfulSessionIntoTemplate(
        templateDerivedSets: List<WorkoutSet>,
        snapshotSets: List<WorkoutSet>
    ): List<WorkoutSet> {
        val snapshotWorkById = snapshotSets
            .filter { it !is RestSet }
            .associateBy { it.id }
        return templateDerivedSets.map { set ->
            when (set) {
                is RestSet -> set
                else -> {
                    val replacement = snapshotWorkById[set.id]
                    when {
                        replacement != null && replacement !is RestSet -> replacement
                        else -> set
                    }
                }
            }
        }
    }

    private suspend fun processExercise(
        exercise: Exercise,
        bodyWeightKg: Double,
        getEquipmentById: (UUID) -> WeightLoadedEquipment?,
        getWeightByEquipment: (WeightLoadedEquipment?) -> kotlin.collections.Set<Double>,
        weightsByEquipment: MutableMap<WeightLoadedEquipment, kotlin.collections.Set<Double>>,
        plateauReasonByExerciseId: MutableMap<UUID, String?>
    ): Pair<DoubleProgressionHelper.Plan, ProgressionState> {
        val repsRange = IntRange(exercise.minReps, exercise.maxReps)
        val baseAvailableWeights = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> {
                val equipment = exercise.equipmentId?.let(getEquipmentById)
                if (equipment != null && !weightsByEquipment.containsKey(equipment)) {
                    weightsByEquipment[equipment] = equipment.getWeightsCombinations()
                }
                exercise.equipmentId?.let { getWeightByEquipment(getEquipmentById(it)) } ?: emptySet()
            }

            ExerciseType.BODY_WEIGHT -> {
                val relativeBodyWeight = bodyWeightKg * (exercise.bodyWeightPercentage!! / 100)
                (exercise.equipmentId?.let {
                    getWeightByEquipment(getEquipmentById(it)).map { value -> relativeBodyWeight + value }.toSet()
                } ?: emptySet()) + setOf(relativeBodyWeight)
            }

            else -> throw IllegalArgumentException("Unknown exercise type")
        }
        val sessionDecision = computeSessionDecision(exercise.id)
        val setHistories = setHistoryDao().getSetHistoriesByExerciseId(exercise.id)
        val workoutHistoryIds = setHistories.mapNotNull { it.workoutHistoryId }.toSet()
        val workoutHistories = workoutHistoryDao().getAllWorkoutHistories()
            .filter { it.id in workoutHistoryIds && it.isDone }
            .associateBy { it.id }
        val exerciseProgressions = exerciseSessionProgressionDao().getByExerciseId(exercise.id)
        val progressionStatesByWorkoutHistoryId = exerciseProgressions
            .filter { it.workoutHistoryId in workoutHistoryIds }
            .associate { it.workoutHistoryId to it.progressionState }
        // Prefer equipment from historical snapshot so plateau detection uses the same weight system as past sessions.
        val equipmentIdForPlateau = setHistories.maxByOrNull { it.executionSequence?.toLong() ?: 0L }?.equipmentIdSnapshot
            ?: exercise.equipmentId
        val equipment = equipmentIdForPlateau?.let(getEquipmentById)
        val (isPlateau, _, reason) = PlateauDetectionHelper.detectPlateauFromHistories(
            setHistories = setHistories,
            workoutHistories = workoutHistories,
            progressionStatesByWorkoutHistoryId = progressionStatesByWorkoutHistoryId,
            equipment = equipment
        )
        plateauReasonByExerciseId[exercise.id] = if (isPlateau) reason else null

        val previousSets = removeRestAndRestPause(
            sets = exercise.sets,
            isRestPause = {
                when (it) {
                    is BodyWeightSet -> it.subCategory == SetSubCategory.RestPauseSet
                    is WeightSet -> it.subCategory == SetSubCategory.RestPauseSet
                    else -> false
                }
            },
            isRestSet = { it is RestSet }
        ).filter { it !is RestSet }.map { set ->
            when (set) {
                is BodyWeightSet -> {
                    val relativeBodyWeight = bodyWeightKg * (exercise.bodyWeightPercentage!! / 100)
                    SimpleSet(set.getWeight(relativeBodyWeight), set.reps)
                }

                is WeightSet -> SimpleSet(set.weight, set.reps)
                else -> throw IllegalStateException("Unknown set type encountered after filtering.")
            }
        }

        val previousVolume = previousSets.sumOf { it.weight * it.reps }
        val availableWeights = baseAvailableWeights.toSet()
        val exerciseProgression = when (sessionDecision.progressionState) {
            ProgressionState.DELOAD -> DoubleProgressionHelper.planDeloadSession(
                previousSets = previousSets,
                availableWeights = availableWeights,
                repsRange = repsRange
            )

            ProgressionState.RETRY -> DoubleProgressionHelper.Plan(
                sets = previousSets,
                previousVolume = previousVolume,
                newVolume = previousVolume
            )

            ProgressionState.PROGRESS -> {
                val jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(
                    defaultPct = exercise.loadJumpDefaultPct ?: 0.025,
                    maxPct = exercise.loadJumpMaxPct ?: 0.5,
                    overcapUntil = exercise.loadJumpOvercapUntil ?: 2
                )
                DoubleProgressionHelper.planNextSession(
                    previousSets = previousSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange,
                    jumpPolicy = jumpPolicy
                )
            }

            else -> throw IllegalStateException("Unknown progression state")
        }
        val progressIncrease = if (exerciseProgression.previousVolume == 0.0) {
            0.0
        } else {
            ((exerciseProgression.newVolume - exerciseProgression.previousVolume) / exerciseProgression.previousVolume) * 100
        }
        Log.d(
            "WorkoutViewModel",
            "${exercise.name}: ${exerciseProgression.previousVolume.round(2)} -> ${exerciseProgression.newVolume.round(2)} (${if (progressIncrease > 0) "+" else ""}${progressIncrease.round(2)}%)"
        )
        val couldNotFindProgression =
            sessionDecision.progressionState == ProgressionState.PROGRESS &&
                exerciseProgression.previousVolume.round(2) == exerciseProgression.newVolume.round(2)
        val progressionState = if (couldNotFindProgression) {
            ProgressionState.FAILED
        } else {
            sessionDecision.progressionState
        }
        return exerciseProgression to progressionState
    }
}
