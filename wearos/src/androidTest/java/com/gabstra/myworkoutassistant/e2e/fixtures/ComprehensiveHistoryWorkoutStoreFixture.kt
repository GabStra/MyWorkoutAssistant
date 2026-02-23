package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.e2e.helpers.TestWorkoutStoreSeeder
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Generic
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.util.UUID

/**
 * Comprehensive fixture for creating a workout store with all exercise types and equipment types.
 * Used to test exercise history storage after workout completion.
 */
object ComprehensiveHistoryWorkoutStoreFixture {
    private const val WORKOUT_NAME = "Comprehensive History Test Workout"

    fun setupWorkoutStore(context: Context) {
        val equipments = listOf(
            createTestBarbell(),
            createTestDumbbells(),
            createTestDumbbell(),
            createTestPlateLoadedCable(),
            createTestWeightVest(),
            createTestMachine(),
            createTestGeneric()
        )

        val exercises = mutableListOf<Exercise>()

        // Exercise 1: WEIGHT, BARBELL - 3 WeightSets (1 WarmupSet, 2 WorkSets) with RestSets
        exercises.add(createBarbellExercise(equipments[0].id))

        // Exercise 2: WEIGHT, DUMBBELLS - 2 WeightSets
        exercises.add(createDumbbellsExercise(equipments[1].id))

        // Exercise 3: WEIGHT, DUMBBELL - 2 WeightSets
        exercises.add(createDumbbellExercise(equipments[2].id))

        // Exercise 4: WEIGHT, PLATELOADEDCABLE - 2 WeightSets
        exercises.add(createPlateLoadedCableExercise(equipments[3].id))

        // Exercise 5: WEIGHT, WEIGHTVEST - 2 WeightSets
        exercises.add(createWeightVestExercise(equipments[4].id))

        // Exercise 6: WEIGHT, MACHINE - 2 WeightSets
        exercises.add(createMachineExercise(equipments[5].id))

        // Exercise 7: WEIGHT, GENERIC - 2 WeightSets
        exercises.add(createGenericExercise(equipments[6].id))

        // Exercise 8: BODY_WEIGHT - 2 BodyWeightSets
        exercises.add(createBodyWeightExercise())

        // Exercise 9: COUNTDOWN - 1 TimedDurationSet
        exercises.add(createCountdownExercise())

        // Exercise 10: COUNTUP - 1 EnduranceSet
        exercises.add(createCountupExercise())

        // Exercise 11: WEIGHT, BARBELL, doNotStoreHistory=true
        exercises.add(createDoNotStoreHistoryExercise(equipments[0].id))

        val workout = Workout(
            id = UUID.randomUUID(),
            name = WORKOUT_NAME,
            description = "Comprehensive test workout for history storage verification",
            workoutComponents = exercises,
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

        val workoutStore = WorkoutStore(
            workouts = listOf(workout),
            equipments = equipments,
            polarDeviceId = null,
            birthDateYear = 1990,
            weightKg = 75.0,
            progressionPercentageAmount = 0.0
        )

        TestWorkoutStoreSeeder.seedWorkoutStore(context, workoutStore)
    }

    fun getWorkoutName(): String = WORKOUT_NAME

    // Equipment factory methods

    private fun createTestBarbell() = TestBarbellFactory.createTestBarbell()

    private fun createTestDumbbells(): Dumbbells {
        return Dumbbells(
            id = UUID.randomUUID(),
            name = "Test Dumbbells",
            availableDumbbells = listOf(
                BaseWeight(5.0),
                BaseWeight(10.0),
                BaseWeight(15.0),
                BaseWeight(20.0)
            ),
            extraWeights = emptyList(),
            maxExtraWeightsPerLoadingPoint = 0
        )
    }

    private fun createTestDumbbell(): Dumbbell {
        return Dumbbell(
            id = UUID.randomUUID(),
            name = "Test Dumbbell",
            availableDumbbells = listOf(
                BaseWeight(5.0),
                BaseWeight(10.0),
                BaseWeight(15.0)
            ),
            extraWeights = emptyList(),
            maxExtraWeightsPerLoadingPoint = 0
        )
    }

    private fun createTestPlateLoadedCable(): PlateLoadedCable {
        return PlateLoadedCable(
            id = UUID.randomUUID(),
            name = "Test Plate Loaded Cable",
            availablePlates = listOf(
                Plate(10.0, 15.0),
                Plate(5.0, 10.0),
                Plate(2.5, 5.0)
            ),
            sleeveLength = 200
        )
    }

    private fun createTestWeightVest(): WeightVest {
        return WeightVest(
            id = UUID.randomUUID(),
            name = "Test Weight Vest",
            availableWeights = listOf(
                BaseWeight(5.0),
                BaseWeight(10.0),
                BaseWeight(15.0),
                BaseWeight(20.0)
            )
        )
    }

    private fun createTestMachine(): Machine {
        return Machine(
            id = UUID.randomUUID(),
            name = "Test Machine",
            availableWeights = listOf(
                BaseWeight(10.0),
                BaseWeight(20.0),
                BaseWeight(30.0)
            ),
            extraWeights = listOf(
                BaseWeight(2.5),
                BaseWeight(5.0)
            ),
            maxExtraWeightsPerLoadingPoint = 2
        )
    }

    private fun createTestGeneric(): Generic {
        return Generic(
            id = UUID.randomUUID(),
            name = "Test Generic Equipment"
        )
    }

    // Exercise factory methods

    private fun createBarbellExercise(equipmentId: UUID): Exercise {
        val exerciseId = UUID.randomUUID()
        val warmupSetId = UUID.randomUUID()
        val workSet1Id = UUID.randomUUID()
        val workSet2Id = UUID.randomUUID()
        val restId1 = UUID.randomUUID()
        val restId2 = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Barbell Bench Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(warmupSetId, 10, 40.0, SetSubCategory.WarmupSet), // 20kg bar + 20kg plates
                RestSet(restId1, 60),
                WeightSet(workSet1Id, 8, 60.0, SetSubCategory.WorkSet), // 20kg bar + 40kg plates
                RestSet(restId2, 60),
                WeightSet(workSet2Id, 6, 80.0, SetSubCategory.WorkSet) // 20kg bar + 60kg plates
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
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createDumbbellsExercise(equipmentId: UUID): Exercise {
        val exerciseId = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()
        val restId = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Dumbbell Shoulder Press",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set1Id, 12, 20.0), // 2x10kg
                RestSet(restId, 60),
                WeightSet(set2Id, 10, 30.0) // 2x15kg
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 8,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createDumbbellExercise(equipmentId: UUID): Exercise {
        val exerciseId = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Single Dumbbell Row",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set1Id, 15, 10.0), // Single 10kg
                WeightSet(set2Id, 12, 15.0) // Single 15kg
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 10,
            maxReps = 20,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createPlateLoadedCableExercise(equipmentId: UUID): Exercise {
        val exerciseId = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()
        val restId = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Cable Fly",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set1Id, 12, 10.0), // 10kg plate
                RestSet(restId, 60),
                WeightSet(set2Id, 10, 15.0) // 10kg + 5kg plates
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 8,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createWeightVestExercise(equipmentId: UUID): Exercise {
        val exerciseId = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Weighted Pull-ups",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set1Id, 10, 10.0), // 10kg vest
                WeightSet(set2Id, 8, 15.0) // 15kg vest
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
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createMachineExercise(equipmentId: UUID): Exercise {
        val exerciseId = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()
        val restId = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Leg Press Machine",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set1Id, 15, 20.0), // 20kg base
                RestSet(restId, 60),
                WeightSet(set2Id, 12, 25.0) // 20kg base + 5kg extra
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 10,
            maxReps = 20,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createGenericExercise(equipmentId: UUID): Exercise {
        val exerciseId = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Generic Weight Exercise",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                WeightSet(set1Id, 12, 25.0), // Any valid weight
                WeightSet(set2Id, 10, 50.0) // Any valid weight
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 8,
            maxReps = 15,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createBodyWeightExercise(): Exercise {
        val exerciseId = UUID.randomUUID()
        val set1Id = UUID.randomUUID()
        val set2Id = UUID.randomUUID()
        val restId = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Push-ups",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                BodyWeightSet(set1Id, 15, 0.0), // Body weight only
                RestSet(restId, 60),
                BodyWeightSet(set2Id, 12, 10.0) // Body weight + 10kg
            ),
            exerciseType = ExerciseType.BODY_WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 10,
            maxReps = 20,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = 100.0, // 100% of body weight for push-ups
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createCountdownExercise(): Exercise {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Plank Hold",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                TimedDurationSet(setId, 60_000, autoStart = true, autoStop = true) // 60 seconds
            ),
            exerciseType = ExerciseType.COUNTDOWN,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createCountupExercise(): Exercise {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Running",
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(
                EnduranceSet(setId, 120_000, autoStart = false, autoStop = false) // 2 minutes
            ),
            exerciseType = ExerciseType.COUNTUP,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }

    private fun createDoNotStoreHistoryExercise(equipmentId: UUID): Exercise {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()

        return Exercise(
            id = exerciseId,
            enabled = true,
            name = "Warm-up Jog",
            doNotStoreHistory = true, // Should not appear in history
            notes = "",
            sets = listOf(
                WeightSet(setId, 5, 40.0)
            ),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 5,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null
        )
    }
}


