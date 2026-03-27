package com.gabstra.myworkoutassistant.shared.export

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
@OptIn(ExperimentalCoroutinesApi::class)
class WorkoutSessionMarkdownExportTest {

    private lateinit var context: Context
    private lateinit var database: AppDatabase

    private val equipmentId = UUID.randomUUID()
    private val exerciseId = UUID.randomUUID()
    private val workoutId = UUID.randomUUID()
    private val workoutGlobalId = UUID.randomUUID()
    private val restSetId = UUID.randomUUID()
    private val workSet1Id = UUID.randomUUID()
    private val workSet2Id = UUID.randomUUID()

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun buildWorkoutSessionMarkdown_includesHistoricalCoachingSections() = runTest {
        val workout = createWorkout()
        val workoutStore = createWorkoutStore(workout)

        val firstHistoryId = UUID.randomUUID()
        val secondHistoryId = UUID.randomUUID()
        val selectedHistoryId = UUID.randomUUID()

        insertCompletedSession(
            workoutHistoryId = firstHistoryId,
            date = LocalDate.of(2026, 1, 5),
            time = LocalTime.of(9, 0),
            firstWeight = 40.0,
            firstReps = 7,
            secondWeight = 40.0,
            secondReps = 7,
            progressionState = ProgressionState.PROGRESS,
            vsExpected = Ternary.EQUAL,
            vsPrevious = Ternary.EQUAL
        )
        insertCompletedSession(
            workoutHistoryId = secondHistoryId,
            date = LocalDate.of(2026, 1, 12),
            time = LocalTime.of(9, 0),
            firstWeight = 42.5,
            firstReps = 8,
            secondWeight = 42.5,
            secondReps = 7,
            progressionState = ProgressionState.PROGRESS,
            vsExpected = Ternary.ABOVE,
            vsPrevious = Ternary.ABOVE
        )
        insertCompletedSession(
            workoutHistoryId = selectedHistoryId,
            date = LocalDate.of(2026, 1, 19),
            time = LocalTime.of(9, 0),
            firstWeight = 45.0,
            firstReps = 8,
            secondWeight = 45.0,
            secondReps = 8,
            progressionState = ProgressionState.PROGRESS,
            vsExpected = Ternary.EQUAL,
            vsPrevious = Ternary.ABOVE
        )

        val result = buildWorkoutSessionMarkdown(
            workoutHistoryId = selectedHistoryId,
            workoutHistoryDao = database.workoutHistoryDao(),
            setHistoryDao = database.setHistoryDao(),
            restHistoryDao = database.restHistoryDao(),
            exerciseSessionProgressionDao = database.exerciseSessionProgressionDao(),
            workoutStore = workoutStore
        )

        val markdown = (result as WorkoutSessionMarkdownResult.Success).markdown
        assertTrue(markdown.contains("#### Athlete Context"))
        assertTrue(markdown.contains("#### Session Heart Rate"))
        assertTrue(markdown.contains("#### Planned"))
        assertTrue(markdown.contains("- P1: 45 kg × 8 reps"))
        assertTrue(markdown.contains("#### Executed"))
        assertTrue(markdown.contains("#### Previous Session"))
        assertTrue(markdown.contains("- Date: 2026-01-12 09:00"))
        assertTrue(markdown.contains("#### Best To Date"))
        assertTrue(markdown.contains("- Note: selected session"))
        assertTrue(markdown.contains("#### Recovery Context"))
        assertTrue(markdown.contains("#### Coaching Signals"))
        assertTrue(markdown.contains("best_to_date"))
        assertTrue(markdown.contains("#### Trend (last 3 sessions)"))
        assertTrue(markdown.contains("- 2026-01-05 | Push A"))
        assertTrue(markdown.contains("- 2026-01-19 | Push A"))
        assertTrue(markdown.contains("| selected"))
    }

    @Test
    fun buildWorkoutSessionMarkdown_marksMissingPreviousSessionExplicitly() = runTest {
        val workout = createWorkout()
        val workoutStore = createWorkoutStore(workout)
        val selectedHistoryId = UUID.randomUUID()

        insertCompletedSession(
            workoutHistoryId = selectedHistoryId,
            date = LocalDate.of(2026, 2, 2),
            time = LocalTime.of(8, 30),
            firstWeight = 35.0,
            firstReps = 10,
            secondWeight = 35.0,
            secondReps = 10,
            progressionState = null,
            vsExpected = null,
            vsPrevious = null
        )

        val result = buildWorkoutSessionMarkdown(
            workoutHistoryId = selectedHistoryId,
            workoutHistoryDao = database.workoutHistoryDao(),
            setHistoryDao = database.setHistoryDao(),
            restHistoryDao = database.restHistoryDao(),
            exerciseSessionProgressionDao = database.exerciseSessionProgressionDao(),
            workoutStore = workoutStore
        )

        val markdown = (result as WorkoutSessionMarkdownResult.Success).markdown
        assertTrue(markdown.contains("#### Previous Session\n- None"))
        assertTrue(markdown.contains("#### Trend (last 1 sessions)"))
        assertTrue(markdown.contains("#### Executed Timeline"))
    }

    private suspend fun insertCompletedSession(
        workoutHistoryId: UUID,
        date: LocalDate,
        time: LocalTime,
        firstWeight: Double,
        firstReps: Int,
        secondWeight: Double,
        secondReps: Int,
        progressionState: ProgressionState?,
        vsExpected: Ternary?,
        vsPrevious: Ternary?,
    ) {
        val startTime = LocalDateTime.of(date, time)
        database.workoutHistoryDao().insert(
            com.gabstra.myworkoutassistant.shared.WorkoutHistory(
                id = workoutHistoryId,
                workoutId = workoutId,
                date = date,
                time = time,
                startTime = startTime,
                duration = 180,
                heartBeatRecords = List(720) { 118 + (it % 9) },
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = workoutGlobalId
            )
        )

        database.setHistoryDao().insertAll(
            SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                equipmentIdSnapshot = equipmentId,
                equipmentNameSnapshot = "Test Barbell",
                equipmentTypeSnapshot = "BARBELL",
                setId = workSet1Id,
                order = 0u,
                startTime = startTime.plusSeconds(5),
                endTime = startTime.plusSeconds(35),
                setData = WeightSetData(
                    actualReps = firstReps,
                    actualWeight = firstWeight,
                    volume = firstWeight * firstReps
                ),
                skipped = false
            ),
            SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                equipmentIdSnapshot = equipmentId,
                equipmentNameSnapshot = "Test Barbell",
                equipmentTypeSnapshot = "BARBELL",
                setId = workSet2Id,
                order = 2u,
                startTime = startTime.plusSeconds(95),
                endTime = startTime.plusSeconds(125),
                setData = WeightSetData(
                    actualReps = secondReps,
                    actualWeight = secondWeight,
                    volume = secondWeight * secondReps
                ),
                skipped = false
            )
        )

        database.restHistoryDao().insert(
            RestHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                scope = RestHistoryScope.INTRA_EXERCISE,
                executionSequence = 2u,
                setData = RestSetData(
                    startTimer = 60,
                    endTimer = 0
                ),
                startTime = startTime.plusSeconds(35),
                endTime = startTime.plusSeconds(95),
                exerciseId = exerciseId,
                restSetId = restSetId,
                order = 1u
            )
        )

        if (progressionState != null && vsExpected != null && vsPrevious != null) {
            val expectedSets = listOf(
                SimpleSet(firstWeight, firstReps),
                SimpleSet(secondWeight, secondReps)
            )
            val executedVolume = (firstWeight * firstReps) + (secondWeight * secondReps)
            database.exerciseSessionProgressionDao().insert(
                ExerciseSessionProgression(
                    id = UUID.randomUUID(),
                    workoutHistoryId = workoutHistoryId,
                    exerciseId = exerciseId,
                    expectedSets = expectedSets,
                    progressionState = progressionState,
                    vsExpected = vsExpected,
                    vsPrevious = vsPrevious,
                    previousSessionVolume = executedVolume - 40.0,
                    expectedVolume = executedVolume,
                    executedVolume = executedVolume
                )
            )
        }
    }

    private fun createWorkout(): Workout {
        return Workout(
            id = workoutId,
            name = "Push A",
            description = "Upper-body pressing focus.",
            workoutComponents = listOf(
                Exercise(
                    id = exerciseId,
                    enabled = true,
                    name = "Bench Press",
                    notes = "Pause on chest.",
                    sets = listOf(
                        WeightSet(id = workSet1Id, reps = 8, weight = 45.0),
                        RestSet(id = restSetId, timeInSeconds = 60),
                        WeightSet(id = workSet2Id, reps = 8, weight = 45.0)
                    ),
                    exerciseType = ExerciseType.WEIGHT,
                    minLoadPercent = 70.0,
                    maxLoadPercent = 85.0,
                    minReps = 6,
                    maxReps = 8,
                    lowerBoundMaxHRPercent = 0.65f,
                    upperBoundMaxHRPercent = 0.85f,
                    equipmentId = equipmentId,
                    bodyWeightPercentage = null,
                    generateWarmUpSets = true,
                    progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
                    keepScreenOn = false,
                    showCountDownTimer = false,
                    intraSetRestInSeconds = null
                )
            ),
            order = 0,
            enabled = true,
            usePolarDevice = false,
            creationDate = LocalDate.of(2026, 1, 1),
            globalId = workoutGlobalId,
            type = 0
        )
    }

    private fun createWorkoutStore(workout: Workout): WorkoutStore {
        return WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(
                Barbell(
                    id = equipmentId,
                    name = "Test Barbell",
                    availablePlates = listOf(
                        Plate(weight = 20.0, thickness = 20.0),
                        Plate(weight = 10.0, thickness = 15.0),
                        Plate(weight = 5.0, thickness = 10.0),
                        Plate(weight = 2.5, thickness = 5.0),
                    ),
                    sleeveLength = 200,
                    barWeight = 20.0
                )
            ),
            birthDateYear = 1990,
            weightKg = 82.0,
            progressionPercentageAmount = 2.5,
            measuredMaxHeartRate = 188,
            restingHeartRate = 58
        )
    }
}
