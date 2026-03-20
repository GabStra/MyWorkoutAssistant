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
}
