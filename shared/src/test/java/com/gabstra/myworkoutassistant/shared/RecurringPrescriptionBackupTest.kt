package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.nio.file.Files
import java.time.LocalDate
import java.util.UUID

class RecurringPrescriptionBackupTest {

    @Test
    fun appBackupRoundTripAndStoreRestoreKeepRecurringPrescriptionData() {
        val planId = UUID.randomUUID()
        val sessionId = UUID.randomUUID()
        val carryTrackId = UUID.randomUUID()
        val prescribedTrackId = UUID.randomUUID()
        val plan = WorkoutPlan(
            id = planId,
            name = "Four week cycle",
            workoutIds = emptyList(),
            order = 0,
            suggestNextPrescription = false,
        )
        val carryExercise = exercise(
            id = UUID.randomUUID(),
            trackId = carryTrackId,
            policy = LoadHistoryPolicy.LAST_WORKING_LOAD,
            setId = UUID.randomUUID(),
            reps = 8,
            weight = 42.5,
            notes = "Keep the same tempo",
        )
        val prescribedExercise = exercise(
            id = UUID.randomUUID(),
            trackId = prescribedTrackId,
            policy = LoadHistoryPolicy.PRESCRIBED_WEIGHT,
            setId = UUID.randomUUID(),
            reps = 6,
            weight = 50.0,
            notes = "Coach specified load",
        )
        val legacyExercise = exercise(
            id = UUID.randomUUID(),
            trackId = null,
            policy = LoadHistoryPolicy.NONE,
            setId = UUID.randomUUID(),
            reps = 10,
            weight = 30.0,
            notes = "Legacy automatic behavior",
        )
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "Progression",
            description = "Prescribed week two",
            workoutComponents = listOf(
                carryExercise,
                prescribedExercise,
                legacyExercise,
                Rest(UUID.randomUUID(), enabled = true, timeInSeconds = 90),
            ),
            order = 1,
            creationDate = LocalDate.of(2026, 1, 1),
            globalId = UUID.randomUUID(),
            type = 0,
            workoutPlanId = planId,
            recurringSessionId = sessionId,
            prescriptionOrdinal = 2,
            prescriptionLabel = "Progression",
        )
        val originalStore = WorkoutStore(
            workouts = listOf(workout),
            workoutPlans = listOf(plan.copy(workoutIds = listOf(workout.id))),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.05,
        )
        val originalBackup = AppBackup(
            WorkoutStore = originalStore,
            WorkoutHistories = emptyList(),
            SetHistories = emptyList(),
            ExerciseInfos = emptyList(),
            WorkoutSchedules = emptyList(),
            WorkoutRecords = emptyList(),
            ExerciseSessionProgressions = emptyList(),
        )

        val decodedBackup = fromJSONtoAppBackup(fromAppBackupToJSON(originalBackup))
        val restoredStore = decodedBackup.WorkoutStore
        val directory = Files.createTempDirectory("recurring-prescription-backup").toFile()
        try {
            val repository = WorkoutStoreRepository(directory)
            repository.saveWorkoutStore(restoredStore)
            val restoredWorkoutStore = repository.getWorkoutStore()
            val restoredWorkout = restoredWorkoutStore.workouts.single()
            val restoredExercises = restoredWorkout.workoutComponents.filterIsInstance<Exercise>()

            assertEquals(sessionId, restoredWorkout.recurringSessionId)
            assertEquals(2, restoredWorkout.prescriptionOrdinal)
            assertEquals("Progression", restoredWorkout.prescriptionLabel)
            assertEquals(false, restoredWorkoutStore.workoutPlans.single().suggestNextPrescription)
            assertEquals(listOf(carryTrackId, prescribedTrackId, null), restoredExercises.map { it.recurringExerciseId })
            assertEquals(
                listOf(LoadHistoryPolicy.LAST_WORKING_LOAD, LoadHistoryPolicy.PRESCRIBED_WEIGHT, LoadHistoryPolicy.NONE),
                restoredExercises.map { it.loadHistoryPolicy },
            )
            assertEquals(listOf(8, 6, 10), restoredExercises.map { (it.sets.single() as WeightSet).reps })
            assertEquals(listOf(42.5, 50.0, 30.0), restoredExercises.map { (it.sets.single() as WeightSet).weight })
            assertEquals(
                listOf("Keep the same tempo", "Coach specified load", "Legacy automatic behavior"),
                restoredExercises.map { it.notes },
            )
            assertEquals(
                listOf("8 reps at 42.5 kg", "6 reps at 50.0 kg", "10 reps at 30.0 kg"),
                restoredExercises.map { (it.sets.single() as WeightSet).note },
            )
            assertEquals(90, (restoredWorkout.workoutComponents.filterIsInstance<Rest>().single()).timeInSeconds)
            assertNotEquals(restoredExercises[0].recurringExerciseId, restoredExercises[1].recurringExerciseId)
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun legacyBackupDefaultsSuggestionAndExercisePolicySafely() {
        val planId = UUID.randomUUID()
        val workoutId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val legacyJson = """
            {
              "WorkoutStore": {
                "workouts": [{
                  "id": "$workoutId", "name": "Legacy", "description": "",
                  "workoutComponents": [{
                    "type": "Exercise", "id": "$exerciseId", "enabled": true,
                    "name": "Press", "sets": [{"type":"WeightSet", "id":"$setId", "reps":8, "weight":40.0}],
                    "exerciseType": "WEIGHT", "minReps": 5, "maxReps": 8
                  }], "order": 0, "creationDate": "2026-01-01",
                  "globalId": "${UUID.randomUUID()}", "type": 0, "workoutPlanId": "$planId"
                }],
                "equipments": [], "accessoryEquipments": [],
                "workoutPlans": [{"id": "$planId", "name": "Plan", "workoutIds": ["$workoutId"], "order": 0}],
                "birthDateYear": 1990, "weightKg": 80.0, "progressionPercentageAmount": 0.05
              },
              "WorkoutHistories": [], "SetHistories": [], "ExerciseInfos": [],
              "WorkoutSchedules": [], "WorkoutRecords": [], "ExerciseSessionProgressions": []
            }
        """.trimIndent()

        val restored = fromJSONtoAppBackup(legacyJson).WorkoutStore

        assertEquals(true, restored.workoutPlans.single().suggestNextPrescription)
        assertNull(restored.workouts.single().recurringSessionId)
        assertNull(restored.workouts.single().prescriptionOrdinal)
        assertNull(restored.workouts.single().prescriptionLabel)
        val exercise = restored.workouts.single().workoutComponents.filterIsInstance<Exercise>().single()
        assertNull(exercise.recurringExerciseId)
        assertEquals(LoadHistoryPolicy.NONE, exercise.loadHistoryPolicy)
    }

    private fun exercise(
        id: UUID,
        trackId: UUID?,
        policy: LoadHistoryPolicy,
        setId: UUID,
        reps: Int,
        weight: Double,
        notes: String,
    ) = Exercise(
        id = id,
        enabled = true,
        name = "Press",
        notes = notes,
        sets = listOf(WeightSet(setId, reps, weight, SetSubCategory.WorkSet, note = "$reps reps at $weight kg")),
        exerciseType = ExerciseType.WEIGHT,
        minReps = reps,
        maxReps = reps,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        recurringExerciseId = trackId,
        loadHistoryPolicy = policy,
    )
}
