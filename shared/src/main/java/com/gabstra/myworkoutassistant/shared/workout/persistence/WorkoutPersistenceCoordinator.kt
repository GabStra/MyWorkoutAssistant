package com.gabstra.myworkoutassistant.shared.workout.persistence

import android.util.Log
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.replaceSetsInExerciseRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutManager.Companion.updateWorkoutComponentsRecursively
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.copySetData
import com.gabstra.myworkoutassistant.shared.workout.history.ExerciseSessionReconstruction
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.stores.ExecutedRestStore
import com.gabstra.myworkoutassistant.shared.stores.ExecutedSetStore
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.persistence.WorkoutRestHistoryOps
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
    private val executedRestStore: ExecutedRestStore,
    private val workoutHistoryDao: () -> WorkoutHistoryDao,
    private val setHistoryDao: () -> SetHistoryDao,
    private val restHistoryDao: () -> RestHistoryDao,
    private val exerciseInfoDao: () -> ExerciseInfoDao,
    private val exerciseSessionProgressionDao: () -> ExerciseSessionProgressionDao,
    private val workoutStoreRepository: () -> WorkoutStoreRepository,
    private val workoutRecordDao: () -> WorkoutRecordDao,
    private val tag: String = "WorkoutViewModel"
) {
    data class SetHistorySnapshot(
        val setHistory: SetHistory,
        val setId: UUID,
        val order: UInt,
        val exerciseId: UUID?
    )

    data class RestHistorySnapshot(
        val restHistory: RestHistory,
        val restSetId: UUID,
        val order: UInt,
        val exerciseId: UUID?
    )

    data class PushWorkoutDataSnapshot(
        val startWorkoutTime: LocalDateTime,
        val selectedWorkout: Workout,
        val currentWorkoutHistory: WorkoutHistory?,
        val heartBeatRecords: List<Int>,
        val executedSetsHistory: List<SetHistory>,
        val executedRestHistories: List<RestHistory>,
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
            else -> return null
        }
        val setDataSnapshot = copySetData(setData)
        val startTime = when (currentState) {
            is WorkoutState.Set -> currentState.startTime ?: LocalDateTime.now()
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
        val nextExecutionSequence = nextExecutionSequenceValue()

        // Resolve equipment snapshot at record time so later equipment edits do not
        // change how this historical set is labeled or interpreted.
        val exercise = historyIdentity.exerciseId?.let { exercisesById[it] }
        val equipmentIdFromState = (currentState as? WorkoutState.Set)?.equipmentId ?: exercise?.equipmentId
        val workoutStore = workoutStoreRepository().getWorkoutStore()
        val equipmentSnapshot = equipmentIdFromState?.let { equipmentId ->
            workoutStore.equipments.find { it.id == equipmentId }
        }

        val newSetHistory = SetHistory(
            id = UUID.randomUUID(),
            equipmentIdSnapshot = equipmentIdFromState,
            equipmentNameSnapshot = equipmentSnapshot?.name,
            equipmentTypeSnapshot = equipmentSnapshot?.type?.name,
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

    fun captureRestHistorySnapshot(
        currentState: WorkoutState,
        exercisesById: Map<UUID, Exercise>
    ): RestHistorySnapshot? {
        if (currentState !is WorkoutState.Rest) return null
        if (WorkoutRestHistoryOps.shouldSkipPersistingRest(currentState, exercisesById)) return null
        val historyIdentity = WorkoutStateQueries.stateHistoryIdentity(currentState) ?: return null
        val setDataSnapshot = copySetData(currentState.currentSetData)
        val startTime = currentState.startTime ?: LocalDateTime.now()
        val scope = if (currentState.isIntraSetRest) {
            RestHistoryScope.INTRA_EXERCISE
        } else {
            RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS
        }
        val workoutComponentId =
            if (scope == RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS) currentState.set.id else null
        val nextExecutionSequence = nextExecutionSequenceValue()
        val newRestHistory = RestHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = null,
            scope = scope,
            executionSequence = nextExecutionSequence.toUInt(),
            setData = setDataSnapshot,
            startTime = startTime,
            endTime = LocalDateTime.now(),
            workoutComponentId = workoutComponentId,
            exerciseId = historyIdentity.exerciseId,
            restSetId = historyIdentity.setId,
            order = historyIdentity.order
        )
        return RestHistorySnapshot(
            restHistory = newRestHistory,
            restSetId = historyIdentity.setId,
            order = historyIdentity.order,
            exerciseId = historyIdentity.exerciseId
        )
    }

    private fun nextExecutionSequenceValue(): Long {
        val setMax = executedSetStore.executedSets.value.maxOfOrNull { it.executionSequence?.toLong() ?: 0L } ?: 0L
        val restMax = executedRestStore.executedRests.value.maxOfOrNull { it.executionSequence?.toLong() ?: 0L } ?: 0L
        return maxOf(setMax, restMax) + 1L
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

    suspend fun upsertRestHistorySnapshot(snapshot: RestHistorySnapshot) {
        val key: (RestHistory) -> Boolean = { history ->
            WorkoutStateQueries.matchesRestHistory(
                history,
                snapshot.restSetId,
                snapshot.order,
                snapshot.exerciseId
            )
        }
        val existing = executedRestStore.executedRests.value.firstOrNull(key)
        val normalizedSnapshot = if (existing?.executionSequence != null) {
            snapshot.restHistory.copy(executionSequence = existing.executionSequence)
        } else {
            snapshot.restHistory
        }
        executedRestStore.upsert(normalizedSnapshot, key)
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
        val executedRestSnapshot = cloneRestHistories(executedRestStore.executedRests.value)
        return PushWorkoutDataSnapshot(
            startWorkoutTime = startTime,
            selectedWorkout = selectedWorkout,
            currentWorkoutHistory = currentWorkoutHistory,
            heartBeatRecords = heartBeatRecords,
            executedSetsHistory = executedSetsSnapshot,
            executedRestHistories = executedRestSnapshot,
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
        val restHistoryDaoRef = restHistoryDao()
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

        val newExecutedSetsHistory = snapshot.executedSetsHistory
            .asSequence()
            .filterNot { history ->
                isDone && isWarmupSetData(history.setData)
            }
            .map {
                it.copy(
                    workoutHistoryId = workoutHistoryForThisPush.id,
                    setData = copySetData(it.setData)
                )
            }
            .toList()

        val newExecutedRestHistories = snapshot.executedRestHistories.map {
            it.copy(
                workoutHistoryId = workoutHistoryForThisPush.id,
                setData = copySetData(it.setData)
            )
        }

        executedSetStore.replaceAll(newExecutedSetsHistory)
        executedRestStore.replaceAll(newExecutedRestHistories)
        workoutHistoryDaoRef.insertWithVersionCheck(workoutHistoryForThisPush)
        setHistoryDaoRef.deleteByWorkoutHistoryId(workoutHistoryForThisPush.id)
        setHistoryDaoRef.insertAllWithVersionCheck(*newExecutedSetsHistory.toTypedArray())
        restHistoryDaoRef.deleteByWorkoutHistoryId(workoutHistoryForThisPush.id)
        restHistoryDaoRef.insertAllWithVersionCheck(*newExecutedRestHistories.toTypedArray())

        if (isDone) {
            workoutRecordDao().deleteByWorkoutId(selectedWorkoutSnapshot.id)
            val setHistoriesByExerciseId = newExecutedSetsHistory
                .filter { it.exerciseId != null }
                .groupBy { it.exerciseId!! }

            val exercises = flattenExercises(selectedWorkoutSnapshot)

            val mergeByExerciseId = exercises
                .associate { exercise ->
                    exercise.id to ExerciseSessionReconstruction.mergeCompletedSession(
                        templateSets = exercise.sets,
                        rawSetHistoriesForExercise = setHistoriesByExerciseId[exercise.id].orEmpty(),
                        allRestHistories = newExecutedRestHistories,
                        exerciseId = exercise.id,
                    )
                }

            setHistoriesByExerciseId.forEach { entry ->
                val exercise = exercises.firstOrNull { item -> item.id == entry.key }
                if (exercise == null) {
                    Log.e(tag, "Exercise with id ${entry.key} not found")
                    return@forEach
                }

                val isTrackableExercise =
                    exercise.exerciseType == ExerciseType.WEIGHT || exercise.exerciseType == ExerciseType.BODY_WEIGHT
                if (!isTrackableExercise) return@forEach

                val progressionData = progressionByExerciseIdSnapshot[entry.key]
                val exerciseProgression = progressionData?.first
                val progressionState = progressionData?.second
                val isDeloadSession = progressionState == ProgressionState.DELOAD
                val sessionMerge = mergeByExerciseId.getValue(exercise.id)
                val currentSessionSnapshot = sessionMerge.snapshot
                val preparedSetHistories = sessionMerge.preparedSetHistories

                val exerciseId = entry.key
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

                val executedSets = preparedSetHistories.mapNotNull { setHistory ->
                    if (isWarmupSetData(setHistory.setData)) return@mapNotNull null
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                        is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
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
                                if (isNonWorkSetData(setData)) return@mapNotNull null
                                SimpleSet(setData.getWeight(), setData.actualReps)
                            }
                            is BodyWeightSetData -> {
                                if (isNonWorkSetData(setData)) return@mapNotNull null
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
                        bestSession = currentSessionSnapshot,
                        lastSuccessfulSession = currentSessionSnapshot,
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

                        val bestSessionSets = toExecutedWorkSets(updatedInfo.bestSession)

                        if (compareSetListsUnordered(executedSets, bestSessionSets) == Ternary.ABOVE) {
                            updatedInfo = updatedInfo.copy(bestSession = currentSessionSnapshot)
                        }

                        if (progressionState != null) {
                            when (progressionState) {
                                ProgressionState.PROGRESS -> {
                                    val isSuccess = exerciseProgression != null &&
                                        expectedSets.isNotEmpty() &&
                                        (vsExpected == Ternary.ABOVE || vsExpected == Ternary.EQUAL)
                                    updatedInfo = if (isSuccess) {
                                        updatedInfo.copy(
                                            lastSuccessfulSession = currentSessionSnapshot,
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
                                            lastSuccessfulSession = currentSessionSnapshot,
                                            successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                            sessionFailedCounter = 0u
                                        )
                                        Ternary.EQUAL -> updatedInfo.copy(
                                            lastSuccessfulSession = currentSessionSnapshot,
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
                                            lastSuccessfulSession = currentSessionSnapshot,
                                            successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                            sessionFailedCounter = 0u
                                        )
                                    }
                                    else -> updatedInfo
                                }
                            } else {
                                val lastSessionSets = toExecutedWorkSets(updatedInfo.lastSuccessfulSession)
                                updatedInfo = when (compareSetListsUnordered(executedSets, lastSessionSets)) {
                                    Ternary.ABOVE -> updatedInfo.copy(
                                        lastSuccessfulSession = currentSessionSnapshot,
                                        successfulSessionCounter = updatedInfo.successfulSessionCounter.inc(),
                                        sessionFailedCounter = 0u
                                    )
                                    Ternary.EQUAL -> updatedInfo.copy(
                                        lastSuccessfulSession = currentSessionSnapshot,
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

            var workoutComponents = selectedWorkoutSnapshot.workoutComponents
            for (exercise in exercises) {
                val merge = mergeByExerciseId.getValue(exercise.id)
                workoutComponents = replaceSetsInExerciseRecursively(
                    workoutComponents,
                    exercise,
                    merge.mergedSets(),
                )
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
                val processedSession =
                    ExerciseSessionReconstruction.prepareSetHistoriesForSnapshot(setHistories)
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

    private fun cloneRestHistories(restHistories: List<RestHistory>): List<RestHistory> {
        return restHistories.map { history -> history.copy(setData = copySetData(history.setData)) }
    }

    private fun isWarmupSetData(setData: com.gabstra.myworkoutassistant.shared.setdata.SetData): Boolean = when (setData) {
        is WeightSetData -> setData.subCategory == SetSubCategory.WarmupSet
        is BodyWeightSetData -> setData.subCategory == SetSubCategory.WarmupSet
        else -> false
    }

    private fun isNonWorkSetData(setData: com.gabstra.myworkoutassistant.shared.setdata.SetData): Boolean = when (setData) {
        is WeightSetData -> setData.subCategory == SetSubCategory.RestPauseSet ||
            setData.subCategory == SetSubCategory.CalibrationSet ||
            setData.subCategory == SetSubCategory.WarmupSet
        is BodyWeightSetData -> setData.subCategory == SetSubCategory.RestPauseSet ||
            setData.subCategory == SetSubCategory.CalibrationSet ||
            setData.subCategory == SetSubCategory.WarmupSet
        else -> false
    }

    private fun toExecutedWorkSets(snapshot: ExerciseSessionSnapshot): List<SimpleSet> {
        return snapshot.sets.mapNotNull { setSnapshot ->
            val isNonWorkSet = when (val set = setSnapshot.set) {
                is WeightSet -> {
                    set.subCategory == SetSubCategory.RestPauseSet ||
                        set.subCategory == SetSubCategory.CalibrationSet ||
                        set.subCategory == SetSubCategory.WarmupSet
                }
                is BodyWeightSet -> {
                    set.subCategory == SetSubCategory.RestPauseSet ||
                        set.subCategory == SetSubCategory.CalibrationSet ||
                        set.subCategory == SetSubCategory.WarmupSet
                }
                else -> true
            }
            if (isNonWorkSet || !setSnapshot.wasExecuted || setSnapshot.wasSkipped) {
                return@mapNotNull null
            }
            setSnapshot.simpleSet
        }
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
