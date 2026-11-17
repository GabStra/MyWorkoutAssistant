package com.gabstra.myworkoutassistant.shared.workout.session

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedRestStore
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedSetStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutSessionLifecycleServiceTest {
    private lateinit var context: Context
    private lateinit var database: AppDatabase
    private lateinit var service: WorkoutSessionLifecycleService

    private val workoutId: UUID = UUID.fromString("b9727cc7-5956-4415-ae7e-95bc33ed6f6e")
    private val workoutGlobalId: UUID = UUID.fromString("cb9c1210-fec8-4dbf-9310-8016136be845")
    private val exerciseId: UUID = UUID.fromString("d803ab73-60bf-41ff-8825-a1208b92bc74")
    private val currentSetId: UUID = UUID.fromString("f654a2f0-c5c1-4e89-b839-e4f15a3eb6dc")
    private val olderMatchingSetId: UUID = UUID.fromString("db30f6a6-aafd-4f52-b58e-783e92c5b1d7")
    private val newerChangedSetId: UUID = UUID.fromString("ab0ff4b2-a34b-45b0-96fe-25d9c6a3d8c7")
    private val recurringSessionId = UUID.fromString("e1b47c64-8d21-4483-8a68-0f3e2735a4bf")
    private val recurringExerciseId = UUID.fromString("d561b119-bff0-42ad-a4e4-40e3e519a1dc")
    private val exerciseDefinitionId = UUID.fromString("433cbf63-bb55-4b6a-9938-4a19a9254b78")
    private val recurringEquipmentId = UUID.fromString("56f9d8c1-9fd1-4aa7-87b2-4189a047d78e")

    @Before
    fun setup() {
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        service = WorkoutSessionLifecycleService(
            executedSetStore = DefaultExecutedSetStore(),
            executedRestStore = DefaultExecutedRestStore(),
            setHistoryDao = { database.setHistoryDao() },
            restHistoryDao = { database.restHistoryDao() },
            workoutHistoryDao = { database.workoutHistoryDao() }
        )
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun loadWorkoutHistory_prefersMostRecentComparableSessionOverOlderCoverageMatch() = runBlocking {
        seedHistory(
            historyId = UUID.fromString("45ddb966-b1c3-4d36-b296-64c57f38b37e"),
            date = LocalDate.of(2026, 3, 10),
            time = LocalTime.of(9, 0),
            setId = olderMatchingSetId,
            reps = 10,
            weight = 100.0
        )
        seedHistory(
            historyId = UUID.fromString("f51c97be-acf7-43bb-8f78-37a79f5cd9e8"),
            date = LocalDate.of(2026, 3, 17),
            time = LocalTime.of(9, 0),
            setId = newerChangedSetId,
            reps = 8,
            weight = 105.0
        )

        val loaded = service.loadWorkoutHistory(createWorkout())

        val exerciseHistory = loaded.latestSetHistoriesByExerciseId[exerciseId].orEmpty()
        assertEquals(1, exerciseHistory.size)
        assertEquals(
            "Newest comparable session should drive vs last even if set ids changed.",
            newerChangedSetId,
            exerciseHistory.single().setId
        )
        assertFalse(
            "Per-set lookup should not fabricate a match for the current set id when ids changed.",
            loaded.latestSetHistoryByExerciseAndSetId.containsKey(exerciseId to currentSetId)
        )
    }

    @Test
    fun loadWorkoutHistory_prefersLaterSameDayHistory() = runBlocking {
        val day = LocalDate.of(2026, 3, 17)
        seedHistory(
            historyId = UUID.fromString("a5c15d0c-b0f5-4cf7-85ba-2d845bceab34"),
            date = day,
            time = LocalTime.of(9, 0),
            setId = olderMatchingSetId,
            reps = 10,
            weight = 100.0
        )
        seedHistory(
            historyId = UUID.fromString("8d975412-3057-4fc8-84ae-d0dbdf7dbd07"),
            date = day,
            time = LocalTime.of(18, 0),
            setId = newerChangedSetId,
            reps = 8,
            weight = 105.0
        )

        val loaded = service.loadWorkoutHistory(createWorkout())

        assertEquals(
            newerChangedSetId,
            loaded.latestSetHistoriesByExerciseId[exerciseId].orEmpty().single().setId
        )
    }

    @Test
    fun loadWorkoutHistory_recurringTrackFindsLatestCompletedOccurrenceAndRepeatsLastLoadForAddedSet() = runBlocking {
        seedRecurringHistory(
            historyId = UUID.fromString("6bdd4a65-41c6-4d45-b320-e764b2a51630"),
            time = LocalTime.of(9, 0), trackId = recurringExerciseId, weight = 80.0
        )
        seedRecurringHistory(
            historyId = UUID.fromString("7825d7d3-8f29-4214-9dc0-e31b1996c2c9"),
            time = LocalTime.of(10, 0), trackId = UUID.randomUUID(), weight = 120.0
        )
        seedRecurringHistory(
            historyId = UUID.fromString("21e1506d-7740-41ef-afde-dc7026eaf85b"),
            time = LocalTime.of(11, 0), trackId = recurringExerciseId, weight = 150.0, isDone = false
        )
        val firstSetId = UUID.randomUUID()
        val secondSetId = UUID.randomUUID()
        val exercise = createWorkout().workoutComponents.single() as Exercise
        val current = createWorkout().copy(
            recurringSessionId = recurringSessionId,
            workoutComponents = listOf(exercise.copy(
                exerciseDefinitionId = exerciseDefinitionId,
                equipmentId = recurringEquipmentId,
                recurringExerciseId = recurringExerciseId,
                loadHistoryPolicy = LoadHistoryPolicy.LAST_WORKING_LOAD,
                sets = listOf(WeightSet(firstSetId, 12, 65.0), WeightSet(secondSetId, 10, 70.0))
            ))
        )

        val loaded = service.loadWorkoutHistory(current)
        val firstHistory = loaded.latestSetHistoryByExerciseAndSetId[exerciseId to firstSetId]!!
        val secondHistory = loaded.latestSetHistoryByExerciseAndSetId[exerciseId to secondSetId]!!
        assertEquals(80.0, (firstHistory.setData as WeightSetData).actualWeight, 0.0)
        assertEquals(80.0, (secondHistory.setData as WeightSetData).actualWeight, 0.0)
    }

    @Test
    fun loadWorkoutHistory_recurringTrackCanUseExactMemberLegacyHistoryUntilNewHistoryExists() = runBlocking {
        seedHistory(
            historyId = UUID.fromString("173c0735-24b1-41b6-92eb-b4dcd34e0e80"),
            date = LocalDate.of(2026, 3, 25),
            time = LocalTime.of(9, 0),
            setId = olderMatchingSetId,
            reps = 8,
            weight = 55.0,
        )
        val source = createWorkout().copy(
            recurringSessionId = recurringSessionId,
            prescriptionOrdinal = 1,
            workoutComponents = listOf((createWorkout().workoutComponents.single() as Exercise).copy(
                exerciseDefinitionId = exerciseDefinitionId,
                equipmentId = recurringEquipmentId,
                recurringExerciseId = recurringExerciseId,
            )),
        )
        val currentExerciseId = UUID.randomUUID()
        val currentSet = WeightSet(UUID.randomUUID(), reps = 9, weight = 40.0)
        val current = createWorkout().copy(
            id = UUID.randomUUID(),
            globalId = UUID.randomUUID(),
            recurringSessionId = recurringSessionId,
            prescriptionOrdinal = 2,
            workoutComponents = listOf((createWorkout().workoutComponents.single() as Exercise).copy(
                id = currentExerciseId,
                exerciseDefinitionId = exerciseDefinitionId,
                equipmentId = recurringEquipmentId,
                recurringExerciseId = recurringExerciseId,
                loadHistoryPolicy = LoadHistoryPolicy.LAST_WORKING_LOAD,
                sets = listOf(currentSet),
            )),
        )

        val loaded = service.loadWorkoutHistory(current, listOf(source, current))
        assertEquals(55.0, (loaded.latestSetHistoryByExerciseAndSetId[currentExerciseId to currentSet.id]!!.setData as WeightSetData).actualWeight, 0.0)

        val detachedSourceExcluded = service.loadWorkoutHistory(current, listOf(current))
        assertEquals(emptyMap<Pair<UUID, UUID>, SetHistory>(), detachedSourceExcluded.latestSetHistoryByExerciseAndSetId)

        val changedOriginal = source.copy(workoutComponents = listOf(
            (source.workoutComponents.single() as Exercise).copy(exerciseDefinitionId = UUID.randomUUID()),
        ))
        val changedDefinitionRejected = service.loadWorkoutHistory(
            current,
            familyWorkouts = listOf(changedOriginal, current),
            allWorkoutVersions = listOf(changedOriginal, current),
        )
        assertEquals(emptyMap<Pair<UUID, UUID>, SetHistory>(), changedDefinitionRejected.latestSetHistoryByExerciseAndSetId)
    }

    @Test
    fun loadWorkoutHistory_recurringTrackRejectsChangedDefinitionEquipmentAndSetType() = runBlocking {
        seedRecurringHistory(
            historyId = UUID.fromString("cb183c60-653b-4f2a-89df-4f4cc2c84380"),
            time = LocalTime.of(9, 0), trackId = recurringExerciseId, weight = 80.0
        )
        val original = createWorkout().workoutComponents.single() as Exercise
        val current = createWorkout().copy(
            recurringSessionId = recurringSessionId,
            workoutComponents = listOf(original.copy(
                exerciseDefinitionId = UUID.randomUUID(),
                equipmentId = UUID.randomUUID(),
                recurringExerciseId = recurringExerciseId,
                loadHistoryPolicy = LoadHistoryPolicy.LAST_WORKING_LOAD
            ))
        )

        val loaded = service.loadWorkoutHistory(current)

        assertEquals(emptyMap<Pair<UUID, UUID>, SetHistory>(), loaded.latestSetHistoryByExerciseAndSetId)
    }

    private suspend fun seedRecurringHistory(
        historyId: UUID,
        time: LocalTime,
        trackId: UUID,
        weight: Double,
        isDone: Boolean = true
    ) {
        val date = LocalDate.of(2026, 3, 24)
        database.workoutHistoryDao().insert(WorkoutHistory(
            id = historyId,
            workoutId = UUID.randomUUID(),
            date = date,
            time = time,
            startTime = LocalDateTime.of(date, time),
            duration = 300,
            heartBeatRecords = emptyList(),
            isDone = isDone,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID(),
            recurringSessionId = recurringSessionId
        ))
        database.setHistoryDao().insert(SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = historyId,
            exerciseId = UUID.randomUUID(),
            equipmentIdSnapshot = recurringEquipmentId,
            setId = UUID.randomUUID(),
            order = 0u,
            startTime = LocalDateTime.of(date, time),
            endTime = LocalDateTime.of(date, time).plusMinutes(1),
            setData = WeightSetData(8, weight, 8 * weight),
            skipped = false,
            recurringExerciseId = trackId,
            exerciseDefinitionIdSnapshot = exerciseDefinitionId,
            exerciseTypeSnapshot = ExerciseType.WEIGHT.name
        ))
    }

    private suspend fun seedHistory(
        historyId: UUID,
        date: LocalDate,
        time: LocalTime,
        setId: UUID,
        reps: Int,
        weight: Double
    ) {
        database.workoutHistoryDao().insert(
            WorkoutHistory(
                id = historyId,
                workoutId = workoutId,
                date = date,
                time = time,
                startTime = LocalDateTime.of(date, time),
                duration = 300,
                heartBeatRecords = emptyList(),
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = workoutGlobalId
            )
        )
        database.setHistoryDao().insert(
            SetHistory(
                id = UUID.nameUUIDFromBytes("history-$historyId-$setId".toByteArray()),
                workoutHistoryId = historyId,
                exerciseId = exerciseId,
                setId = setId,
                order = 0u,
                startTime = LocalDateTime.of(date, time),
                endTime = LocalDateTime.of(date, time).plusMinutes(1),
                setData = WeightSetData(
                    actualReps = reps,
                    actualWeight = weight,
                    volume = reps * weight,
                    subCategory = SetSubCategory.WorkSet
                ),
                skipped = false,
                executionSequence = 0u
            )
        )
    }

    private fun createWorkout(): Workout {
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Vs Last Press",
            notes = "",
            sets = listOf(WeightSet(id = currentSetId, reps = 10, weight = 100.0)),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )

        return Workout(
            id = workoutId,
            name = "Completion Vs Last Workout",
            description = "Test workout",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            heartRateSource = com.gabstra.myworkoutassistant.shared.HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.of(2026, 3, 20),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = workoutGlobalId,
            type = 0
        )
    }
}
