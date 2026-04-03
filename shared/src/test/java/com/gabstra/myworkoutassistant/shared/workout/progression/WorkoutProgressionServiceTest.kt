package com.gabstra.myworkoutassistant.shared.workout.progression

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.buildExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.exerciseSessionSnapshotFromSets
import com.gabstra.myworkoutassistant.shared.toSets
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.DoubleProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.WorkoutManager
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutProgressionServiceTest {

    private lateinit var database: AppDatabase
    private lateinit var context: Context

    @Before
    fun setup() {
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
    fun generateProgressions_bodyWeightWithEquipmentStartingAtBw_selectsHeavierAvailableLoad() {
        val equipment = Dumbbell(
            id = UUID.randomUUID(),
            name = "Test Dumbbell",
            availableDumbbells = listOf(
                BaseWeight(5.0),
                BaseWeight(10.0)
            )
        )
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Pull-up",
            notes = "",
            sets = listOf(
                BodyWeightSet(
                    id = UUID.randomUUID(),
                    reps = 12,
                    additionalWeight = 0.0
                )
            ),
            exerciseType = ExerciseType.BODY_WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 8,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = 100.0,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "Workout",
            description = "",
            workoutComponents = listOf(exercise),
            order = 0,
            creationDate = LocalDate.now(),
            globalId = UUID.randomUUID(),
            type = 0
        )
        val service = WorkoutProgressionService(
            exerciseInfoDao = { database.exerciseInfoDao() },
            setHistoryDao = { database.setHistoryDao() },
            workoutHistoryDao = { database.workoutHistoryDao() },
            exerciseSessionProgressionDao = { database.exerciseSessionProgressionDao() }
        )

        val result = kotlinx.coroutines.runBlocking {
            service.generateProgressions(
                selectedWorkout = workout,
                bodyWeightKg = 80.0,
                getEquipmentById = { id -> if (id == equipment.id) equipment else null },
                getWeightByEquipment = { loadedEquipment -> loadedEquipment?.getWeightsCombinations() ?: emptySet() },
                weightsByEquipment = mutableMapOf()
            )
        }

        val (plan, _) = result.progressionByExerciseId.getValue(exercise.id)
        assertTrue(
            "Next session should select a total load heavier than bodyweight when BW-only set hits the top of the rep range",
            plan.sets.all { it.weight > 80.0 }
        )

        val progressedExercise = service.buildExerciseWithProgression(
            exercise = exercise,
            plan = plan,
            bodyWeightKg = 80.0
        )
        val progressedSet = progressedExercise.sets.single() as BodyWeightSet

        assertEquals(
            "Progression should convert the heavier total load back into a positive additional weight",
            5.0,
            progressedSet.additionalWeight,
            0.0001
        )
    }

    @Test
    fun buildPreProcessedSets_preservesRestSets_whenLoadingLastSuccessfulSession() {
        val w1 = UUID.randomUUID()
        val w2 = UUID.randomUUID()
        val restId = UUID.randomUUID()
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Squat",
            notes = "",
            sets = listOf(
                WeightSet(w1, 10, 50.0),
                RestSet(restId, 90),
                WeightSet(w2, 8, 50.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 6,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )
        val service = WorkoutProgressionService(
            exerciseInfoDao = { database.exerciseInfoDao() },
            setHistoryDao = { database.setHistoryDao() },
            workoutHistoryDao = { database.workoutHistoryDao() },
            exerciseSessionProgressionDao = { database.exerciseSessionProgressionDao() }
        )
        val snapshotOnlyWorkSets = exerciseSessionSnapshotFromSets(
            listOf(
                WeightSet(w1, 10, 52.5),
                WeightSet(w2, 8, 52.5)
            )
        )
        val sessionDecision = SessionDecision(
            progressionState = ProgressionState.RETRY,
            shouldLoadLastSuccessfulSession = true,
            lastSuccessfulSession = snapshotOnlyWorkSets
        )
        val result = service.buildPreProcessedSets(exercise, emptyMap(), sessionDecision)
        assertEquals(3, result.size)
        assertTrue(result[1] is RestSet)
        assertEquals(90, (result[1] as RestSet).timeInSeconds)
        assertEquals(52.5, (result[0] as WeightSet).weight, 0.001)
        assertEquals(52.5, (result[2] as WeightSet).weight, 0.001)
    }

    @Test
    fun buildExerciseWithProgression_preservesRestBetweenWorkSets_matchingTemplateOrder() {
        val w1 = UUID.randomUUID()
        val w2 = UUID.randomUUID()
        val w3 = UUID.randomUUID()
        val r1 = UUID.randomUUID()
        val r2 = UUID.randomUUID()
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Ramp",
            notes = "",
            sets = listOf(
                WeightSet(w1, 8, 40.0),
                RestSet(r1, 60),
                WeightSet(w2, 10, 40.0),
                RestSet(r2, 60),
                WeightSet(w3, 12, 40.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 6,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )
        val service = WorkoutProgressionService(
            exerciseInfoDao = { database.exerciseInfoDao() },
            setHistoryDao = { database.setHistoryDao() },
            workoutHistoryDao = { database.workoutHistoryDao() },
            exerciseSessionProgressionDao = { database.exerciseSessionProgressionDao() }
        )
        val plan = DoubleProgressionHelper.Plan(
            sets = listOf(
                SimpleSet(42.0, 8),
                SimpleSet(42.0, 10),
                SimpleSet(42.0, 12)
            ),
            newVolume = 1.0,
            previousVolume = 1.0
        )
        val progressed = service.buildExerciseWithProgression(exercise, plan, bodyWeightKg = 80.0)
        assertEquals(5, progressed.sets.size)
        assertEquals(w1, (progressed.sets[0] as WeightSet).id)
        assertTrue(progressed.sets[1] is RestSet)
        assertEquals(r1, (progressed.sets[1] as RestSet).id)
        assertEquals(w2, (progressed.sets[2] as WeightSet).id)
        assertTrue(progressed.sets[3] is RestSet)
        assertEquals(r2, (progressed.sets[3] as RestSet).id)
        assertEquals(w3, (progressed.sets[4] as WeightSet).id)
    }

    @Test
    fun buildExerciseSessionSnapshot_roundTrip_preservesRestSetCount() {
        val w1 = UUID.randomUUID()
        val w2 = UUID.randomUUID()
        val restId = UUID.randomUUID()
        val sets = listOf(
            WeightSet(w1, 10, 50.0),
            RestSet(restId, 90),
            WeightSet(w2, 8, 50.0)
        )
        val snapshot = buildExerciseSessionSnapshot(sets, emptyList())
        val roundTrip = snapshot.toSets()
        assertEquals(3, roundTrip.size)
        assertTrue(roundTrip[1] is RestSet)
        assertEquals(90, (roundTrip[1] as RestSet).timeInSeconds)
    }

    @Test
    fun buildExerciseWithProgression_marksProgressedWorkSetsToKeepProgrammedTargets() {
        val setId = UUID.randomUUID()
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Bench",
            notes = "",
            sets = listOf(WeightSet(setId, 8, 80.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 6,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
        val service = WorkoutProgressionService(
            exerciseInfoDao = { database.exerciseInfoDao() },
            setHistoryDao = { database.setHistoryDao() },
            workoutHistoryDao = { database.workoutHistoryDao() },
            exerciseSessionProgressionDao = { database.exerciseSessionProgressionDao() }
        )
        val plan = DoubleProgressionHelper.Plan(
            sets = listOf(SimpleSet(82.5, 9)),
            state = ProgressionState.PROGRESS,
            increment = 2.5,
            previousVolume = 640.0
        )

        val progressed = service.buildExerciseWithProgression(exercise, plan, bodyWeightKg = 80.0)
        val progressedSet = progressed.sets.single() as WeightSet

        assertFalse(progressedSet.shouldReapplyHistoryToSet)
    }

    @Test
    fun completion_replaceSetsFromSessionSnapshot_preservesRestSets_whenExerciseTemplateHasRests() {
        val w1 = UUID.randomUUID()
        val w2 = UUID.randomUUID()
        val restId = UUID.randomUUID()
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Bench",
            notes = "",
            sets = listOf(
                WeightSet(w1, 10, 60.0),
                RestSet(restId, 90),
                WeightSet(w2, 8, 60.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 6,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null,
            progressionMode = ProgressionMode.OFF,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "W",
            description = "",
            workoutComponents = listOf(exercise),
            order = 0,
            creationDate = LocalDate.now(),
            globalId = UUID.randomUUID(),
            type = 0
        )
        val newSets = buildExerciseSessionSnapshot(exercise.sets, emptyList()).toSets()
        assertEquals(3, newSets.size)
        assertTrue(newSets[1] is RestSet)
        assertEquals(90, (newSets[1] as RestSet).timeInSeconds)
        val updated = WorkoutManager.replaceSetsInExerciseRecursively(
            workout.workoutComponents,
            exercise,
            newSets
        )
        val updatedExercise = updated.filterIsInstance<Exercise>().single()
        assertEquals(3, updatedExercise.sets.size)
        assertNotNull(updatedExercise.sets[1] as? RestSet)
        assertEquals(90, (updatedExercise.sets[1] as RestSet).timeInSeconds)
    }

    @Test
    fun computeSessionDecision_sameWeekRepeatWithoutFailures_stillProgresses() {
        val exerciseId = UUID.randomUUID()
        val today = LocalDate.now()
        val sameWeekDate = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        kotlinx.coroutines.runBlocking {
            database.exerciseInfoDao().insert(
                ExerciseInfo(
                    id = exerciseId,
                    bestSession = exerciseSessionSnapshotFromSets(emptyList()),
                    lastSuccessfulSession = exerciseSessionSnapshotFromSets(emptyList()),
                    successfulSessionCounter = 2u,
                    sessionFailedCounter = 0u,
                    lastSessionWasDeload = false,
                    timesCompletedInAWeek = 2,
                    weeklyCompletionUpdateDate = sameWeekDate
                )
            )
        }
        val service = WorkoutProgressionService(
            exerciseInfoDao = { database.exerciseInfoDao() },
            setHistoryDao = { database.setHistoryDao() },
            workoutHistoryDao = { database.workoutHistoryDao() },
            exerciseSessionProgressionDao = { database.exerciseSessionProgressionDao() }
        )

        val decision = kotlinx.coroutines.runBlocking {
            service.computeSessionDecision(exerciseId)
        }

        assertEquals(ProgressionState.PROGRESS, decision.progressionState)
        assertEquals(false, decision.shouldLoadLastSuccessfulSession)
    }
}
