package com.gabstra.myworkoutassistant.shared.workout.persistence

import android.util.Log
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.addSetToExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.removeSetsFromExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutComponentsRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.copySetData
import com.gabstra.myworkoutassistant.shared.getNewSetFromSetHistory
import com.gabstra.myworkoutassistant.shared.sanitizeRestPlacementInSetHistories
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.stores.ExecutedSetStore
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.persistence.WorkoutSetHistoryOps
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.DayOfWeek
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID
import java.time.temporal.TemporalAdjusters

internal class WorkoutPersistenceCoordinator(
    private val executedSetStore: ExecutedSetStore,
    private val workoutHistoryDao: () -> WorkoutHistoryDao,
    private val setHistoryDao: () -> SetHistoryDao,
    private val exerciseInfoDao: () -> ExerciseInfoDao,
    private val exerciseSessionProgressionDao: () -> ExerciseSessionProgressionDao,
    private val workoutStoreRepository: () -> WorkoutStoreRepository,
    private val tag: String = "WorkoutViewModel"
) {
    data class SetHistorySnapshot(
        val setHistory: SetHistory,
        val setId: UUID,
        val order: UInt,
        val exerciseId: UUID?
    )

    data class PushWorkoutDataSnapshot(
        val startWorkoutTime: LocalDateTime,
        val selectedWorkout: Workout,
        val currentWorkoutHistory: WorkoutHistory?,
        val heartBeatRecords: List<Int>,
        val executedSetsHistory: List<SetHistory>,
        val progressionByExerciseId: Map<UUID, Pair<DoubleProgressionHelper.Plan, ProgressionState>>,
        val capturedAt: LocalDateTime
    )

    fun captureSetHistorySnapshot(
        currentState: WorkoutState,
        exercisesById: Map<UUID, Exercise>,
        supersetIdByExerciseId: Map<UUID, UUID>,
        exercisesBySupersetId: Map<UUID, List<Exercise>>
    ): SetHistorySnapshot? {
        val historyIdentity = WorkoutStateQueries.stateHistoryIdentity(currentState) ?: return null
        if (WorkoutSetHistoryOps.shouldSkipPersistingState(currentState, exercisesById)) return null

        val setData = when (currentState) {
            is WorkoutState.Set -> currentState.currentSetData
            is WorkoutState.Rest -> currentState.currentSetData
            else -> return null
        }
        val setDataSnapshot = copySetData(setData)
        val startTime = when (currentState) {
            is WorkoutState.Set -> currentState.startTime ?: LocalDateTime.now()
            is WorkoutState.Rest -> currentState.startTime ?: LocalDateTime.now()
            else -> return null
        }

        if (currentState is WorkoutState.Set && (setData is TimedDurationSetData || setData is EnduranceSetData)) {
            val timerInfo = when (setData) {
                is TimedDurationSetData -> "TimedDurationSet: startTimer=${setData.startTimer}ms, endTimer=${setData.endTimer}ms, startTime=$startTime"
                is EnduranceSetData -> "EnduranceSet: startTimer=${setData.startTimer}ms, endTimer=${setData.endTimer}ms, startTime=$startTime"
                else -> ""
            }
            Log.d(tag, "Storing timer state: $timerInfo")
        }

        val skipped = (currentState as? WorkoutState.Set)?.skipped ?: false
        val supersetMetadata = resolveSupersetMetadata(
            exerciseId = historyIdentity.exerciseId,
            order = historyIdentity.order,
            supersetIdByExerciseId = supersetIdByExerciseId,
            exercisesBySupersetId = exercisesBySupersetId
        )
        val nextExecutionSequence = (
            executedSetStore.executedSets.value.maxOfOrNull { it.executionSequence?.toLong() ?: 0L } ?: 0L
        ) + 1L
        val newSetHistory = SetHistory(
            id = UUID.randomUUID(),
            setId = historyIdentity.setId,
            setData = setDataSnapshot,
            order = historyIdentity.order,
            skipped = skipped,
            exerciseId = historyIdentity.exerciseId,
            startTime = startTime,
            endTime = LocalDateTime.now(),
            supersetId = supersetMetadata?.supersetId,
            supersetRound = supersetMetadata?.supersetRound,
            supersetExerciseIndex = supersetMetadata?.supersetExerciseIndex,
            executionSequence = nextExecutionSequence.toUInt()
        )

        return SetHistorySnapshot(
            setHistory = newSetHistory,
            setId = historyIdentity.setId,
            order = historyIdentity.order,
            exerciseId = historyIdentity.exerciseId
        )
    }

    suspend fun upsertSetHistorySnapshot(snapshot: SetHistorySnapshot) {
        val key: (SetHistory) -> Boolean = { history ->
            WorkoutStateQueries.matchesSetHistory(
                history,
                snapshot.setId,
                snapshot.order,
                snapshot.exerciseId
            )
        }
        val existing = executedSetStore.executedSets.value.firstOrNull(key)
        val normalizedSnapshot = if (existing?.executionSequence != null) {
            snapshot.setHistory.copy(executionSequence = existing.executionSequence)
        } else {
            snapshot.setHistory
        }
        executedSetStore.upsert(normalizedSnapshot, key)
    }

    fun capturePushWorkoutDataSnapshot(
        startWorkoutTime: LocalDateTime?,
        selectedWorkout: Workout,
        currentWorkoutHistory: WorkoutHistory?,
        heartBeatRecords: List<Int>,
        progressionByExerciseId: Map<UUID, Pair<DoubleProgressionHelper.Plan, ProgressionState>>
    ): PushWorkoutDataSnapshot? {
        val startTime = startWorkoutTime ?: return null
        val executedSetsSnapshot = cloneSetHistories(executedSetStore.executedSets.value)
        return PushWorkoutDataSnapshot(
            startWorkoutTime = startTime,
            selectedWorkout = selectedWorkout,
            currentWorkoutHistory = currentWorkoutHistory,
            heartBeatRecords = heartBeatRecords,
            executedSetsHistory = executedSetsSnapshot,
            progressionByExerciseId = progressionByExerciseId,
            capturedAt = LocalDateTime.now()
        )
    }

    suspend fun pushWorkoutData(
        snapshot: PushWorkoutDataSnapshot,
        isDone: Boolean,
        updateWorkoutStore: (WorkoutStore) -> Unit
    ): WorkoutHistory {
        val selectedWorkoutSnapshot = snapshot.selectedWorkout
        val progressionByExerciseIdSnapshot = snapshot.progressionByExerciseId
        val duration = Duration.between(snapshot.startWorkoutTime, snapshot.capturedAt)
        val workoutHistoryDaoRef = workoutHistoryDao()
        val setHistoryDaoRef = setHistoryDao()
        val exerciseInfoDaoRef = exerciseInfoDao()
        val exerciseSessionProgressionDaoRef = exerciseSessionProgressionDao()
        val workoutStoreRepositoryRef = workoutStoreRepository()

        var currentWorkoutHistorySnapshot = snapshot.currentWorkoutHistory

        if (currentWorkoutHistorySnapshot == null) {
            currentWorkoutHistorySnapshot = WorkoutHistory(
                id = UUID.randomUUID(),
                workoutId = selectedWorkoutSnapshot.id,
                date = snapshot.capturedAt.toLocalDate(),
                duration = duration.seconds.toInt(),
                heartBeatRecords = snapshot.heartBeatRecords,
                time = snapshot.capturedAt.toLocalTime(),
                startTime = snapshot.startWorkoutTime,
                isDone = isDone,
                hasBeenSentToHealth = false,
                globalId = selectedWorkoutSnapshot.globalId
            )
        } else {
            currentWorkoutHistorySnapshot = currentWorkoutHistorySnapshot.copy(
                duration = duration.seconds.toInt(),
                heartBeatRecords = snapshot.heartBeatRecords,
                time = snapshot.capturedAt.toLocalTime(),
                isDone = isDone,
                hasBeenSentToHealth = false,
                version = currentWorkoutHistorySnapshot.version.inc()
            )
        }
        val workoutHistoryForThisPush = currentWorkoutHistorySnapshot ?: error("WorkoutHistory snapshot is null")

        val newExecutedSetsHistory = snapshot.executedSetsHistory.map {
            it.copy(
                workoutHistoryId = workoutHistoryForThisPush.id,
                setData = copySetData(it.setData)
            )
        }

        executedSetStore.replaceAll(newExecutedSetsHistory)
        workoutHistoryDaoRef.insertWithVersionCheck(workoutHistoryForThisPush)
        setHistoryDaoRef.insertAllWithVersionCheck(*newExecutedSetsHistory.toTypedArray())

        if (isDone) {
            val executedSetsHistoryByExerciseId = newExecutedSetsHistory.groupBy { it.exerciseId }
            val exercises = flattenExercises(selectedWorkoutSnapshot)

            executedSetsHistoryByExerciseId.forEach { entry ->
                val exercise = exercises.firstOrNull { item -> item.id == entry.key }
                if (exercise == null) {
                    Log.e(tag, "Exercise with id ${entry.key} not found")
                    return@forEach
                }

                val isTrackableExercise = !exercise.doNotStoreHistory &&
                    (exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT)
                if (!isTrackableExercise) return@forEach

                val progressionData = progressionByExerciseIdSnapshot[entry.key]
                val exerciseProgression = progressionData?.first
                val progressionState = progressionData?.second
                val isDeloadSession = progressionState == ProgressionState.DELOAD
                val exerciseHistories = entry.value

                val currentSession = sanitizeRestPlacementInSetHistories(exerciseHistories)
                    .filter {
                        when (val sd = it.setData) {
                            is BodyWeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                            is WeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                            is RestSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                            else -> true
                        }
                    }

                val exerciseId = entry.key ?: return@forEach
                val exerciseInfo = exerciseInfoDaoRef.getExerciseInfoById(exerciseId)
                val today = LocalDate.now()

                var weeklyCount = 0
                if (exerciseInfo != null) {
                    val lastUpdate = exerciseInfo.weeklyCompletionUpdateDate
                    if (lastUpdate != null) {
                        val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                        val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                        if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
                            weeklyCount = exerciseInfo.timesCompletedInAWeek
                        }
                    }
                }
                weeklyCount++

                val executedSets = currentSession.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet || setData.subCategory == SetSubCategory.CalibrationSet) return@mapNotNull null
                            SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet || setData.subCategory == SetSubCategory.CalibrationSet) return@mapNotNull null
                            SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }

                val expectedSets = exerciseProgression?.sets ?: emptyList()
                val vsExpected = if (exerciseProgression != null) {
                    compareSetListsUnordered(executedSets, expectedSets)
                } else {
                    Ternary.EQUAL
                }

                val lastSessionFromHistory = getLastSessionFromHistory(
                    exerciseId,
                    selectedWorkoutSnapshot.globalId,
                    workoutHistoryForThisPush.id
                )
                val previousSessionSets = if (lastSessionFromHistory.isNotEmpty()) {
                    lastSessionFromHistory.mapNotNull { setHistory ->
                        when (val setData = setHistory.setData) {
                            is WeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            is BodyWeightSetData -> {
                                if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            else -> null
                        }
                    }
                } else {
                    emptyList()
                }

                val vsPrevious = if (previousSessionSets.isNotEmpty()) {
                    compareSetListsUnordered(executedSets, previousSessionSets)
                } else {
                    Ternary.EQUAL
                }

                val previousSessionVolume = previousSessionSets.sumOf { it.weight * it.reps }
                val expectedVolume = expectedSets.sumOf { it.weight * it.reps }
                val executedVolume = executedSets.sumOf { it.weight * it.reps }

                if (exerciseInfo == null) {
                    val newExerciseInfo = com.gabstra.myworkoutassistant.shared.ExerciseInfo(
                        id = exerciseId,
                        bestSession = currentSession,
                        lastSuccessfulSession = currentSession,
                        successfulSessionCounter = 1u,
                        sessionFailedCounter = 0u,
                        timesCompletedInAWeek = weeklyCount,
                        weeklyCompletionUpdateDate = today,
                        lastSessionWasDeload = false,
                    )
                    exerciseInfoDaoRef.insert(newExerciseInfo)
                } else {
                    var updatedInfo = exerciseInfo.copy(version = exerciseInfo.version + 1u)

                    if (isDeloadSession) {
                        updatedInfo = updatedInfo.copy(
                            sessionFailedCounter = 0u,
                            successfulSessionCounter = 0u,
                            lastSessionWasDeload = true
                        )
                    } else {
                        updatedInfo = updatedInfo.copy(lastSessionWasDeload = false)

                        val bestSessionSets = updatedInfo.bestSession.mapNotNull { setHistory ->
                            when (val setData = setHistory.setData) {
                                is WeightSetData -> {
                                    if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                    SimpleSet(setData.getWeight(), setData.actualReps)
                                }
                                is BodyWeightSetData -> {
                                    if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                    SimpleSet(setData.getWeight(), setData.actualReps)
                                }
                                else -> null
                            }
                        }

                        if (compareSetListsUnordered(executedSets, bestSessionSets) == Ternary.ABOVE) {
                            updatedInfo = updatedInfo.copy(bestSession = currentSession)
                        }

                        if (progressionState != null) {
                            when (progressionState) {
                                ProgressionState.PROGRESS -> {
                                    val isSuccess = exerciseProgression != null &&
                                        expectedSets.isNotEmpty() &&
                                        (vsExpected == Ternary.ABOVE || vsExpected == Ternary.EQUAL)
                                    updatedInfo = if (isSuccess) {
                                        updatedInfo.copy(
                                            lastSuccessfulSession = currentSession,
                                            successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                            sessionFailedCounter = 0u
                                        )
                                    } else {
                                        updatedInfo.copy(
                                            successfulSessionCounter = 0u,
                                            sessionFailedCounter = updatedInfo.sessionFailedCounter.inc()
                                        )
                                    }
                                }
                                ProgressionState.RETRY -> {
                                    updatedInfo = when (vsExpected) {
                                        Ternary.ABOVE -> updatedInfo.copy(
                                            lastSuccessfulSession = currentSession,
                                            successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                            sessionFailedCounter = 0u
                                        )
                                        Ternary.EQUAL -> updatedInfo.copy(
                                            lastSuccessfulSession = currentSession,
                                            successfulSessionCounter = 0u,
                                            sessionFailedCounter = 0u
                                        )
                                        Ternary.BELOW, Ternary.MIXED -> updatedInfo
                                    }
                                }
                                ProgressionState.FAILED -> {
                                    updatedInfo = updatedInfo.copy(
                                        successfulSessionCounter = 0u,
                                        sessionFailedCounter = updatedInfo.sessionFailedCounter.inc()
                                    )
                                }
                                ProgressionState.DELOAD -> Unit
                            }
                        } else {
                            if (exerciseProgression != null && expectedSets.isNotEmpty()) {
                                updatedInfo = when {
                                    vsExpected == Ternary.BELOW || vsExpected == Ternary.MIXED -> {
                                        updatedInfo.copy(
                                            successfulSessionCounter = 0u,
                                            sessionFailedCounter = updatedInfo.sessionFailedCounter.inc()
                                        )
                                    }
                                    vsExpected == Ternary.ABOVE || vsExpected == Ternary.EQUAL -> {
                                        updatedInfo.copy(
                                            lastSuccessfulSession = currentSession,
                                            successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                            sessionFailedCounter = 0u
                                        )
                                    }
                                    else -> updatedInfo
                                }
                            } else {
                                val lastSessionSets = updatedInfo.lastSuccessfulSession.mapNotNull { setHistory ->
                                    when (val setData = setHistory.setData) {
                                        is WeightSetData -> {
                                            if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                            SimpleSet(setData.getWeight(), setData.actualReps)
                                        }
                                        is BodyWeightSetData -> {
                                            if (setData.subCategory == SetSubCategory.RestPauseSet) return@mapNotNull null
                                            SimpleSet(setData.getWeight(), setData.actualReps)
                                        }
                                        else -> null
                                    }
                                }
                                updatedInfo = when (compareSetListsUnordered(executedSets, lastSessionSets)) {
                                    Ternary.ABOVE -> updatedInfo.copy(
                                        lastSuccessfulSession = currentSession,
                                        successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                        sessionFailedCounter = 0u
                                    )
                                    Ternary.EQUAL -> updatedInfo.copy(
                                        lastSuccessfulSession = currentSession,
                                        successfulSessionCounter = 0u,
                                        sessionFailedCounter = 0u
                                    )
                                    Ternary.BELOW, Ternary.MIXED -> updatedInfo.copy(
                                        successfulSessionCounter = 0u,
                                        sessionFailedCounter = updatedInfo.sessionFailedCounter.inc()
                                    )
                                }
                            }
                        }
                    }

                    updatedInfo = updatedInfo.copy(
                        timesCompletedInAWeek = weeklyCount,
                        weeklyCompletionUpdateDate = today
                    )
                    exerciseInfoDaoRef.insert(updatedInfo)
                }

                if (progressionData != null && progressionState != null) {
                    val progressionEntry = ExerciseSessionProgression(
                        id = UUID.randomUUID(),
                        workoutHistoryId = workoutHistoryForThisPush.id,
                        exerciseId = exerciseId,
                        expectedSets = expectedSets,
                        progressionState = progressionState,
                        vsExpected = vsExpected,
                        vsPrevious = vsPrevious,
                        previousSessionVolume = previousSessionVolume,
                        expectedVolume = expectedVolume,
                        executedVolume = executedVolume
                    )
                    exerciseSessionProgressionDaoRef.insert(progressionEntry)
                }
            }

            val setHistoriesByExerciseId = newExecutedSetsHistory
                .filter { it.exerciseId != null }
                .groupBy { it.exerciseId }

            var workoutComponents = selectedWorkoutSnapshot.workoutComponents
            for (exercise in exercises) {
                if (exercise.doNotStoreHistory) continue
                val setHistories = setHistoriesByExerciseId[exercise.id]?.sortedBy { it.order } ?: continue

                workoutComponents = removeSetsFromExerciseRecursively(workoutComponents, exercise)
                val validSetHistories = sanitizeRestPlacementInSetHistories(setHistories)
                    .filter {
                        when (val setData = it.setData) {
                            is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                            is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                            is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet && setData.subCategory != SetSubCategory.CalibrationSet
                            else -> true
                        }
                    }

                for (setHistory in validSetHistories) {
                    val newSet = getNewSetFromSetHistory(setHistory)
                    workoutComponents = addSetToExerciseRecursively(workoutComponents, exercise, newSet, setHistory.order)
                }
            }

            val currentWorkoutStore = workoutStoreRepositoryRef.getWorkoutStore()
            val newWorkoutStore = currentWorkoutStore.copy(workouts = currentWorkoutStore.workouts.map {
                if (it.id == selectedWorkoutSnapshot.id) it.copy(workoutComponents = workoutComponents) else it
            })
            updateWorkoutStore(newWorkoutStore)
            workoutStoreRepositoryRef.saveWorkoutStore(newWorkoutStore)

            var updatedWorkoutComponents = workoutComponents
            for (exercise in exercises) {
                if (!exercise.requiresLoadCalibration) continue
                val updatedExercise = exercise.copy(requiresLoadCalibration = false)
                updatedWorkoutComponents = updateWorkoutComponentsRecursively(
                    updatedWorkoutComponents,
                    exercise,
                    updatedExercise
                )
                Log.d(tag, "Disabled calibration requirement for exercise: ${exercise.name}")
            }

            if (updatedWorkoutComponents != workoutComponents) {
                val finalWorkoutStore = newWorkoutStore.copy(workouts = newWorkoutStore.workouts.map {
                    if (it.id == selectedWorkoutSnapshot.id) it.copy(workoutComponents = updatedWorkoutComponents) else it
                })
                updateWorkoutStore(finalWorkoutStore)
                workoutStoreRepositoryRef.saveWorkoutStore(finalWorkoutStore)
            }
        }

        return workoutHistoryForThisPush
    }

    suspend fun getLastSessionFromHistory(
        exerciseId: UUID,
        workoutGlobalId: UUID,
        excludeWorkoutHistoryId: UUID?
    ): List<SetHistory> {
        val workoutHistories = workoutHistoryDao().getAllWorkoutHistories()
            .filter {
                it.globalId == workoutGlobalId &&
                    it.isDone &&
                    it.id != excludeWorkoutHistoryId
            }
            .sortedWith(Comparator { a, b ->
                val dateCompare = b.date.compareTo(a.date)
                if (dateCompare != 0) dateCompare else b.time.compareTo(a.time)
            })

        for (workoutHistory in workoutHistories) {
            val setHistories = setHistoryDao().getSetHistoriesByWorkoutHistoryIdAndExerciseId(
                workoutHistory.id,
                exerciseId
            )

            if (setHistories.isNotEmpty()) {
                val processedSession = sanitizeRestPlacementInSetHistories(setHistories)
                    .filter {
                        when (val sd = it.setData) {
                            is BodyWeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                            is WeightSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                            is RestSetData -> sd.subCategory != SetSubCategory.RestPauseSet && sd.subCategory != SetSubCategory.CalibrationSet
                            else -> true
                        }
                    }

                if (processedSession.isNotEmpty()) {
                    return processedSession
                }
            }
        }

        return emptyList()
    }

    private fun cloneSetHistories(setHistories: List<SetHistory>): List<SetHistory> {
        return setHistories.map { history -> history.copy(setData = copySetData(history.setData)) }
    }

    private fun flattenExercises(workout: Workout): List<Exercise> {
        return workout.workoutComponents.filterIsInstance<Exercise>() +
            workout.workoutComponents.filterIsInstance<Superset>().flatMap { it.exercises }
    }

    private data class SupersetMetadata(
        val supersetId: UUID,
        val supersetRound: UInt,
        val supersetExerciseIndex: UInt
    )

    private fun resolveSupersetMetadata(
        exerciseId: UUID?,
        order: UInt,
        supersetIdByExerciseId: Map<UUID, UUID>,
        exercisesBySupersetId: Map<UUID, List<Exercise>>
    ): SupersetMetadata? {
        val resolvedExerciseId = exerciseId ?: return null
        val resolvedSupersetId = supersetIdByExerciseId[resolvedExerciseId] ?: return null
        val exerciseIndex = exercisesBySupersetId[resolvedSupersetId]
            ?.indexOfFirst { it.id == resolvedExerciseId }
            ?.takeIf { it >= 0 }
            ?: return null

        return SupersetMetadata(
            supersetId = resolvedSupersetId,
            supersetRound = order,
            supersetExerciseIndex = exerciseIndex.toUInt()
        )
    }
}


