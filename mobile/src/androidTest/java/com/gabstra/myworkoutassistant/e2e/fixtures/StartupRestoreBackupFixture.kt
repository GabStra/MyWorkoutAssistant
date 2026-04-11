package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

object StartupRestoreBackupFixture {
    const val WORKOUT_NAME = "Startup Restore Downloads Backup Workout"
    const val EXERCISE_NAME = "Startup Restore Press"
    const val BACKUP_FILE_PREFIX = "workout_backup_startup_restore_regression"

    val WORKOUT_ID: UUID = UUID.fromString("8f0d1d9f-8e87-4e6c-8063-c8af5dc550f5")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("61d1be0f-51e1-40f8-b907-645693e4b41d")
    val EXERCISE_ID: UUID = UUID.fromString("d8bf01bf-376d-4c79-92a9-dabf226e8cb4")
    val SET_ID: UUID = UUID.fromString("ca7bde60-9f7f-4e23-9783-9f90ee29151a")

    fun createBackup(): AppBackup {
        return AppBackup(
            WorkoutStore = createWorkoutStore(),
            WorkoutHistories = emptyList(),
            SetHistories = emptyList(),
            ExerciseInfos = emptyList(),
            WorkoutSchedules = emptyList(),
            WorkoutRecords = emptyList(),
            ExerciseSessionProgressions = emptyList(),
            ErrorLogs = null,
            RestHistories = emptyList()
        )
    }

    private fun createWorkoutStore(): WorkoutStore {
        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = EXERCISE_NAME,
            notes = "Restored from a pre-existing Downloads backup during first app launch.",
            sets = listOf(WeightSet(id = SET_ID, reps = 7, weight = 42.5)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
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

        return WorkoutStore(
            workouts = listOf(
                Workout(
                    id = WORKOUT_ID,
                    name = WORKOUT_NAME,
                    description = "Regression fixture for first-launch restore from Downloads.",
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
            ),
            equipments = emptyList(),
            accessoryEquipments = emptyList(),
            workoutPlans = emptyList(),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }
}
