package com.gabstra.myworkoutassistant.shared

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import com.gabstra.myworkoutassistant.shared.equipments.CardioMachine
import com.gabstra.myworkoutassistant.shared.equipments.Generic
import com.gabstra.myworkoutassistant.shared.equipments.isCompatibleWith
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.LocalDate
import java.util.UUID

class WorkoutStoreAdapterTest {

    @Test
    fun linkedExerciseNameOverride_roundTripsAndSurvivesDefinitionRename() {
        val definition = ExerciseDefinition(
            id = UUID.randomUUID(),
            name = "Barbell bench press",
            exerciseType = ExerciseType.WEIGHT,
        )
        val prescription = legacyExercise(UUID.randomUUID(), UUID.randomUUID()).copy(
            name = "Heavy bench",
            exerciseDefinitionId = definition.id,
            nameOverride = "Heavy bench",
        )
        val store = storeWith(definition, prescription)

        val roundTripped = fromJSONToWorkoutStore(fromWorkoutStoreToJSON(store))
        val renamed = roundTripped.updateExerciseDefinition(definition.copy(name = "Bench press"))
        val renamedPrescription = renamed.allExercisePrescriptions().single()

        assertEquals("Heavy bench", renamedPrescription.nameOverride)
        assertEquals("Heavy bench", renamedPrescription.name)
        assertEquals("Heavy bench", renamed.resolveExercise(renamedPrescription).displayName)
    }

    @Test
    fun linkedExerciseWithoutNameOverride_followsDefinitionRename() {
        val definition = ExerciseDefinition(
            id = UUID.randomUUID(),
            name = "Barbell bench press",
            exerciseType = ExerciseType.WEIGHT,
        )
        val prescription = legacyExercise(UUID.randomUUID(), UUID.randomUUID()).copy(
            name = definition.name,
            exerciseDefinitionId = definition.id,
        )

        val renamed = storeWith(definition, prescription)
            .updateExerciseDefinition(definition.copy(name = "Bench press"))
        val renamedPrescription = renamed.allExercisePrescriptions().single()

        assertNull(renamedPrescription.nameOverride)
        assertEquals("Bench press", renamedPrescription.name)
        assertEquals("Bench press", renamed.resolveExercise(renamedPrescription).displayName)
    }

    @Test
    fun legacyExercises_migrateDeterministicallyAndIdempotently() {
        val prescriptionId = UUID.randomUUID()
        val supersetPrescriptionId = UUID.randomUUID()
        val equipmentId = UUID.randomUUID()
        val workout = Workout(
            id = UUID.randomUUID(), name = "A", description = "",
            workoutComponents = listOf(
                legacyExercise(prescriptionId, equipmentId),
                Superset(
                    id = UUID.randomUUID(), enabled = true,
                    exercises = listOf(legacyExercise(supersetPrescriptionId, equipmentId)),
                    restSecondsByExercise = mapOf(supersetPrescriptionId to 60),
                ),
            ),
            order = 0, creationDate = LocalDate.of(2025, 1, 1),
            globalId = UUID.randomUUID(), type = 0,
        )
        val legacy = WorkoutStore(
            schemaVersion = 1, workouts = listOf(workout), birthDateYear = 1990,
            weightKg = 80.0, progressionPercentageAmount = 0.05,
        )

        val first = fromJSONToWorkoutStore(fromWorkoutStoreToJSON(legacy))
        val second = fromJSONToWorkoutStore(fromWorkoutStoreToJSON(first))

        assertEquals(WorkoutStore.CURRENT_SCHEMA_VERSION, first.schemaVersion)
        assertEquals(1, first.exerciseDefinitions.size)
        assertTrue(first.exerciseDefinitions.all { it.exerciseFamilyId != null })
        assertEquals(first, second)
        assertEquals(listOf(prescriptionId, supersetPrescriptionId), first.allExercisePrescriptions().map { it.id })
        assertTrue(first.allExercisePrescriptions().all {
            it.exerciseDefinitionId == first.exerciseDefinitions.single().id &&
                it.placementNotes == "Shared instructions"
        })
    }

    @Test
    fun legacyExercises_keepEquipmentAndTypeVariationsSeparate() {
        val equipmentA = UUID.randomUUID()
        val workout = Workout(
            id = UUID.randomUUID(), name = "A", description = "",
            workoutComponents = listOf(
                legacyExercise(UUID.randomUUID(), equipmentA),
                legacyExercise(UUID.randomUUID(), UUID.randomUUID()),
                legacyExercise(UUID.randomUUID(), equipmentA).copy(exerciseType = ExerciseType.BODY_WEIGHT),
            ),
            order = 0, creationDate = LocalDate.of(2025, 1, 1),
            globalId = UUID.randomUUID(), type = 0,
        )
        val migrated = WorkoutStore(
            schemaVersion = 1, workouts = listOf(workout), birthDateYear = 1990,
            weightKg = 80.0, progressionPercentageAmount = 0.05,
        ).migrateExerciseLibrary()

        assertEquals(3, migrated.exerciseDefinitions.size)
        assertEquals(3, migrated.allExercisePrescriptions().mapNotNull { it.exerciseDefinitionId }.distinct().size)
        assertEquals(1, migrated.exerciseDefinitions.map { it.exerciseFamilyId }.distinct().size)
    }

    @Test
    fun familyMovement_isSharedAcrossWeightAndTimedVariations() {
        val familyId = UUID.randomUUID()
        val movement = ExerciseMovementRef.forWearSkeletonJson("bench", "{}")
        val weight = ExerciseDefinition(
            id = UUID.randomUUID(), exerciseFamilyId = familyId, name = "Bench press",
            exerciseType = ExerciseType.WEIGHT, movementRef = movement,
        )
        val timed = ExerciseDefinition(
            id = UUID.randomUUID(), exerciseFamilyId = familyId, name = "Bench press",
            exerciseType = ExerciseType.COUNTDOWN,
        )

        val normalized = listOf(weight, timed).normalizeExerciseFamilyMovements()

        assertEquals(setOf(ExerciseType.WEIGHT, ExerciseType.COUNTDOWN), normalized.map { it.exerciseType }.toSet())
        assertTrue(normalized.all { it.movementRef == movement })
    }

    @Test
    fun updatingFamilyMovement_propagatesToEveryVariationAndPrescription() {
        val familyId = UUID.randomUUID()
        val originalMovement = ExerciseMovementRef.forWearSkeletonJson("old", "old")
        val updatedMovement = ExerciseMovementRef.forWearSkeletonJson("new", "new")
        val weight = ExerciseDefinition(
            id = UUID.randomUUID(), exerciseFamilyId = familyId, name = "Bench press",
            exerciseType = ExerciseType.WEIGHT, movementRef = originalMovement,
        )
        val timed = ExerciseDefinition(
            id = UUID.randomUUID(), exerciseFamilyId = familyId, name = "Bench press",
            exerciseType = ExerciseType.COUNTDOWN, movementRef = originalMovement,
        )
        val prescription = legacyExercise(UUID.randomUUID(), UUID.randomUUID()).copy(
            exerciseDefinitionId = timed.id,
            movementRef = originalMovement,
        )
        val store = storeWith(timed, prescription).copy(exerciseDefinitions = listOf(weight, timed))

        val updated = store.updateExerciseDefinition(weight.copy(movementRef = updatedMovement))

        assertTrue(updated.exerciseDefinitions.all { it.movementRef == updatedMovement })
        assertEquals(updatedMovement, updated.allExercisePrescriptions().single().movementRef)
    }

    private fun legacyExercise(id: UUID, equipmentId: UUID) = Exercise(
        id = id, enabled = true, name = "Bench press", notes = "Shared instructions",
        sets = emptyList(), exerciseType = ExerciseType.WEIGHT, minReps = 5, maxReps = 8,
        lowerBoundMaxHRPercent = null, upperBoundMaxHRPercent = null,
        equipmentId = equipmentId, bodyWeightPercentage = null,
    )

    private fun storeWith(definition: ExerciseDefinition, prescription: Exercise): WorkoutStore =
        WorkoutStore(
            workouts = listOf(
                Workout(
                    id = UUID.randomUUID(), name = "A", description = "",
                    workoutComponents = listOf(prescription), order = 0,
                    creationDate = LocalDate.of(2025, 1, 1),
                    globalId = UUID.randomUUID(), type = 0,
                )
            ),
            exerciseDefinitions = listOf(definition),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.05,
        )

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

    @Test
    fun exerciseLibraryPackage_isDetectedAndParsedWithoutPrescriptions() {
        val definitionId = UUID.randomUUID()
        val json = """
            {
              "format": "$EXERCISE_LIBRARY_PACKAGE_FORMAT",
              "schemaVersion": 2,
              "exerciseDefinitions": [{
                "id": "$definitionId",
                "name": "Push-Up",
                "instructions": "Keep the trunk braced.",
                "exerciseType": "BODY_WEIGHT",
                "equipmentId": null,
                "bodyWeightPercentage": 100.0,
                "muscleGroups": ["FRONT_CHEST"],
                "secondaryMuscleGroups": ["FRONT_TRICEPS"],
                "requiredAccessoryEquipmentIds": [],
                "exerciseCategory": "MODERATE_COMPOUND"
              }],
              "exerciseMovements": [],
              "equipments": [],
              "accessoryEquipments": []
            }
        """.trimIndent()

        assertEquals(BackupFileType.EXERCISE_LIBRARY_PACKAGE, detectBackupFileType(json))
        val parsed = fromJSONToExerciseLibraryPackage(json)
        assertEquals(EXERCISE_LIBRARY_PACKAGE_FORMAT, parsed.format)
        assertEquals(definitionId, parsed.exerciseDefinitions.single().id)
        assertEquals("Push-Up", parsed.exerciseDefinitions.single().name)
    }

    @Test
    fun cardioMachine_isParsedAndOnlyCompatibleWithTimedExercises() {
        val equipmentId = UUID.randomUUID()
        val json = """
            {
              "format": "$EXERCISE_LIBRARY_PACKAGE_FORMAT",
              "schemaVersion": 2,
              "exerciseDefinitions": [],
              "exerciseMovements": [],
              "equipments": [{
                "id": "$equipmentId",
                "type": "CARDIO_MACHINE",
                "name": "Spin Bike"
              }],
              "accessoryEquipments": []
            }
        """.trimIndent()

        val cardioMachine = fromJSONToExerciseLibraryPackage(json).equipments.single()

        assertTrue(cardioMachine is CardioMachine)
        assertTrue(cardioMachine.isCompatibleWith(ExerciseType.COUNTUP))
        assertTrue(cardioMachine.isCompatibleWith(ExerciseType.COUNTDOWN))
        assertTrue(!cardioMachine.isCompatibleWith(ExerciseType.WEIGHT))
        assertTrue(!cardioMachine.isCompatibleWith(ExerciseType.BODY_WEIGHT))

        val weightedEquipment = Generic(UUID.randomUUID(), "Generic")
        assertTrue(weightedEquipment.isCompatibleWith(ExerciseType.WEIGHT))
        assertTrue(weightedEquipment.isCompatibleWith(ExerciseType.BODY_WEIGHT))
        assertTrue(!weightedEquipment.isCompatibleWith(ExerciseType.COUNTUP))
    }
}
