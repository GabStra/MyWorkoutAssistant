package com.gabstra.myworkoutassistant.shared.export

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
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
class ExerciseHistoryMarkdownExportTest {

    private lateinit var context: Context
    private lateinit var database: AppDatabase

    private val exerciseId = UUID.randomUUID()
    private val workoutId = UUID.randomUUID()
    private val workoutGlobalId = UUID.randomUUID()
    private val vestId = UUID.randomUUID()
    private val dumbbellId = UUID.randomUUID()
    private val setId = UUID.randomUUID()

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
    fun buildExerciseHistoryMarkdown_listsEquipmentHistoryAndBodyWeightFormulaOnce() = runTest {
        val exercise = bodyWeightExercise()
        val workout = workoutWith(exercise)
        val workoutStore = workoutStore(workout)

        insertBodyWeightSession(
            date = LocalDate.of(2026, 3, 1),
            equipmentId = vestId,
            equipmentName = "Weighted Vest",
            relativeBodyWeight = 60.0,
            additionalWeight = 10.0,
            reps = 8
        )
        insertBodyWeightSession(
            date = LocalDate.of(2026, 3, 8),
            equipmentId = dumbbellId,
            equipmentName = "Dip Dumbbell",
            relativeBodyWeight = 60.0,
            additionalWeight = 12.5,
            reps = 9
        )

        val result = buildExerciseHistoryMarkdown(
            exercise = exercise,
            workoutHistoryDao = database.workoutHistoryDao(),
            setHistoryDao = database.setHistoryDao(),
            restHistoryDao = database.restHistoryDao(),
            exerciseSessionProgressionDao = database.exerciseSessionProgressionDao(),
            workouts = listOf(workout),
            workoutStore = workoutStore
        )

        val markdown = (result as ExerciseHistoryMarkdownResult.Success).markdown

        assertTrue(markdown.contains("#### Equipment\n- Weighted Vest | Weights: 5,10,15 kg\n- Dip Dumbbell | Weights: 10,12.5,15 kg"))
        assertTrue(markdown.contains("#### Body Weight Load"))
        assertTrue(markdown.contains("Relative BW = session BW x 75%"))
        assertTrue(markdown.contains("Set load = relative BW +/- equipment weight"))
        assertTrue(markdown.contains("60 kg relative BW (80 kg x 75%) + 10 kg equipment = 70 kg x 8"))
        assertTrue(markdown.contains("60 kg relative BW (80 kg x 75%) + 12.5 kg equipment = 72.5 kg x 9"))
        assertEquals(
            "Equipment section should only be emitted once",
            markdown.indexOf("#### Equipment"),
            markdown.lastIndexOf("#### Equipment")
        )
        assertTrue(markdown.indexOf("#### Equipment") < markdown.indexOf("## S1"))
    }

    private suspend fun insertBodyWeightSession(
        date: LocalDate,
        equipmentId: UUID,
        equipmentName: String,
        relativeBodyWeight: Double,
        additionalWeight: Double,
        reps: Int,
    ) {
        val workoutHistoryId = UUID.randomUUID()
        val startTime = LocalDateTime.of(date, LocalTime.of(9, 0))
        database.workoutHistoryDao().insert(
            WorkoutHistory(
                id = workoutHistoryId,
                workoutId = workoutId,
                date = date,
                time = LocalTime.of(9, 0),
                startTime = startTime,
                duration = 120,
                heartBeatRecords = emptyList(),
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = workoutGlobalId
            )
        )
        database.setHistoryDao().insert(
            SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                equipmentIdSnapshot = equipmentId,
                equipmentNameSnapshot = equipmentName,
                equipmentTypeSnapshot = null,
                setId = setId,
                order = 0u,
                startTime = startTime,
                endTime = startTime.plusSeconds(30),
                setData = BodyWeightSetData(
                    actualReps = reps,
                    additionalWeight = additionalWeight,
                    relativeBodyWeightInKg = relativeBodyWeight,
                    volume = (relativeBodyWeight + additionalWeight) * reps,
                    bodyWeightPercentageSnapshot = 75.0
                ),
                skipped = false
            )
        )
    }

    private fun bodyWeightExercise(): Exercise {
        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Pull Up",
            notes = "",
            sets = listOf(BodyWeightSet(id = setId, reps = 8, additionalWeight = 10.0)),
            exerciseType = ExerciseType.BODY_WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 0.0,
            minReps = 6,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = vestId,
            bodyWeightPercentage = 75.0,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null
        )
    }

    private fun workoutWith(exercise: Exercise): Workout {
        return Workout(
            id = workoutId,
            name = "Pull Day",
            description = "",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.of(2026, 1, 1),
            globalId = workoutGlobalId,
            type = 0
        )
    }

    private fun workoutStore(workout: Workout): WorkoutStore {
        return WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(
                WeightVest(
                    id = vestId,
                    name = "Weighted Vest",
                    availableWeights = listOf(BaseWeight(5.0), BaseWeight(10.0), BaseWeight(15.0))
                ),
                Dumbbell(
                    id = dumbbellId,
                    name = "Dip Dumbbell",
                    availableDumbbells = listOf(BaseWeight(10.0), BaseWeight(12.5), BaseWeight(15.0))
                )
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 2.5,
            measuredMaxHeartRate = null,
            restingHeartRate = null
        )
    }
}
