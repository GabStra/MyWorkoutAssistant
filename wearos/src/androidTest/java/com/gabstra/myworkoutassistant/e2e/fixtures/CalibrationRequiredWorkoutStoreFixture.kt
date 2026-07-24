package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.data.WorkoutRecoveryCheckpointStore
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.recovery.RecoveryStateType
import com.gabstra.myworkoutassistant.shared.workout.recovery.WorkoutRecoveryCheckpoint
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import kotlinx.coroutines.runBlocking
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID

/**
 * Fixture for a workout containing one exercise that requires load calibration.
 */
object CalibrationRequiredWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Calibration Workout"
    private val WORKOUT_ID = UUID.fromString("f82a63ed-d507-4cc3-961f-767de30f64d5")
    private val WORKOUT_GLOBAL_ID = UUID.fromString("8904a6cf-e0a1-42c6-9228-029cd97bca24")
    private val EXERCISE_ID = UUID.fromString("dfbe3340-d214-426c-8a46-6d272286a45c")
    private val SET_ID = UUID.fromString("11c4a141-f0e7-4ba3-82c4-b2ce793fa572")
    private val HISTORY_ID = UUID.fromString("ae42229a-4174-4dbc-8ce8-e1c039a6731a")
    private val RECORD_ID = UUID.fromString("7a01de40-00c2-4251-8d2f-38555a29caf4")

    fun setupWorkoutStore(context: Context) {
        val equipment = TestBarbellFactory.createTestBarbell()

        val exercise = Exercise(
            id = EXERCISE_ID,
            enabled = true,
            name = "Calibrated Bench Press",
            notes = "",
            sets = listOf(
                WeightSet(SET_ID, 8, 80.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 5,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            requiresLoadCalibration = true
        )

        val workout = Workout(
            id = WORKOUT_ID,
            name = WORKOUT_NAME,
            description = "Calibration test workout",
            workoutComponents = listOf(exercise),
            order = 0,
            enabled = true,
            heartRateSource = com.gabstra.myworkoutassistant.shared.HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.now(),
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = null,
            globalId = WORKOUT_GLOBAL_ID,
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

    fun setupCalibrationLoadRecovery(context: Context) {
        setupWorkoutStore(context)

        val startTime = LocalDateTime.now().minusMinutes(2)
        runBlocking {
            val db = AppDatabase.getDatabase(context)
            WearFixtureDatabaseSeeder.resetResumeScenarioTables(db)
            db.workoutHistoryDao().insert(
                WorkoutHistory(
                    id = HISTORY_ID,
                    workoutId = WORKOUT_ID,
                    date = startTime.toLocalDate(),
                    time = startTime.toLocalTime(),
                    startTime = startTime,
                    duration = 120,
                    heartBeatRecords = emptyList(),
                    isDone = false,
                    hasBeenSentToHealth = false,
                    globalId = WORKOUT_GLOBAL_ID,
                    version = 1u
                )
            )
            db.workoutRecordDao().insert(
                WorkoutRecord(
                    id = RECORD_ID,
                    workoutId = WORKOUT_ID,
                    workoutHistoryId = HISTORY_ID,
                    setIndex = 0u,
                    exerciseId = EXERCISE_ID,
                    ownerDevice = SessionOwnerDevice.WEAR.name,
                    lastActiveSyncAt = startTime.plusMinutes(1),
                    activeSessionRevision = 1u,
                    lastKnownSessionState = "CalibrationLoadSelection"
                )
            )
        }

        WorkoutRecoveryCheckpointStore(context).save(
            WorkoutRecoveryCheckpoint(
                workoutId = WORKOUT_ID,
                workoutHistoryId = HISTORY_ID,
                stateType = RecoveryStateType.CALIBRATION_LOAD,
                exerciseId = EXERCISE_ID,
                setId = SET_ID,
                setIndex = 0u,
                restOrder = null,
                setStartEpochMs = null,
                updatedAtEpochMs = System.currentTimeMillis()
            ),
            synchronous = true
        )
        context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            .edit()
            .putBoolean("isWorkoutInProgress", true)
            .commit()
    }

    fun getWorkoutName(): String = WORKOUT_NAME
}
