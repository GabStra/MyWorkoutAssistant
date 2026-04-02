package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID

object AlarmTriggerPhoneWorkoutStoreFixture {
    const val WORKOUT_NAME = "Alarm Trigger Workout"
    const val SCHEDULE_LABEL = "Alarm Trigger Reminder"
    /**
     * Keep the synced alarm close enough that the Wear verifier can stay within a stable
     * instrumentation session, while still leaving enough room for phone-to-watch sync.
     */
    private const val CROSS_DEVICE_TRIGGER_MIN_LEAD_SECONDS = 180L

    val WORKOUT_ID: UUID = UUID.fromString("d41b2245-6af2-458e-8a70-c6ad9db52e9c")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("6d9849b0-9f92-4ea6-acbe-c6c69e1d8163")
    val EXERCISE_ID: UUID = UUID.fromString("f6bf08f1-e1be-4d4c-b01a-dfd7279357f0")
    val SET_ID: UUID = UUID.fromString("e844d996-4e39-4351-95bd-91b1ac6da882")
    val SCHEDULE_ID: UUID = UUID.fromString("1e4a430f-9771-4da6-a08d-b0fa53a33542")

    data class AlarmExpectation(
        val schedule: WorkoutSchedule,
        val triggerAt: LocalDateTime
    )

    fun createWorkoutStore(): WorkoutStore {
        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = "Alarm Bench Press",
            notes = "Phone alarm sync fixture exercise",
            sets = listOf(WeightSet(id = SET_ID, reps = 8, weight = 55.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 4,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )

        val workout = Workout(
            id = WORKOUT_ID,
            name = WORKOUT_NAME,
            description = "Phone-seeded alarm trigger fixture",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = WORKOUT_GLOBAL_ID,
            type = 0
        )

        return WorkoutStore(
            workouts = listOf(workout),
            equipments = emptyList(),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }

    fun createCrossDeviceAlarmExpectation(
        now: LocalDateTime = LocalDateTime.now()
    ): AlarmExpectation {
        val triggerAt = nextMinuteBoundaryAfter(now, CROSS_DEVICE_TRIGGER_MIN_LEAD_SECONDS)
        return AlarmExpectation(
            schedule = createSchedule(triggerAt),
            triggerAt = triggerAt
        )
    }

    private fun createSchedule(triggerAt: LocalDateTime): WorkoutSchedule {
        return WorkoutSchedule(
            id = SCHEDULE_ID,
            workoutId = WORKOUT_GLOBAL_ID,
            label = SCHEDULE_LABEL,
            hour = triggerAt.hour,
            minute = triggerAt.minute,
            isEnabled = true,
            daysOfWeek = 0,
            specificDate = triggerAt.toLocalDate(),
            hasExecuted = false,
            lastNotificationSentAt = null
        )
    }

    private fun nextMinuteBoundaryAfter(now: LocalDateTime, minLeadSeconds: Long): LocalDateTime {
        var candidate = now.withSecond(0).withNano(0).plusMinutes(1)
        while (Duration.between(now, candidate).seconds < minLeadSeconds) {
            candidate = candidate.plusMinutes(1)
        }
        return candidate
    }
}
