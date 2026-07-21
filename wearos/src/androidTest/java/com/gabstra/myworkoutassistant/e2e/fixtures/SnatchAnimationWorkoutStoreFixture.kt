package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object SnatchAnimationWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Test Workout"
    private const val EXERCISE_NAME = "Pull Up"

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()
        val movementJson = InstrumentationRegistry.getInstrumentation()
            .context
            .assets
            .open("pull_up_preview_skeleton.json")
            .bufferedReader()
            .use { reader -> reader.readText() }
        val movementRef = ExerciseMovementRef.forWearSkeletonJson(
            movementId = "pull-up-test",
            json = movementJson,
        )
        ExerciseMovementStorage.writeMovementJson(
            context = context,
            movementRef = movementRef,
            json = movementJson,
        )
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = EXERCISE_NAME,
            notes = "",
            sets = listOf(
                WeightSet(UUID.randomUUID(), 2, 60.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 1,
            maxReps = 3,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = 0.025,
            loadJumpMaxPct = 0.5,
            loadJumpOvercapUntil = 2,
            movementRef = movementRef,
        )

        val workout = Workout(
            id = UUID.randomUUID(),
            name = WORKOUT_NAME,
            description = "Animation test workout",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.randomUUID(),
            type = 0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(
            context,
            WorkoutStore(
                workouts = listOf(workout),
                equipments = listOf(equipment),
                birthDateYear = 1990,
                weightKg = 75.0,
                progressionPercentageAmount = 0.0
            )
        )
    }

    fun getWorkoutName(): String = WORKOUT_NAME
}
