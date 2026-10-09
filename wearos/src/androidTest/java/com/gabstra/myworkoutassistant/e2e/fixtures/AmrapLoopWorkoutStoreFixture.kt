package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.LocalDate
import java.util.UUID

/**
 * Fixture for the AMRAP round-loop behavior: one plain exercise followed by a
 * two-member superset in AMRAP mode with a generous cap as the final component.
 * Completing the pre-block set enters the cap window; completing both members
 * must re-present the same round (round 2) instead of finishing the workout, and
 * the cap must then cut to completion hands-free.
 */
object AmrapLoopWorkoutStoreFixture {
    const val WORKOUT_NAME = "Amrap Loop Workout"

    lateinit var preBlockSetId: UUID
        private set
    lateinit var memberOneSetId: UUID
        private set
    lateinit var memberTwoSetId: UUID
        private set

    private lateinit var workoutId: UUID

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()

        fun weightExercise(name: String, setId: UUID): Exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = name,
            notes = "",
            sets = listOf(WeightSet(setId, 10, 40.0)),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )

        preBlockSetId = UUID.randomUUID()
        memberOneSetId = UUID.randomUUID()
        memberTwoSetId = UUID.randomUUID()

        val preBlockExercise = weightExercise("Pre-AMRAP Exercise", preBlockSetId).copy(
            sets = listOf(WeightSet(preBlockSetId, 10, 100.0))
        )
        val members = listOf(
            weightExercise("Amrap Member One", memberOneSetId),
            weightExercise("Amrap Member Two", memberTwoSetId)
        )

        workoutId = UUID.randomUUID()
        val superset = Superset(
            id = UUID.randomUUID(),
            enabled = true,
            exercises = members,
            restSecondsByExercise = members.associate { it.id to 0 },
            timeCapSeconds = 40,
            amrap = true
        )

        val workout = Workout(
            id = workoutId,
            name = WORKOUT_NAME,
            description = "AMRAP round loop e2e",
            workoutComponents = listOf(preBlockExercise, superset),
            order = 0,
            enabled = true,
            heartRateSource = com.gabstra.myworkoutassistant.shared.HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = UUID.randomUUID(),
            type = 0
        )

        val workoutStore = WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    fun getWorkoutName(): String = WORKOUT_NAME

    fun getWorkoutId(): UUID = workoutId
}
