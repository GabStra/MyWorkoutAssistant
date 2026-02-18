package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import android.widget.Toast
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Energy
import com.gabstra.myworkoutassistant.composables.FilterRange
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.export.equipmentToJSON
import com.gabstra.myworkoutassistant.shared.export.extractEquipmentFromWorkoutPlan
import com.gabstra.myworkoutassistant.shared.export.ExerciseHistoryMarkdownResult
import com.gabstra.myworkoutassistant.shared.export.buildExerciseHistoryMarkdown
import com.gabstra.myworkoutassistant.shared.export.buildWorkoutPlanMarkdown
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.sanitizeRestPlacementInSetHistories
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.compareSetListsUnordered
import com.gabstra.myworkoutassistant.shared.viewmodels.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.CancellationException
import java.text.SimpleDateFormat
import java.time.DayOfWeek
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.temporal.TemporalAdjusters
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.pow
import kotlin.math.roundToInt
import java.security.MessageDigest

suspend fun backfillExerciseSessionProgressions(
    workoutStore: WorkoutStore,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exerciseInfoDao: ExerciseInfoDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    db: AppDatabase
) {
    try {
        Log.d("BackfillProgression", "Starting backfill of ExerciseSessionProgressions")
        
        // Get all completed workouts chronologically
        val allWorkouts = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(isDone = true)
            ?: emptyList()
        
        if (allWorkouts.isEmpty()) {
            Log.d("BackfillProgression", "No completed workouts found, skipping backfill")
            return
        }
        
        val sortedWorkouts = allWorkouts.sortedWith(compareBy<WorkoutHistory> { it.date }.thenBy { it.time })
        Log.d("BackfillProgression", "Processing ${sortedWorkouts.size} completed workouts")

        // Build a map of workout ID to Workout for quick lookup
        val workouts = workoutStore.workouts ?: emptyList()
        val workoutMap = workouts.associateBy { it.id }
        
        // Build a map of exercise ID to Exercise for quick lookup
        val exerciseMap = mutableMapOf<UUID, Exercise>()
        workouts.forEach { workout ->
            workout.workoutComponents?.forEach { component ->
                when (component) {
                    is Exercise -> exerciseMap[component.id] = component
                    is Superset -> component.exercises?.forEach { exercise ->
                        exerciseMap[exercise.id] = exercise
                    }
                    is Rest -> Unit
                }
            }
        }

        // Build equipment map
        val equipments = workoutStore.equipments ?: emptyList()
        val equipmentMap = equipments.associateBy { it.id }
        
        // Track ExerciseInfo state as we process workouts chronologically
        // We start with empty state and build it up chronologically to ensure correctness
        val exerciseInfoStateMap = mutableMapOf<UUID, ExerciseInfo>()

        // Process each workout chronologically
        for (workoutHistory in sortedWorkouts) {
            val workout = workoutMap[workoutHistory.workoutId] ?: run {
                Log.d("BackfillProgression", "Workout ${workoutHistory.workoutId} not found in workout store, skipping")
                continue
            }
            
            // Get all exercises from this workout that have enableProgression
            val exercises = mutableListOf<Exercise>()
            workout.workoutComponents?.forEach { component ->
                when (component) {
                    is Exercise -> {
                        if (component.enableProgression &&
                            !component.requiresLoadCalibration &&
                            (component.exerciseType == ExerciseType.WEIGHT || 
                             component.exerciseType == ExerciseType.BODY_WEIGHT)) {
                            exercises.add(component)
                        }
                    }
                    is Superset -> {
                        component.exercises?.forEach { exercise ->
                            if (exercise.enableProgression &&
                                !exercise.requiresLoadCalibration &&
                                (exercise.exerciseType == ExerciseType.WEIGHT || 
                                 exercise.exerciseType == ExerciseType.BODY_WEIGHT)) {
                                exercises.add(exercise)
                            }
                        }
                    }
                    is Rest -> Unit
                }
            }

            // Get SetHistory entries for this workout
            val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                ?.filter { it.exerciseId != null } ?: emptyList()

            // Process each exercise
            for (exercise in exercises) {
                // Check if progression entry already exists
                val existingProgression = exerciseSessionProgressionDao
                    .getByWorkoutHistoryIdAndExerciseId(workoutHistory.id, exercise.id)
                
                if (existingProgression != null) {
                    // Entry already exists, skip
                    Log.d("BackfillProgression", "Progression entry already exists for exercise ${exercise.id} in workout ${workoutHistory.id}, skipping")
                    continue
                }

                // Get SetHistory entries for this exercise in this workout
                val exerciseSetHistories = setHistories
                    .filter { it.exerciseId == exercise.id }
                    .sortedBy { it.order }

                if (exerciseSetHistories.isEmpty()) {
                    // No sets for this exercise in this workout, skip
                    continue
                }

                // Filter out rest sets and rest pause sets
                val currentSession = sanitizeRestPlacementInSetHistories(exerciseSetHistories)
                    .filter {
                        when (val setData = it.setData) {
                            is BodyWeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            is WeightSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            is RestSetData -> setData.subCategory != SetSubCategory.RestPauseSet
                            else -> true
                        }
                    }

                if (currentSession.isEmpty()) {
                    continue
                }

                // Convert executed sets to SimpleSet
                val executedSets = currentSession.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }

                if (executedSets.isEmpty()) {
                    continue
                }

                // Get or reconstruct ExerciseInfo state as it would have been BEFORE this workout
                val exerciseInfoBefore = exerciseInfoStateMap[exercise.id]

                // Calculate expected sets and progression state
                val (expectedSets, progressionState) = calculateExpectedSetsAndProgressionState(
                    exercise = exercise,
                    exerciseInfoBefore = exerciseInfoBefore,
                    workoutStore = workoutStore,
                    equipmentMap = equipmentMap,
                    workoutHistoryDate = workoutHistory.date
                )

                // Handle first sessions (when expectedSets is null because there's no previous session)
                val finalExpectedSets = expectedSets ?: executedSets
                val finalProgressionState = progressionState ?: ProgressionState.PROGRESS
                
                if (finalExpectedSets.isEmpty()) {
                    // No expected sets and no executed sets, skip
                    Log.d("BackfillProgression", "Skipping exercise ${exercise.id} - no sets available")
                    continue
                }

                // Calculate comparisons
                val vsExpected = compareSetListsUnordered(executedSets, finalExpectedSets)
                
                val previousSessionSets = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                } ?: emptyList()

                val vsPrevious = if (previousSessionSets.isNotEmpty()) {
                    compareSetListsUnordered(executedSets, previousSessionSets)
                } else {
                    Ternary.EQUAL
                }

                // Calculate volumes
                val previousSessionVolume = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
                    when (val setData = setHistory.setData) {
                        is WeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        is BodyWeightSetData -> {
                            if (setData.subCategory == SetSubCategory.RestPauseSet) null
                            else SimpleSet(setData.getWeight(), setData.actualReps)
                        }
                        else -> null
                    }
                }?.sumOf { it.weight * it.reps } ?: 0.0

                val expectedVolume = finalExpectedSets.sumOf { it.weight * it.reps }
                val executedVolume = executedSets.sumOf { it.weight * it.reps }

                // Create and insert ExerciseSessionProgression entry
                val progressionEntry = ExerciseSessionProgression(
                    id = UUID.randomUUID(),
                    workoutHistoryId = workoutHistory.id,
                    exerciseId = exercise.id,
                    expectedSets = finalExpectedSets,
                    progressionState = finalProgressionState,
                    vsExpected = vsExpected,
                    vsPrevious = vsPrevious,
                    previousSessionVolume = previousSessionVolume,
                    expectedVolume = expectedVolume,
                    executedVolume = executedVolume
                )

                exerciseSessionProgressionDao.insert(progressionEntry)
                Log.d("BackfillProgression", "Created progression entry for exercise ${exercise.id} in workout ${workoutHistory.id}")

                // Update ExerciseInfo state for next iteration
                updateExerciseInfoState(
                    exerciseId = exercise.id,
                    currentSession = currentSession,
                    executedSets = executedSets,
                    progressionState = progressionState,
                    vsExpected = vsExpected,
                    exerciseInfoBefore = exerciseInfoBefore,
                    exerciseInfoStateMap = exerciseInfoStateMap,
                    workoutHistoryDate = workoutHistory.date
                )
            }
        }
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error backfilling ExerciseSessionProgressions", e)
    }
}

private suspend fun calculateExpectedSetsAndProgressionState(
    exercise: Exercise,
    exerciseInfoBefore: ExerciseInfo?,
    workoutStore: WorkoutStore,
    equipmentMap: Map<UUID, WeightLoadedEquipment>,
    workoutHistoryDate: LocalDate?
): Pair<List<SimpleSet>?, ProgressionState?> {
    try {
        // Get available weights
        val availableWeights = when (exercise.exerciseType) {
            ExerciseType.WEIGHT -> {
                exercise.equipmentId?.let { equipmentMap[it]?.getWeightsCombinations() } ?: emptySet()
            }
            ExerciseType.BODY_WEIGHT -> {
                val relativeBodyWeight = workoutStore.weightKg * (exercise.bodyWeightPercentage!! / 100)
                (exercise.equipmentId?.let {
                    equipmentMap[it]?.getWeightsCombinations()?.map { value -> relativeBodyWeight + value }!!.toSet()
                } ?: emptySet()) + setOf(relativeBodyWeight)
            }
            else -> return Pair(null, null)
        }

        if (availableWeights.isEmpty()) {
            return Pair(null, null)
        }

        // Get previous session sets
        val previousSessionSets = exerciseInfoBefore?.lastSuccessfulSession?.mapNotNull { setHistory ->
            when (val setData = setHistory.setData) {
                is WeightSetData -> {
                    if (setData.subCategory == SetSubCategory.RestPauseSet) null
                    else SimpleSet(setData.getWeight(), setData.actualReps)
                }
                is BodyWeightSetData -> {
                    if (setData.subCategory == SetSubCategory.RestPauseSet) null
                    else SimpleSet(setData.getWeight(), setData.actualReps)
                }
                else -> null
            }
        } ?: emptyList()

        if (previousSessionSets.isEmpty()) {
            // No previous session, cannot calculate expected sets
            return Pair(null, null)
        }

        // Compute progression state using the workout history date
        val progressionState = computeProgressionState(exerciseInfoBefore, workoutHistoryDate = workoutHistoryDate)

        // Calculate expected sets based on progression state
        val repsRange = IntRange(exercise.minReps, exercise.maxReps)
        val expectedSets = when (progressionState) {
            ProgressionState.DELOAD -> {
                DoubleProgressionHelper.planDeloadSession(
                    previousSets = previousSessionSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange
                ).sets
            }
            ProgressionState.RETRY -> {
                // For retry, expected sets are the same as previous
                previousSessionSets
            }
            ProgressionState.PROGRESS -> {
                val jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(
                    defaultPct = exercise.loadJumpDefaultPct ?: 0.025,
                    maxPct = exercise.loadJumpMaxPct ?: 0.5,
                    overcapUntil = exercise.loadJumpOvercapUntil ?: 2
                )
                DoubleProgressionHelper.planNextSession(
                    previousSets = previousSessionSets,
                    availableWeights = availableWeights,
                    repsRange = repsRange,
                    jumpPolicy = jumpPolicy
                ).sets
            }
            ProgressionState.FAILED -> {
                // Should not happen during backfill, but handle it
                previousSessionSets
            }
        }

        return Pair(expectedSets, progressionState)
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error calculating expected sets", e)
        return Pair(null, null)
    }
}

private fun computeProgressionState(
    exerciseInfo: ExerciseInfo?,
    workoutHistoryDate: LocalDate?
): ProgressionState {
    val fails = exerciseInfo?.sessionFailedCounter?.toInt() ?: 0
    val lastWasDeload = exerciseInfo?.lastSessionWasDeload ?: false

    // For backfill, we use the date from the workout history if available
    val today = workoutHistoryDate ?: LocalDate.now()

    var weeklyCount = 0
    exerciseInfo?.weeklyCompletionUpdateDate?.let { lastUpdate ->
        val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
            weeklyCount = exerciseInfo.timesCompletedInAWeek
        }
    }

    val shouldDeload = false // temporarily disable deload: (fails >= 2) && !lastWasDeload
    val shouldRetry = !lastWasDeload && (fails >= 1 || weeklyCount > 1)

    return when {
        shouldDeload -> ProgressionState.DELOAD
        shouldRetry -> ProgressionState.RETRY
        else -> ProgressionState.PROGRESS
    }
}

private suspend fun updateExerciseInfoState(
    exerciseId: UUID,
    currentSession: List<SetHistory>,
    executedSets: List<SimpleSet>,
    progressionState: ProgressionState?,
    vsExpected: Ternary,
    exerciseInfoBefore: ExerciseInfo?,
    exerciseInfoStateMap: MutableMap<UUID, ExerciseInfo>,
    workoutHistoryDate: LocalDate
) {
    try {
        val today = workoutHistoryDate

        // Calculate weekly count
        var weeklyCount = 0
        if (exerciseInfoBefore != null) {
            val lastUpdate = exerciseInfoBefore.weeklyCompletionUpdateDate
            if (lastUpdate != null) {
                val startOfThisWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                val startOfLastUpdateWeek = lastUpdate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
                if (startOfThisWeek.isEqual(startOfLastUpdateWeek)) {
                    weeklyCount = exerciseInfoBefore.timesCompletedInAWeek
                }
            }
        }
        weeklyCount++

        val isDeloadSession = progressionState == ProgressionState.DELOAD

        val updatedInfo = if (exerciseInfoBefore == null) {
            // First session for this exercise
            ExerciseInfo(
                id = exerciseId,
                bestSession = currentSession,
                lastSuccessfulSession = currentSession,
                successfulSessionCounter = 1u,
                sessionFailedCounter = 0u,
                timesCompletedInAWeek = weeklyCount,
                weeklyCompletionUpdateDate = today,
                lastSessionWasDeload = false
            )
        } else {
            var info = exerciseInfoBefore.copy(version = exerciseInfoBefore.version + 1u)

            if (isDeloadSession) {
                info = info.copy(
                    sessionFailedCounter = 0u,
                    successfulSessionCounter = 0u,
                    lastSessionWasDeload = true
                )
            } else {
                info = info.copy(lastSessionWasDeload = false)

                // Convert best session to SimpleSet list for comparison
                val bestSessionSets = info.bestSession.mapNotNull { setHistory ->
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

                // Check if current session is better than best session
                val vsBest = compareSetListsUnordered(executedSets, bestSessionSets)
                if (vsBest == Ternary.ABOVE) {
                    info = info.copy(bestSession = currentSession)
                }

                if (progressionState != null) {
                    if (progressionState == ProgressionState.PROGRESS) {
                        // Success if executed sets are ABOVE or EQUAL to expected sets
                        val isSuccess = vsExpected == Ternary.ABOVE || vsExpected == Ternary.EQUAL

                        info = if (isSuccess) {
                            info.copy(
                                lastSuccessfulSession = currentSession,
                                successfulSessionCounter = info.successfulSessionCounter.inc(),
                                sessionFailedCounter = 0u
                            )
                        } else {
                            info.copy(
                                successfulSessionCounter = 0u,
                                sessionFailedCounter = info.sessionFailedCounter.inc()
                            )
                        }
                    } else {
                        // ProgressionState.RETRY as DELOAD was already handled
                        when (vsExpected) {
                            Ternary.ABOVE -> {
                                // Exceeded retry target - success
                                info = info.copy(
                                    lastSuccessfulSession = currentSession,
                                    successfulSessionCounter = info.successfulSessionCounter.inc(),
                                    sessionFailedCounter = 0u
                                )
                            }
                            Ternary.EQUAL -> {
                                // Met retry target exactly - complete retry, reset counters
                                info = info.copy(
                                    lastSuccessfulSession = currentSession,
                                    successfulSessionCounter = 0u,
                                    sessionFailedCounter = 0u
                                )
                            }
                            Ternary.BELOW, Ternary.MIXED -> {
                                // Below retry target - session failed, don't update counters
                                // Counters remain unchanged (will be incremented elsewhere if needed)
                            }
                        }
                    }
                } else {
                    // No progression state - compare against last successful session
                    val lastSessionSets = info.lastSuccessfulSession.mapNotNull { setHistory ->
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

                    val vsLast = compareSetListsUnordered(executedSets, lastSessionSets)
                    val isSuccess = vsLast == Ternary.ABOVE || vsLast == Ternary.EQUAL

                    info = if (isSuccess) {
                        info.copy(
                            lastSuccessfulSession = currentSession,
                            successfulSessionCounter = info.successfulSessionCounter.inc(),
                            sessionFailedCounter = 0u
                        )
                    } else {
                        info.copy(
                            successfulSessionCounter = 0u,
                            sessionFailedCounter = info.sessionFailedCounter.inc()
                        )
                    }
                }
            }

            info.copy(
                timesCompletedInAWeek = weeklyCount,
                weeklyCompletionUpdateDate = today
            )
        }

        exerciseInfoStateMap[exerciseId] = updatedInfo
    } catch (e: Exception) {
        Log.e("BackfillProgression", "Error updating ExerciseInfo state", e)
    }
}

object Spacing {
    val xs = 6.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
}

/**
 * Conflict resolution strategy for merging WorkoutStore data.
 */
enum class ConflictResolution {
    SKIP_DUPLICATES,      // Skip items with duplicate IDs
    GENERATE_NEW_IDS,     // Generate new UUIDs for conflicts
    REPLACE_EXISTING      // Replace existing items with same ID
}

/**
 * Merges an imported WorkoutStore with an existing WorkoutStore.
 * 
 * @param existing The current WorkoutStore in the app
 * @param imported The WorkoutStore to import/merge
 * @param conflictResolution How to handle ID conflicts (default: GENERATE_NEW_IDS)
 * @return Merged WorkoutStore
 */
fun mergeWorkoutStore(
    existing: WorkoutStore,
    imported: WorkoutStore,
    conflictResolution: ConflictResolution = ConflictResolution.SKIP_DUPLICATES
): WorkoutStore {
    // Merge workouts
    val existingWorkoutIds = existing.workouts.map { it.id }.toSet()
    val mergedWorkouts = mutableListOf<Workout>()
    mergedWorkouts.addAll(existing.workouts)
    
    imported.workouts.forEach { importedWorkout ->
        when {
            !existingWorkoutIds.contains(importedWorkout.id) -> {
                // New workout, add it
                mergedWorkouts.add(importedWorkout)
            }
            conflictResolution == ConflictResolution.REPLACE_EXISTING -> {
                // Replace existing workout
                val index = mergedWorkouts.indexOfFirst { it.id == importedWorkout.id }
                if (index >= 0) {
                    mergedWorkouts[index] = importedWorkout
                }
            }
            conflictResolution == ConflictResolution.GENERATE_NEW_IDS -> {
                // Generate new ID for imported workout
                val newId = UUID.randomUUID()
                val newGlobalId = UUID.randomUUID()
                mergedWorkouts.add(
                    importedWorkout.copy(
                        id = newId,
                        globalId = newGlobalId,
                        previousVersionId = null,
                        nextVersionId = null
                    )
                )
            }
            // SKIP_DUPLICATES: do nothing, skip this workout
        }
    }
    
    // Merge equipment
    val existingEquipmentIds = existing.equipments.map { it.id }.toSet()
    val mergedEquipment = mutableListOf<WeightLoadedEquipment>()
    mergedEquipment.addAll(existing.equipments)
    
    imported.equipments.forEach { importedEquipment ->
        when {
            !existingEquipmentIds.contains(importedEquipment.id) -> {
                // New equipment, add it
                mergedEquipment.add(importedEquipment)
            }
            conflictResolution == ConflictResolution.REPLACE_EXISTING -> {
                // Replace existing equipment
                val index = mergedEquipment.indexOfFirst { it.id == importedEquipment.id }
                if (index >= 0) {
                    mergedEquipment[index] = importedEquipment
                }
            }
            conflictResolution == ConflictResolution.GENERATE_NEW_IDS -> {
                // For equipment, skip duplicates when generating new IDs
                // Updating all equipment references in workouts would be complex
                // User can manually add equipment if needed
                // SKIP_DUPLICATES: do nothing, skip this equipment
            }
            // SKIP_DUPLICATES: do nothing, skip this equipment
        }
    }
    
    // Merge accessory equipment
    val existingAccessoryIds = existing.accessoryEquipments.map { it.id }.toSet()
    val mergedAccessories = mutableListOf<AccessoryEquipment>()
    mergedAccessories.addAll(existing.accessoryEquipments)
    
    imported.accessoryEquipments.forEach { importedAccessory ->
        when {
            !existingAccessoryIds.contains(importedAccessory.id) -> {
                // New accessory, add it
                mergedAccessories.add(importedAccessory)
            }
            conflictResolution == ConflictResolution.REPLACE_EXISTING -> {
                // Replace existing accessory
                val index = mergedAccessories.indexOfFirst { it.id == importedAccessory.id }
                if (index >= 0) {
                    mergedAccessories[index] = importedAccessory
                }
            }
            conflictResolution == ConflictResolution.GENERATE_NEW_IDS -> {
                // For accessories, skip duplicates when generating new IDs
                // Updating all accessory references in exercises would be complex
                // User can manually add accessories if needed
                // SKIP_DUPLICATES: do nothing, skip this accessory
            }
            // SKIP_DUPLICATES: do nothing, skip this accessory
        }
    }
    
    // User profile data: always keep local values, ignore imported
    val mergedBirthDateYear = existing.birthDateYear
    val mergedWeightKg = existing.weightKg
    val mergedProgressionPercentageAmount = existing.progressionPercentageAmount
    val mergedPolarDeviceId = existing.polarDeviceId
    val mergedMeasuredMaxHeartRate = existing.measuredMaxHeartRate
    val mergedRestingHeartRate = existing.restingHeartRate
    
    // Merge workout plans
    val existingPlanIds = existing.workoutPlans.map { it.id }.toSet()
    val mergedPlans = mutableListOf<WorkoutPlan>()
    mergedPlans.addAll(existing.workoutPlans)
    
    imported.workoutPlans.forEach { importedPlan ->
        when {
            !existingPlanIds.contains(importedPlan.id) -> {
                // New plan, add it
                mergedPlans.add(importedPlan)
            }
            conflictResolution == ConflictResolution.REPLACE_EXISTING -> {
                // Replace existing plan
                val index = mergedPlans.indexOfFirst { it.id == importedPlan.id }
                if (index >= 0) {
                    mergedPlans[index] = importedPlan
                }
            }
            conflictResolution == ConflictResolution.GENERATE_NEW_IDS -> {
                // Generate new ID for imported plan
                val newId = UUID.randomUUID()
                mergedPlans.add(
                    importedPlan.copy(
                        id = newId,
                        workoutIds = importedPlan.workoutIds.map { UUID.randomUUID() } // Also generate new IDs for workouts in plan
                    )
                )
            }
            // SKIP_DUPLICATES: do nothing, skip this plan
        }
    }
    
    return WorkoutStore(
        workouts = mergedWorkouts,
        equipments = mergedEquipment,
        accessoryEquipments = mergedAccessories,
        workoutPlans = mergedPlans,
        birthDateYear = mergedBirthDateYear,
        weightKg = mergedWeightKg,
        progressionPercentageAmount = mergedProgressionPercentageAmount,
        polarDeviceId = mergedPolarDeviceId,
        measuredMaxHeartRate = mergedMeasuredMaxHeartRate,
        restingHeartRate = mergedRestingHeartRate
    )
}
