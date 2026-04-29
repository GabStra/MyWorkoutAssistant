package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlinx.coroutines.runBlocking

/**
 * Recreates the "A — Squat/Bench" resume scenario using ids sampled from the
 * user-provided backup. The incomplete history contains previously executed sets
 * across several exercises; the test then resumes and completes the remaining work.
 */
object ResumeAWorkoutHistoryFixture {
    const val WORKOUT_NAME = "A - Squat/Bench"

    val WORKOUT_ID: UUID = UUID.fromString("efdba35b-82bf-418e-9362-4ffa2d39e435")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("63c3379f-f734-424c-94e5-05af28a945f8")
    val INCOMPLETE_HISTORY_ID: UUID = UUID.fromString("9b67898a-febe-4c09-9d4e-830cff9ca864")

    val WARMUP_EXERCISE_ID: UUID = UUID.fromString("a370fe36-bc1c-47e5-a2e2-49ea997703d9")
    val BACK_SQUAT_EXERCISE_ID: UUID = UUID.fromString("fc5ff3fe-8128-49b0-a9c6-95ab4f42c488")
    val BENCH_EXERCISE_ID: UUID = UUID.fromString("c8c032e6-af76-4ae7-b1fd-ebe037bc05a3")
    val PULLUPS_EXERCISE_ID: UUID = UUID.fromString("018b4cc4-2698-4855-97de-801200bb0d43")
    val ROW_EXERCISE_ID: UUID = UUID.fromString("6ca47933-c90e-4a41-ba94-13114c1de8e1")
    val ABS_EXERCISE_ID: UUID = UUID.fromString("c482e870-ab88-422e-b144-58cbf55a323f")

    val SEEDED_EXERCISE_MIN_COUNTS: Map<UUID, Int> = mapOf(
        BACK_SQUAT_EXERCISE_ID to 6,
        BENCH_EXERCISE_ID to 6,
        PULLUPS_EXERCISE_ID to 3,
        ROW_EXERCISE_ID to 3
    )

    private val EQUIPMENT_ID: UUID = UUID.fromString("6643d522-83d8-4cea-b339-9108754f9fb0")
    enum class ResumeSeedMode { StableOrder, OrderDriftOnWorkSets }

    fun setup(context: Context) {
        setup(context, ResumeSeedMode.StableOrder)
    }

    fun setup(context: Context, mode: ResumeSeedMode) {
        TestWorkoutStoreSeeder.seedWorkoutStore(context, createWorkoutStore())
        seedIncompleteHistory(context, mode)
    }

    private fun createWorkoutStore(): WorkoutStore {
        val equipment = Barbell(
            id = EQUIPMENT_ID,
            name = "Resume Fixture Barbell",
            availablePlates = listOf(
                Plate(20.0, 20.0),
                Plate(20.0, 20.0),
                Plate(10.0, 15.0),
                Plate(10.0, 15.0),
                Plate(5.0, 10.0),
                Plate(5.0, 10.0),
                Plate(2.5, 5.0),
                Plate(2.5, 5.0),
                Plate(1.25, 3.0),
                Plate(1.25, 3.0),
            ),
            sleeveLength = 200,
            barWeight = 20.0
        )
        val workout = Workout(
            id = WORKOUT_ID,
            name = WORKOUT_NAME,
            description = "Squat, bench press, pull-ups, row, abs",
            workoutComponents = listOf(
                Exercise(
                    id = WARMUP_EXERCISE_ID,
                    enabled = true,
                    name = "Warm Up",
                    notes = "",
                    sets = listOf(TimedDurationSet(UUID.fromString("05de08a7-67a6-4a82-8b43-92ce1a78292d"), 300_000, autoStart = true, autoStop = true)),
                    exerciseType = ExerciseType.COUNTDOWN,
                    minLoadPercent = 0.0,
                    maxLoadPercent = 0.0,
                    minReps = 0,
                    maxReps = 0,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = null,
                    bodyWeightPercentage = null,
                    generateWarmUpSets = false,
                    progressionMode = ProgressionMode.OFF,
                    keepScreenOn = false,
                    showCountDownTimer = true
                ),
                Exercise(
                    id = BACK_SQUAT_EXERCISE_ID,
                    enabled = true,
                    name = "Back Squat",
                    notes = "",
                    sets = listOf(
                        WeightSet(UUID.fromString("b06747fe-bb01-4637-97bc-b8c5a61669a9"), 8, 100.0),
                        WeightSet(UUID.fromString("8d70f241-b84a-4a9c-873b-3b7b3af87a07"), 8, 100.0),
                        WeightSet(UUID.fromString("3525c514-9483-4bfc-a888-ab6d63ac0833"), 8, 100.0),
                    ),
                    exerciseType = ExerciseType.WEIGHT,
                    minLoadPercent = 60.0,
                    maxLoadPercent = 100.0,
                    minReps = 5,
                    maxReps = 12,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = equipment.id,
                    bodyWeightPercentage = null,
                    generateWarmUpSets = true,
                    progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
                    keepScreenOn = false,
                    showCountDownTimer = false
                ),
                Exercise(
                    id = BENCH_EXERCISE_ID,
                    enabled = true,
                    name = "Bench Press",
                    notes = "",
                    sets = listOf(
                        WeightSet(UUID.fromString("ead17a6d-d3ed-402a-ab71-bd683b530105"), 8, 80.0),
                        WeightSet(UUID.fromString("3b7e3899-aca7-4536-97b3-6c83bdd895df"), 8, 80.0),
                        WeightSet(UUID.fromString("02196bbe-97df-42e2-b909-a630f73f6b8d"), 8, 80.0),
                    ),
                    exerciseType = ExerciseType.WEIGHT,
                    minLoadPercent = 60.0,
                    maxLoadPercent = 100.0,
                    minReps = 5,
                    maxReps = 12,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = equipment.id,
                    bodyWeightPercentage = null,
                    generateWarmUpSets = true,
                    progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
                    keepScreenOn = false,
                    showCountDownTimer = false
                ),
                Exercise(
                    id = PULLUPS_EXERCISE_ID,
                    enabled = true,
                    name = "Pull-Ups",
                    notes = "",
                    sets = listOf(
                        BodyWeightSet(UUID.fromString("0ec620b8-8e35-4e28-b8f6-1f836664bfed"), 8, 5.0),
                        BodyWeightSet(UUID.fromString("a304e1fe-b55d-40ec-89a0-637ff78c2695"), 8, 5.0),
                        BodyWeightSet(UUID.fromString("a0bf7c38-ecbd-4582-a625-3e81fe48cc1b"), 8, 5.0),
                    ),
                    exerciseType = ExerciseType.BODY_WEIGHT,
                    minLoadPercent = 60.0,
                    maxLoadPercent = 100.0,
                    minReps = 5,
                    maxReps = 12,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = equipment.id,
                    bodyWeightPercentage = 75.0,
                    generateWarmUpSets = false,
                    progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
                    keepScreenOn = false,
                    showCountDownTimer = false
                ),
                Exercise(
                    id = ROW_EXERCISE_ID,
                    enabled = true,
                    name = "Row",
                    notes = "",
                    sets = listOf(
                        WeightSet(UUID.fromString("243f5cc1-c2cd-4de3-b343-e561f8512301"), 10, 50.0),
                        WeightSet(UUID.fromString("3b45b875-c482-4c81-9b2b-126d0fda9196"), 10, 50.0),
                        WeightSet(UUID.fromString("e16aa164-0df6-44be-93a4-e3ee529b5648"), 10, 50.0),
                    ),
                    exerciseType = ExerciseType.WEIGHT,
                    minLoadPercent = 60.0,
                    maxLoadPercent = 100.0,
                    minReps = 8,
                    maxReps = 15,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = equipment.id,
                    bodyWeightPercentage = null,
                    generateWarmUpSets = false,
                    progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
                    keepScreenOn = false,
                    showCountDownTimer = false
                ),
                Exercise(
                    id = ABS_EXERCISE_ID,
                    enabled = true,
                    name = "Abs Crunch",
                    notes = "",
                    sets = listOf(
                        WeightSet(UUID.fromString("0332d279-c180-4c57-a5de-61407200858c"), 15, 20.0),
                        WeightSet(UUID.fromString("5870c812-08de-4f3b-abf7-dc482e4663d1"), 15, 20.0),
                        WeightSet(UUID.fromString("b2f2ac3b-7733-4328-a575-61d8ccf948d3"), 15, 20.0),
                    ),
                    exerciseType = ExerciseType.WEIGHT,
                    minLoadPercent = 60.0,
                    maxLoadPercent = 100.0,
                    minReps = 10,
                    maxReps = 20,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = equipment.id,
                    bodyWeightPercentage = null,
                    generateWarmUpSets = false,
                    progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
                    keepScreenOn = false,
                    showCountDownTimer = false
                )
            ),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.of(2026, 4, 17),
            previousVersionId = UUID.fromString("fa80170a-37de-43e4-9c3d-030f4dd6c923"),
            nextVersionId = null,
            isActive = true,
            timesCompletedInAWeek = 1,
            globalId = WORKOUT_GLOBAL_ID,
            type = 0
        )

        return WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(equipment),
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )
    }

    private fun seedIncompleteHistory(context: Context, mode: ResumeSeedMode) = runBlocking {
        val db = AppDatabase.getDatabase(context)
        WearFixtureDatabaseSeeder.resetResumeScenarioTables(db)

        val start = LocalDateTime.of(2026, 4, 27, 18, 56, 19)
        db.workoutHistoryDao().insert(
            WorkoutHistory(
                id = INCOMPLETE_HISTORY_ID,
                workoutId = WORKOUT_ID,
                date = start.toLocalDate(),
                time = LocalTime.of(20, 2, 42),
                startTime = start,
                duration = 3982,
                heartBeatRecords = listOf(96, 100, 104),
                isDone = false,
                hasBeenSentToHealth = false,
                globalId = WORKOUT_GLOBAL_ID,
                version = 30u
            )
        )

        val seeded = mutableListOf<SetHistory>()
        seeded += setHistory(
            exerciseId = WARMUP_EXERCISE_ID,
            setId = UUID.fromString("05de08a7-67a6-4a82-8b43-92ce1a78292d"),
            order = 0u,
            startTime = start.plusMinutes(1),
            setData = TimedDurationSetData(
                startTimer = 300_000,
                endTimer = 0,
                autoStart = true,
                autoStop = true
            )
        )
        val squatWorkOrders = if (mode == ResumeSeedMode.OrderDriftOnWorkSets) listOf(1u, 3u, 5u) else listOf(6u, 8u, 10u)
        val benchWorkOrders = if (mode == ResumeSeedMode.OrderDriftOnWorkSets) listOf(1u, 3u, 5u) else listOf(6u, 8u, 10u)

        // Back squat (3 warmups + 3 work)
        seeded += weightHistory(BACK_SQUAT_EXERCISE_ID, UUID.fromString("e4d647bc-bc1c-456b-8ced-10bd62d05fe4"), 0u, start.plusMinutes(6), 5, 20.0, SetSubCategory.WarmupSet)
        seeded += weightHistory(BACK_SQUAT_EXERCISE_ID, UUID.fromString("e79ff242-71a9-4c3d-8db4-031a6c227ee9"), 2u, start.plusMinutes(8), 4, 40.0, SetSubCategory.WarmupSet)
        seeded += weightHistory(BACK_SQUAT_EXERCISE_ID, UUID.fromString("5050629e-f87b-4824-9df6-560d1b4ac77f"), 4u, start.plusMinutes(10), 2, 60.0, SetSubCategory.WarmupSet)
        seeded += weightHistory(BACK_SQUAT_EXERCISE_ID, UUID.fromString("b06747fe-bb01-4637-97bc-b8c5a61669a9"), squatWorkOrders[0], start.plusMinutes(12), 8, 100.0, SetSubCategory.WorkSet)
        seeded += weightHistory(BACK_SQUAT_EXERCISE_ID, UUID.fromString("8d70f241-b84a-4a9c-873b-3b7b3af87a07"), squatWorkOrders[1], start.plusMinutes(15), 8, 100.0, SetSubCategory.WorkSet)
        seeded += weightHistory(BACK_SQUAT_EXERCISE_ID, UUID.fromString("3525c514-9483-4bfc-a888-ab6d63ac0833"), squatWorkOrders[2], start.plusMinutes(18), 8, 100.0, SetSubCategory.WorkSet)
        // Bench (3 warmups + 3 work)
        seeded += weightHistory(BENCH_EXERCISE_ID, UUID.fromString("03e5a587-0b28-4eea-8988-6d20301593df"), 0u, start.plusMinutes(22), 5, 20.0, SetSubCategory.WarmupSet)
        seeded += weightHistory(BENCH_EXERCISE_ID, UUID.fromString("4b605e0e-106e-4480-855d-391fd67ec4a8"), 2u, start.plusMinutes(24), 4, 35.0, SetSubCategory.WarmupSet)
        seeded += weightHistory(BENCH_EXERCISE_ID, UUID.fromString("d337243a-fb4f-4e48-bcd8-88cb1f73bc2d"), 4u, start.plusMinutes(26), 2, 50.0, SetSubCategory.WarmupSet)
        seeded += weightHistory(BENCH_EXERCISE_ID, UUID.fromString("ead17a6d-d3ed-402a-ab71-bd683b530105"), benchWorkOrders[0], start.plusMinutes(28), 8, 80.0, SetSubCategory.WorkSet)
        seeded += weightHistory(BENCH_EXERCISE_ID, UUID.fromString("3b7e3899-aca7-4536-97b3-6c83bdd895df"), benchWorkOrders[1], start.plusMinutes(31), 8, 80.0, SetSubCategory.WorkSet)
        seeded += weightHistory(BENCH_EXERCISE_ID, UUID.fromString("02196bbe-97df-42e2-b909-a630f73f6b8d"), benchWorkOrders[2], start.plusMinutes(34), 8, 80.0, SetSubCategory.WorkSet)
        // Pull-ups + row
        seeded += bodyWeightHistory(PULLUPS_EXERCISE_ID, UUID.fromString("0ec620b8-8e35-4e28-b8f6-1f836664bfed"), 0u, start.plusMinutes(38), 8, 5.0)
        seeded += bodyWeightHistory(PULLUPS_EXERCISE_ID, UUID.fromString("a304e1fe-b55d-40ec-89a0-637ff78c2695"), 2u, start.plusMinutes(41), 8, 5.0)
        seeded += bodyWeightHistory(PULLUPS_EXERCISE_ID, UUID.fromString("a0bf7c38-ecbd-4582-a625-3e81fe48cc1b"), 4u, start.plusMinutes(44), 8, 5.0)
        seeded += weightHistory(ROW_EXERCISE_ID, UUID.fromString("243f5cc1-c2cd-4de3-b343-e561f8512301"), 0u, start.plusMinutes(47), 10, 50.0, SetSubCategory.WorkSet)
        seeded += weightHistory(ROW_EXERCISE_ID, UUID.fromString("3b45b875-c482-4c81-9b2b-126d0fda9196"), 2u, start.plusMinutes(50), 10, 50.0, SetSubCategory.WorkSet)
        seeded += weightHistory(ROW_EXERCISE_ID, UUID.fromString("e16aa164-0df6-44be-93a4-e3ee529b5648"), 4u, start.plusMinutes(53), 10, 50.0, SetSubCategory.WorkSet)

        db.setHistoryDao().insertAll(*seeded.toTypedArray())
        db.workoutRecordDao().insert(
            WorkoutRecord(
                id = UUID.fromString("b99535b3-900a-4622-835a-31b68c16457f"),
                workoutId = WORKOUT_ID,
                workoutHistoryId = INCOMPLETE_HISTORY_ID,
                setIndex = 4u,
                exerciseId = ROW_EXERCISE_ID,
                ownerDevice = SessionOwnerDevice.WEAR.name,
                lastActiveSyncAt = LocalDateTime.of(2026, 4, 27, 19, 56, 53),
                activeSessionRevision = 12u,
                lastKnownSessionState = "Set"
            )
        )
    }

    private fun setHistory(
        exerciseId: UUID,
        setId: UUID,
        order: UInt,
        startTime: LocalDateTime,
        setData: com.gabstra.myworkoutassistant.shared.setdata.SetData
    ): SetHistory {
        return SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = INCOMPLETE_HISTORY_ID,
            exerciseId = exerciseId,
            setId = setId,
            order = order,
            startTime = startTime,
            endTime = startTime.plusSeconds(60),
            setData = setData,
            skipped = false,
            executionSequence = order + 1u
        )
    }

    private fun weightHistory(
        exerciseId: UUID,
        setId: UUID,
        order: UInt,
        startTime: LocalDateTime,
        reps: Int,
        weight: Double,
        subCategory: SetSubCategory
    ): SetHistory {
        val data = WeightSetData(
            actualReps = reps,
            actualWeight = weight,
            volume = reps * weight,
            subCategory = subCategory
        )
        return setHistory(exerciseId, setId, order, startTime, data)
    }

    private fun bodyWeightHistory(
        exerciseId: UUID,
        setId: UUID,
        order: UInt,
        startTime: LocalDateTime,
        reps: Int,
        additionalWeight: Double
    ): SetHistory {
        val data = BodyWeightSetData(
            actualReps = reps,
            additionalWeight = additionalWeight,
            relativeBodyWeightInKg = 56.25,
            volume = reps * (additionalWeight + 56.25),
            bodyWeightPercentageSnapshot = 75.0,
            subCategory = SetSubCategory.WorkSet
        )
        return setHistory(exerciseId, setId, order, startTime, data)
    }
}
