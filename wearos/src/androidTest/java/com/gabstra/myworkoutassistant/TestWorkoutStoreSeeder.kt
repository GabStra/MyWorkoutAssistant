package com.gabstra.myworkoutassistant

import android.content.Context
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.io.File
import java.time.LocalDate
import java.util.UUID

/**
 * Test-only helper used by Wear OS E2E tests to ensure the watch
 * has a realistic WorkoutStore available before the app launches.
 *
 * NOTE: All E2E tests should call [seedWorkoutStore] before starting MainActivity.
 */
object TestWorkoutStoreSeeder {

    /**
     * Seed the watch's filesDir with the given [workoutStore], or a default
     * realistic test store if none is provided.
     *
     * This writes to the same location and filename used by WorkoutStoreRepository:
     *   File(context.filesDir, "workout_store.json")
     */
    fun seedWorkoutStore(
        context: Context,
        workoutStore: WorkoutStore? = null,
    ): WorkoutStore {
        val storeToWrite = workoutStore ?: createDefaultTestWorkoutStore()

        // Serialize using the same JSON adapters as the production app
        val json = fromWorkoutStoreToJSON(storeToWrite)
        val file = File(context.filesDir, "workout_store.json")
        file.writeText(json)

        return storeToWrite
    }

    /**
     * Default realistic WorkoutStore used when tests don't need
     * a custom structure. Can also be used directly by tests as a base
     * and then copied/modified.
     */
    fun createDefaultTestWorkoutStore(): WorkoutStore {
        val equipment = createTestBarbell()
        val workout = createTestWorkout(equipment.id)

        return WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }

    private fun createTestBarbell(): Barbell {
        val plates = listOf(
            Plate(20.0, 20.0),
            Plate(10.0, 15.0),
            Plate(5.0, 10.0),
            Plate(2.5, 5.0),
            Plate(1.25, 3.0)
        )
        return Barbell(
            id = UUID.randomUUID(),
            name = "Test Barbell",
            availablePlates = plates,
            barLength = 200,
            barWeight = 20.0
        )
    }

    private fun createTestWorkout(equipmentId: UUID): Workout {
        val exercise1Id = UUID.randomUUID()
        val exercise2Id = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()
        val set3Id = UUID.randomUUID()

        val exercise1 = Exercise(
            id = exercise1Id,
            enabled = true,
            name = "Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set1Id, 10, 100.0),
                RestSet(UUID.randomUUID(), 90),
                WeightSet(set2Id, 8, 100.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = true,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )

        val exercise2 = Exercise(
            id = exercise2Id,
            enabled = true,
            name = "Squats",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set3Id, 12, 80.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            enableProgression = true,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2
        )

        return Workout(
            id = UUID.randomUUID(),
            name = "Test Workout",
            description = "Test Description",
            workoutComponents = listOf(exercise1, exercise2),
            order = 0,
            enabled = true,
            usePolarDevice = false,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.randomUUID(),
            type = 0
        )
    }
}


