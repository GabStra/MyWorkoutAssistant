package com.gabstra.myworkoutassistant.shared.export

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
class WorkoutDataMarkdownExportTest {

    private lateinit var context: Context
    private lateinit var database: AppDatabase

    private val equipmentId = UUID.randomUUID()
    private val exerciseId = UUID.randomUUID()
    private val workoutId = UUID.randomUUID()
    private val workoutGlobalId = UUID.randomUUID()
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
    fun buildWorkoutDataMarkdown_groupsSessionsByWeekWithCompactExpectedAchievedOutput() = runTest {
        val workout = createWorkout()
        val workoutStore = createWorkoutStore(workout)

        insertCompletedSession(
            workoutHistoryId = UUID.randomUUID(),
            date = LocalDate.of(2026, 1, 8),
            weight = 42.5,
            reps = 7
        )
        insertCompletedSession(
            workoutHistoryId = UUID.randomUUID(),
            date = LocalDate.of(2026, 1, 5),
            weight = 40.0,
            reps = 8
        )
        val progressUpdates = mutableListOf<String>()

        val result = buildWorkoutDataMarkdown(
            workoutHistoryDao = database.workoutHistoryDao(),
            setHistoryDao = database.setHistoryDao(),
            restHistoryDao = database.restHistoryDao(),
            exerciseSessionProgressionDao = database.exerciseSessionProgressionDao(),
            workoutStore = workoutStore,
            exportedAt = LocalDateTime.of(2026, 2, 1, 10, 30),
            onProgress = { progressUpdates += it }
        )

        val markdown = (result as WorkoutDataMarkdownResult.Success).markdown
        assertTrue(markdown.contains("# My Workout Assistant Export"))
        assertTrue(markdown.contains("- Exported at: 2026-02-01T10:30:00"))
        assertTrue(markdown.contains("- Session dates: all completed sessions (All data)"))
        assertTrue(markdown.contains("- Time format:"))
        assertTrue(markdown.contains("mm:ss"))
        assertTrue(markdown.contains("hh:mm:ss"))
        assertTrue(markdown.contains("Privacy note:"))
        assertTrue(markdown.contains("## Athlete Info"))
        assertTrue(markdown.contains("- Age:"))
        assertFalse(markdown.contains("#### Athlete Context"))
        assertFalse(markdown.contains("### Athlete Context"))
        assertTrue(markdown.contains("## Plan Reference"))
        assertTrue(markdown.contains("### How loads are reported"))
        assertTrue(markdown.contains("- Push A: 2/week"))
        assertTrue(markdown.contains("- Test Barbell: BARBELL | available loads:"))
        assertTrue(markdown.contains("## Weekly Training Log"))
        assertTrue(markdown.contains("### Week 2026-01-05 to 2026-01-11"))
        assertTrue(markdown.contains("- Objective progress: 100%"))
        assertTrue(markdown.contains("- Push A: achieved 2 / expected 2"))
        assertTrue(markdown.contains("##### Session 1: 2026-01-05 09:00"))
        assertTrue(markdown.contains("##### Session 2: 2026-01-08 09:00"))
        assertTrue(
            markdown.indexOf("##### Session 1: 2026-01-05 09:00") <
                markdown.indexOf("##### Session 2: 2026-01-08 09:00")
        )
        assertTrue(markdown.contains("- Bench Press"))
        assertTrue(markdown.contains("  - Equipment: Test Barbell (BARBELL)"))
        assertTrue(markdown.contains("  - Rep range: 6-8 reps"))
        assertTrue(markdown.contains("  - Execution:"))
        assertTrue(
            markdown.contains(
                    "    - Warm-up 1: expected: 20 kg for 5 reps | achieved: 20 kg for 5 reps (elapsed 00:15)"
            )
        )
        assertTrue(
            markdown.contains(
                    "    - Set 1: expected: 40 kg for 8 reps"
            )
        )
        assertTrue(markdown.contains("      - Side A: 40 kg for 8 reps (elapsed 00:30)"))
        assertTrue(markdown.contains("      - Intra-set rest: planned 01:00 | actual 00:55"))
        assertTrue(markdown.contains("      - Side B: 40 kg for 8 reps (elapsed 00:30)"))
        assertTrue(markdown.contains("  - Summary: matched expected"))
        assertTrue(markdown.contains("  - Progression: PROGRESS"))
        assertFalse(markdown.contains("  - Warm-up achieved:"))
        assertFalse(markdown.contains("  - Achieved:"))
        assertFalse(markdown.contains("  - Outcome:"))
        assertFalse(markdown.contains("  - Rest: planned 01:00; actual 00:55 (avg 00:55)"))
        assertFalse(markdown.contains("- Rests: "))
        assertFalse(markdown.contains("## Workout Plan And Equipment"))
        assertFalse(markdown.contains("# Workout Plan Export"))
        assertFalse(markdown.contains("## Completed Sessions"))
        assertFalse(markdown.contains("#### Executed Timeline"))
        assertFalse(markdown.contains("## Exercise History Summaries"))
        assertFalse(markdown.contains("transport_requests"))
        assertFalse(markdown.contains("conversation_messages"))
        assertFalse(markdown.contains("image_png_base64"))
        assertEquals(
            listOf(
                "Preparing workout data export...",
                "Adding workout plan and equipment...",
                "Processing workout history...",
                "Finishing Markdown export..."
            ),
            progressUpdates
        )
    }

    @Test
    fun buildWorkoutDataMarkdown_filtersSessionsAndExerciseSummariesForCustomRange() = runTest {
        val workout = createWorkout()
        val workoutStore = createWorkoutStore(workout)

        insertCompletedSession(
            workoutHistoryId = UUID.randomUUID(),
            date = LocalDate.of(2025, 12, 20),
            weight = 35.0,
            reps = 5
        )
        insertCompletedSession(
            workoutHistoryId = UUID.randomUUID(),
            date = LocalDate.of(2026, 1, 28),
            weight = 50.0,
            reps = 6
        )
        insertCompletedSession(
            workoutHistoryId = UUID.randomUUID(),
            date = LocalDate.of(2026, 1, 30),
            weight = 55.0,
            reps = 4
        )

        val result = buildWorkoutDataMarkdown(
            workoutHistoryDao = database.workoutHistoryDao(),
            setHistoryDao = database.setHistoryDao(),
            restHistoryDao = database.restHistoryDao(),
            exerciseSessionProgressionDao = database.exerciseSessionProgressionDao(),
            workoutStore = workoutStore,
            exportedAt = LocalDateTime.of(2026, 2, 1, 10, 30),
            exportRange = WorkoutDataExportRange.Custom(
                customStartDate = LocalDate.of(2026, 1, 25),
                customEndDate = LocalDate.of(2026, 1, 29)
            )
        )

        val markdown = (result as WorkoutDataMarkdownResult.Success).markdown
        assertTrue(markdown.contains("- Session dates included: 2026-01-25 to 2026-01-29"))
        assertFalse(markdown.contains("- Sessions since:"))
        assertFalse(markdown.contains("- Sessions until:"))
        assertTrue(markdown.contains("- Completed sessions: 1"))
        assertTrue(markdown.contains("### Week 2026-01-26 to 2026-02-01"))
        assertTrue(markdown.contains("##### Session 1: 2026-01-28 09:00"))
        assertTrue(markdown.contains("50 kg for 6 reps"))
        assertFalse(markdown.contains("2025-12-20"))
        assertFalse(markdown.contains("35 kg for 5 reps"))
        assertFalse(markdown.contains("2026-01-30"))
        assertFalse(markdown.contains("55 kg for 4 reps"))
    }

    @Test
    fun buildWorkoutDataMarkdown_handlesEmptyHistoryAndPlan() = runTest {
        val result = buildWorkoutDataMarkdown(
            workoutHistoryDao = database.workoutHistoryDao(),
            setHistoryDao = database.setHistoryDao(),
            restHistoryDao = database.restHistoryDao(),
            exerciseSessionProgressionDao = database.exerciseSessionProgressionDao(),
            workoutStore = WorkoutStore(
                birthDateYear = 1990,
                weightKg = 80.0,
                progressionPercentageAmount = 2.5
            ),
            exportedAt = LocalDateTime.of(2026, 2, 1, 10, 30)
        )

        val markdown = (result as WorkoutDataMarkdownResult.Success).markdown
        assertTrue(markdown.contains("- Completed sessions: 0"))
        assertTrue(markdown.contains("No workouts configured."))
        assertTrue(markdown.contains("No completed workout sessions found."))
        assertFalse(markdown.contains("## Exercise History Summaries"))
    }

    @Test
    fun buildWorkoutDataMarkdown_omitsMissingExpectedOutcomeForTimedBlocksAndShowsTargetRange() = runTest {
        val cardioWorkout = Workout(
            id = workoutId,
            name = "Cyclette - LISS",
            description = "Steady-state cardio.",
            workoutComponents = listOf(
                Exercise(
                    id = exerciseId,
                    enabled = true,
                    name = "Main Set",
                    notes = "",
                    sets = listOf(
                        TimedDurationSet(
                            id = setId,
                            timeInMillis = 45 * 60 * 1000,
                            autoStart = true,
                            autoStop = true
                        )
                    ),
                    exerciseType = ExerciseType.COUNTDOWN,
                    minReps = 0,
                    maxReps = 0,
                    lowerBoundMaxHRPercent = 60f,
                    upperBoundMaxHRPercent = 80f,
                    equipmentId = null,
                    bodyWeightPercentage = null
                )
            ),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.of(2026, 1, 1),
            globalId = workoutGlobalId,
            type = 0,
            timesCompletedInAWeek = 1
        )
        val workoutStore = createWorkoutStore(cardioWorkout)
        val startTime = LocalDateTime.of(LocalDate.of(2026, 1, 5), LocalTime.of(9, 0))
        val historyId = UUID.randomUUID()
        database.workoutHistoryDao().insert(
            WorkoutHistory(
                id = historyId,
                workoutId = workoutId,
                date = startTime.toLocalDate(),
                time = startTime.toLocalTime(),
                startTime = startTime,
                duration = 45 * 60,
                heartBeatRecords = List(45 * 60) { 140 + (it % 5) },
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = workoutGlobalId
            )
        )
        database.setHistoryDao().insert(
            SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = historyId,
                exerciseId = exerciseId,
                equipmentIdSnapshot = null,
                equipmentNameSnapshot = null,
                equipmentTypeSnapshot = null,
                setId = setId,
                order = 0u,
                startTime = startTime,
                endTime = startTime.plusMinutes(45),
                setData = TimedDurationSetData(
                    startTimer = 45 * 60 * 1000,
                    endTimer = 0,
                    autoStart = true,
                    autoStop = true,
                    hasBeenExecuted = true
                ),
                skipped = false
            )
        )

        val result = buildWorkoutDataMarkdown(
            workoutHistoryDao = database.workoutHistoryDao(),
            setHistoryDao = database.setHistoryDao(),
            restHistoryDao = database.restHistoryDao(),
            exerciseSessionProgressionDao = database.exerciseSessionProgressionDao(),
            workoutStore = workoutStore,
            exportedAt = LocalDateTime.of(2026, 2, 1, 10, 30)
        )

        val markdown = (result as WorkoutDataMarkdownResult.Success).markdown
        val mainSetBlock = markdown.substringAfter("- Main Set").substringBefore("\n\n")
        assertFalse(mainSetBlock.contains("  - Estimated 1RM"))
        assertFalse(mainSetBlock.contains("  - Expected: not recorded"))
        assertTrue(
            mainSetBlock.contains(
                "    - Set 1: expected: 45:00 | achieved: 45:00"
            )
        )
        assertFalse(mainSetBlock.contains("  - Outcome: not available"))
        assertTrue(
            mainSetBlock.contains(
                "  - Heart rate: avg 142 bpm, peak 144 bpm, target range 136-162 bpm, in range 100%"
            )
        )
    }

    @Test
    fun buildWorkoutDataMarkdown_listsAllAvailableLoadsWhenManyUniformWeights() = runTest {
        val workout = createWorkout()
        val vestId = UUID.randomUUID()
        val uniformWeights = (1..25).map { weight -> BaseWeight(weight.toDouble()) }
        val vest = WeightVest(
            id = vestId,
            name = "Many Vest",
            availableWeights = uniformWeights
        )
        val baseStore = createWorkoutStore(workout)
        val workoutStore = baseStore.copy(equipments = baseStore.equipments + vest)

        val result = buildWorkoutDataMarkdown(
            workoutHistoryDao = database.workoutHistoryDao(),
            setHistoryDao = database.setHistoryDao(),
            restHistoryDao = database.restHistoryDao(),
            exerciseSessionProgressionDao = database.exerciseSessionProgressionDao(),
            workoutStore = workoutStore,
            exportedAt = LocalDateTime.of(2026, 2, 1, 10, 30)
        )

        val markdown = (result as WorkoutDataMarkdownResult.Success).markdown
        val vestLine = markdown.lineSequence().first { it.contains("Many Vest") }
        assertFalse("Must not summarize loads", vestLine.contains("step"))
        assertTrue(vestLine.contains("1 kg"))
        assertTrue(vestLine.contains("25 kg"))
        assertTrue(vestLine.count { it == ',' } >= 23)
    }

    private suspend fun insertCompletedSession(
        workoutHistoryId: UUID,
        date: LocalDate,
        weight: Double,
        reps: Int,
    ) {
        val startTime = LocalDateTime.of(date, LocalTime.of(9, 0))
        database.workoutHistoryDao().insert(
            WorkoutHistory(
                id = workoutHistoryId,
                workoutId = workoutId,
                date = date,
                time = LocalTime.of(9, 0),
                startTime = startTime,
                duration = 180,
                heartBeatRecords = List(180) { 110 + (it % 5) },
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
                equipmentNameSnapshot = "Test Barbell",
                equipmentTypeSnapshot = "BARBELL",
                setId = setId,
                order = 0u,
                startTime = startTime.plusSeconds(10),
                endTime = startTime.plusSeconds(25),
                setData = WeightSetData(
                    actualReps = 5,
                    actualWeight = 20.0,
                    volume = 100.0,
                    subCategory = SetSubCategory.WarmupSet
                ),
                skipped = false
            )
        )
        database.setHistoryDao().insert(
            SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                equipmentIdSnapshot = equipmentId,
                equipmentNameSnapshot = "Test Barbell",
                equipmentTypeSnapshot = "BARBELL",
                setId = setId,
                order = 1u,
                startTime = startTime.plusSeconds(30),
                endTime = startTime.plusSeconds(60),
                setData = WeightSetData(
                    actualReps = reps,
                    actualWeight = weight,
                    volume = weight * reps
                ),
                skipped = false
            )
        )
        database.restHistoryDao().insert(
            RestHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                scope = RestHistoryScope.INTRA_EXERCISE,
                setData = RestSetData(
                    startTimer = 60,
                    endTimer = 5
                ),
                startTime = startTime.plusSeconds(60),
                endTime = startTime.plusSeconds(115),
                exerciseId = exerciseId,
                restSetId = UUID.randomUUID(),
                order = 0u
            )
        )
        database.setHistoryDao().insert(
            SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                equipmentIdSnapshot = equipmentId,
                equipmentNameSnapshot = "Test Barbell",
                equipmentTypeSnapshot = "BARBELL",
                setId = setId,
                order = 1u,
                startTime = startTime.plusSeconds(115),
                endTime = startTime.plusSeconds(145),
                setData = WeightSetData(
                    actualReps = reps,
                    actualWeight = weight,
                    volume = weight * reps
                ),
                skipped = false
            )
        )
        database.exerciseSessionProgressionDao().insert(
            ExerciseSessionProgression(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistoryId,
                exerciseId = exerciseId,
                expectedSets = listOf(SimpleSet(weight, reps), SimpleSet(weight, reps)),
                progressionState = ProgressionState.PROGRESS,
                vsExpected = Ternary.EQUAL,
                vsPrevious = Ternary.EQUAL,
                previousSessionVolume = weight * reps,
                expectedVolume = weight * reps * 2,
                executedVolume = weight * reps * 2
            )
        )
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
                    sets = listOf(WeightSet(id = setId, reps = 8, weight = 40.0)),
                    exerciseType = ExerciseType.WEIGHT,
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
                    intraSetRestInSeconds = 60
                )
            ),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.of(2026, 1, 1),
            globalId = workoutGlobalId,
            type = 0,
            timesCompletedInAWeek = 2
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

    private fun String.countOccurrences(value: String): Int {
        return Regex(Regex.escape(value)).findAll(this).count()
    }
}
