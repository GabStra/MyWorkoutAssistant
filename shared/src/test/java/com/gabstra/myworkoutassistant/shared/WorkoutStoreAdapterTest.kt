package com.gabstra.myworkoutassistant.shared

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class WorkoutStoreAdapterTest {

    @Test
    fun missingWeeklyProgressOverrides_defaultsToEmptyList() {
        val workoutStore = fromJSONToWorkoutStore(
            """
            {
              "workouts": [],
              "equipments": [],
              "accessoryEquipments": [],
              "workoutPlans": [],
              "birthDateYear": 1990,
              "weightKg": 82.5,
              "progressionPercentageAmount": 0.1
            }
            """.trimIndent()
        )

        assertTrue(workoutStore.weeklyProgressOverrides.isEmpty())
        assertEquals(2, workoutStore.deloadConfig.failedSessionsThreshold)
        assertEquals(null, workoutStore.deloadConfig.completedSessionsInterval)
        assertEquals(0.9, workoutStore.deloadConfig.weightFactor, 0.0)
        assertEquals(2, workoutStore.deloadConfig.repsDrop)
        assertEquals(null, workoutStore.deloadConfig.cutSetsTo)
    }

    @Test
    fun weeklyProgressOverrides_roundTripThroughWorkoutStoreJson() {
        val overrideA = WeeklyProgressOverride(
            weekStart = LocalDate.of(2025, 3, 3),
            includedWorkoutGlobalIds = listOf(UUID.randomUUID(), UUID.randomUUID())
        )
        val overrideB = WeeklyProgressOverride(
            weekStart = LocalDate.of(2025, 3, 10),
            includedWorkoutGlobalIds = emptyList()
        )
        val original = WorkoutStore(
            workouts = emptyList(),
            equipments = emptyList(),
            accessoryEquipments = emptyList(),
            workoutPlans = emptyList(),
            weeklyProgressOverrides = listOf(overrideA, overrideB),
            birthDateYear = 1990,
            weightKg = 82.5,
            progressionPercentageAmount = 0.1
        )

        val roundTripped = fromJSONToWorkoutStore(fromWorkoutStoreToJSON(original))

        assertEquals(listOf(overrideA, overrideB), roundTripped.weeklyProgressOverrides)
    }

    @Test
    fun deloadConfigAndExerciseOverrides_roundTripThroughWorkoutStoreJson() {
        val exercise = com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Bench",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 6,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = UUID.randomUUID(),
            bodyWeightPercentage = null,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            deloadFailedSessionsThreshold = 4,
            deloadCompletedSessionsInterval = 8,
            deloadWeightFactor = 0.85,
            deloadRepsDrop = 3,
            deloadCutSetsTo = 2
        )
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "Push",
            description = "",
            workoutComponents = listOf(exercise),
            order = 0,
            creationDate = LocalDate.of(2025, 1, 1),
            globalId = UUID.randomUUID(),
            type = 0
        )
        val original = WorkoutStore(
            workouts = listOf(workout),
            equipments = emptyList(),
            accessoryEquipments = emptyList(),
            workoutPlans = emptyList(),
            birthDateYear = 1990,
            weightKg = 82.5,
            progressionPercentageAmount = 0.1,
            deloadConfig = DeloadConfig(
                failedSessionsThreshold = 3,
                completedSessionsInterval = 6,
                weightFactor = 0.88,
                repsDrop = 2,
                cutSetsTo = 3
            )
        )

        val roundTripped = fromJSONToWorkoutStore(fromWorkoutStoreToJSON(original))
        val roundTrippedExercise = roundTripped.workouts.single().workoutComponents
            .single() as com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

        assertEquals(original.deloadConfig, roundTripped.deloadConfig)
        assertEquals(4, roundTrippedExercise.deloadFailedSessionsThreshold)
        assertEquals(8, roundTrippedExercise.deloadCompletedSessionsInterval)
        assertEquals(0.85, roundTrippedExercise.deloadWeightFactor ?: 0.0, 0.0)
        assertEquals(3, roundTrippedExercise.deloadRepsDrop)
        assertEquals(2, roundTrippedExercise.deloadCutSetsTo)
    }

    @Test
    fun workoutPlanPackage_roundTripsThroughJson() {
        val original = WorkoutPlanPackage(
            name = "Push Pull Legs",
            workouts = emptyList(),
            equipments = emptyList(),
            accessoryEquipments = emptyList()
        )

        val roundTripped = fromJSONToWorkoutPlanPackage(fromWorkoutPlanPackageToJSON(original))

        assertEquals(original, roundTripped)
    }

    @Test
    fun detectBackupFileType_identifiesWorkoutPlanPackage() {
        val json = """
            {
              "name": "Push Pull Legs",
              "workouts": [],
              "equipments": [],
              "accessoryEquipments": []
            }
        """.trimIndent()

        assertEquals(BackupFileType.WORKOUT_PLAN_PACKAGE, detectBackupFileType(json))
    }

    @Test
    fun detectBackupFileType_identifiesIncrementalBackupArchive() {
        val json = """
            {
              "format": "$APP_BACKUP_ARCHIVE_FORMAT",
              "formatVersion": 1,
              "baseBackup": {},
              "baseHash": "abc",
              "createdAt": "2026-04-17T12:00:00",
              "lastCompactedAt": "2026-04-17T12:00:00",
              "deltas": []
            }
        """.trimIndent()

        assertEquals(BackupFileType.INCREMENTAL_APP_BACKUP, detectBackupFileType(json))
    }
}
