package com.gabstra.myworkoutassistant.shared.workout.persistence

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedRestStore
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedSetStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.io.File
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutPersistenceCoordinatorTest {

    private lateinit var context: Context
    private lateinit var database: AppDatabase
    private lateinit var filesDir: File
    private lateinit var workoutStoreRepository: WorkoutStoreRepository
    private lateinit var executedSetStore: DefaultExecutedSetStore
    private lateinit var coordinator: WorkoutPersistenceCoordinator

    @Before
    fun setup() {
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        filesDir = File(context.cacheDir, "WorkoutPersistenceCoordinatorTest-${UUID.randomUUID()}").apply {
            mkdirs()
        }
        workoutStoreRepository = WorkoutStoreRepository(filesDir)
        executedSetStore = DefaultExecutedSetStore()
        coordinator = WorkoutPersistenceCoordinator(
            executedSetStore = executedSetStore,
            executedRestStore = DefaultExecutedRestStore(),
            workoutHistoryDao = { database.workoutHistoryDao() },
            setHistoryDao = { database.setHistoryDao() },
            restHistoryDao = { database.restHistoryDao() },
            exerciseInfoDao = { database.exerciseInfoDao() },
            exerciseSessionProgressionDao = { database.exerciseSessionProgressionDao() },
            workoutStoreRepository = { workoutStoreRepository },
            workoutRecordDao = { database.workoutRecordDao() },
            tag = "WorkoutPersistenceCoordinatorTest"
        )
    }

    @After
    fun tearDown() {
        database.close()
        filesDir.deleteRecursively()
    }

    @Test
    fun pushWorkoutData_doneWorkoutKeepsWarmupSetHistory() = runBlocking {
        val exerciseId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()
        val workout = workout(
            exerciseId = exerciseId,
            workSetId = workSetId
        )
        workoutStoreRepository.saveWorkoutStore(
            WorkoutStore(
                workouts = listOf(workout),
                birthDateYear = 1990,
                weightKg = 75.0,
                progressionPercentageAmount = 0.0
            )
        )

        val warmupSetId = UUID.randomUUID()
        val sessionStart = LocalDateTime.of(2026, 3, 30, 10, 0, 0)
        executedSetStore.replaceAll(
            listOf(
                setHistory(
                    setId = warmupSetId,
                    exerciseId = exerciseId,
                    order = 0u,
                    sequence = 1u,
                    start = sessionStart,
                    end = sessionStart.plusMinutes(1),
                    setData = WeightSetData(
                        actualReps = 8,
                        actualWeight = 40.0,
                        volume = 320.0,
                        subCategory = SetSubCategory.WarmupSet
                    )
                ),
                setHistory(
                    setId = workSetId,
                    exerciseId = exerciseId,
                    order = 1u,
                    sequence = 2u,
                    start = sessionStart.plusMinutes(2),
                    end = sessionStart.plusMinutes(3),
                    setData = WeightSetData(
                        actualReps = 5,
                        actualWeight = 100.0,
                        volume = 500.0,
                        subCategory = SetSubCategory.WorkSet
                    )
                )
            )
        )

        val snapshot = coordinator.capturePushWorkoutDataSnapshot(
            startWorkoutTime = sessionStart,
            selectedWorkout = workout,
            currentWorkoutHistory = null,
            heartBeatRecords = emptyList(),
            progressionByExerciseId = emptyMap(),
            comparisonBaselineByExerciseId = emptyMap()
        ) ?: error("Expected snapshot")

        val persistedWorkoutHistory = coordinator.pushWorkoutData(
            snapshot = snapshot,
            isDone = true,
            updateWorkoutStore = {}
        )

        val persistedSetHistories = database.setHistoryDao()
            .getSetHistoriesByWorkoutHistoryIdAndExerciseIdOrdered(persistedWorkoutHistory.id, exerciseId)

        assertEquals(
            listOf(warmupSetId, workSetId),
            persistedSetHistories.map { it.setId }
        )
        assertEquals(
            listOf(SetSubCategory.WarmupSet, SetSubCategory.WorkSet),
            persistedSetHistories.map { (it.setData as WeightSetData).subCategory }
        )
        assertTrue(
            executedSetStore.executedSets.value.any {
                (it.setData as? WeightSetData)?.subCategory == SetSubCategory.WarmupSet
            }
        )
    }

    private fun workout(
        exerciseId: UUID,
        workSetId: UUID
    ): Workout {
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            notes = "",
            sets = listOf(WeightSet(workSetId, 5, 100.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = true,
            progressionMode = ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
        return Workout(
            id = UUID.randomUUID(),
            name = "Warmup History Test",
            description = "",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.of(2026, 3, 30),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.randomUUID(),
            type = 0
        )
    }

    private fun setHistory(
        setId: UUID,
        exerciseId: UUID,
        order: UInt,
        sequence: UInt,
        start: LocalDateTime,
        end: LocalDateTime,
        setData: WeightSetData
    ): SetHistory {
        return SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = null,
            exerciseId = exerciseId,
            setId = setId,
            order = order,
            startTime = start,
            endTime = end,
            setData = setData,
            skipped = false,
            executionSequence = sequence
        )
    }
}
