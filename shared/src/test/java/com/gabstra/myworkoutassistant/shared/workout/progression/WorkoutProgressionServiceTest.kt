package com.gabstra.myworkoutassistant.shared.workout.progression

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.LocalDate
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
            doNotStoreHistory = false,
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
}
