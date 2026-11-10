package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.WeeklyProgressOverride
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.util.UUID

class WorkoutStoreImportTest {
    @Test
    fun importPreservesLibraryAndLocalSettings() {
        val existingDefinition = definition("Existing")
        val importedDefinition = definition("Imported")
        val existing = store().copy(
            exerciseDefinitions = listOf(existingDefinition),
            heightCm = 180,
            sex = true,
            gender = 0,
            estimatedVo2MaxMlKgMin = 45.0,
            vo2MaxSource = "test",
            vo2MaxEstimatedAtEpochDay = 20000,
            weeklyProgressOverrides = listOf(WeeklyProgressOverride(LocalDate.of(2026, 11, 9))),
        )
        val imported = store().copy(exerciseDefinitions = listOf(importedDefinition))

        val merged = mergeWorkoutStore(existing, imported)

        assertEquals(
            existing.copy(exerciseDefinitions = listOf(existingDefinition, importedDefinition)),
            merged,
        )
    }

    @Test
    fun definitionConflictsFollowTheSelectedImportPolicyWithoutDuplicatingIdentity() {
        val existingDefinition = definition("Existing")
        val replacement = existingDefinition.copy(name = "Replacement")
        val existing = store().copy(exerciseDefinitions = listOf(existingDefinition))
        val imported = store().copy(exerciseDefinitions = listOf(replacement, replacement))

        for (policy in ConflictResolution.entries) {
            val expected = if (policy == ConflictResolution.REPLACE_EXISTING) {
                replacement
            } else {
                existingDefinition
            }
            assertEquals(listOf(expected), mergeWorkoutStore(existing, imported, policy).exerciseDefinitions)
        }
    }

    private fun definition(name: String) = ExerciseDefinition(
        id = UUID.randomUUID(),
        name = name,
        exerciseType = ExerciseType.WEIGHT,
    )

    private fun store() = WorkoutStore(
        birthDateYear = 1990,
        weightKg = 80.0,
        progressionPercentageAmount = 2.5,
    )
}
