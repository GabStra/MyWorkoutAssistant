package com.gabstra.myworkoutassistant.shared.workout.session

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedRestStore
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedSetStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
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
            setId = olderMatchingSetId,
            reps = 10,
            weight = 100.0
        )
        seedHistory(
            historyId = UUID.fromString("f51c97be-acf7-43bb-8f78-37a79f5cd9e8"),
            date = LocalDate.of(2026, 3, 17),
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

    private suspend fun seedHistory(
        historyId: UUID,
        date: LocalDate,
        setId: UUID,
        reps: Int,
        weight: Double
    ) {
        database.workoutHistoryDao().insert(
            WorkoutHistory(
                id = historyId,
                workoutId = workoutId,
                date = date,
                time = LocalTime.of(9, 0),
                startTime = LocalDateTime.of(date, LocalTime.of(8, 55)),
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
                startTime = LocalDateTime.of(date, LocalTime.of(8, 55)),
                endTime = LocalDateTime.of(date, LocalTime.of(8, 56)),
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
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
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
