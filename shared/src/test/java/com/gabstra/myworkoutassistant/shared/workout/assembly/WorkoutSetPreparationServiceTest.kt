package com.gabstra.myworkoutassistant.shared.workout.assembly

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ExerciseCategory
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.session.withLastWorkingLoads
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import java.time.LocalDateTime
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class WorkoutSetPreparationServiceTest {

    @Test
    fun `last load is materialized before warmup and plate targets are calculated`() {
        val equipment = Machine(
            id = UUID.randomUUID(), name = "Machine",
            availableWeights = listOf(20.0, 30.0, 40.0, 55.0).map(::BaseWeight)
        )
        val setId = UUID.randomUUID()
        val exercise = Exercise(
            id = UUID.randomUUID(), enabled = true, name = "Recurring press", notes = "",
            sets = listOf(WeightSet(setId, reps = 9, weight = 40.0, note = "Keep controlled")),
            exerciseType = ExerciseType.WEIGHT, minReps = 6, maxReps = 12,
            lowerBoundMaxHRPercent = null, upperBoundMaxHRPercent = null,
            equipmentId = equipment.id, bodyWeightPercentage = null,
            generateWarmUpSets = true,
        )
        val history = SetHistory(
            id = UUID.randomUUID(), setId = UUID.randomUUID(), order = 0u,
            startTime = LocalDateTime.now(), endTime = LocalDateTime.now(),
            setData = WeightSetData(actualReps = 8, actualWeight = 55.0, volume = 440.0), skipped = false,
        )
        val materialized = exercise.withLastWorkingLoads(mapOf(setId to history))
        val prepared = WorkoutSetPreparationService().prepareExerciseSets(
            exercise = materialized, priorExercises = emptyList(), equipment = equipment,
            bodyWeightKg = 70.0, getAvailableTotals = { it.getWeightsCombinationsNoExtra() },
        )
        val workSet = prepared.filterIsInstance<WeightSet>().single { it.id == setId }
        val warmups = prepared.filterIsInstance<WeightSet>().filter { it.id != setId && it.subCategory == SetSubCategory.WarmupSet }
        val platePlan = PlateCalculator.calculatePlateChanges(
            availablePlates = listOf(5.0, 5.0),
            sets = listOf(workSet.weight),
            barWeight = 45.0,
        )

        assertEquals(55.0, workSet.weight, 0.0)
        assertEquals(9, workSet.reps)
        assertEquals("Keep controlled", workSet.note)
        assertTrue("The fixture must generate warmups from the carried target", warmups.isNotEmpty())
        assertTrue(warmups.all { it.weight < workSet.weight })
        assertEquals(55.0, platePlan.last().change.to, 0.0)
    }

    @Test
    fun `auto regulation exercise keeps calibration before progression takes over`() {
        val equipment = Machine(
            id = UUID.randomUUID(),
            name = "Machine",
            availableWeights = listOf(BaseWeight(20.0), BaseWeight(25.0))
        )
        val workSet = WeightSet(
            id = UUID.randomUUID(),
            reps = 10,
            weight = 20.0,
            subCategory = SetSubCategory.CalibrationPendingSet
        )
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Calibration press",
            notes = "",
            sets = listOf(workSet),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 8,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            progressionMode = ProgressionMode.AUTO_REGULATION,
            requiresLoadCalibration = true
        )

        val preparedSets = WorkoutSetPreparationService().prepareExerciseSets(
            exercise = exercise,
            priorExercises = emptyList(),
            equipment = equipment,
            bodyWeightKg = 70.0,
            getAvailableTotals = { it.getWeightsCombinationsNoExtra() }
        )

        assertEquals(2, preparedSets.size)
        assertTrue(
            preparedSets.first() is WeightSet &&
                (preparedSets.first() as WeightSet).subCategory == SetSubCategory.CalibrationSet
        )
        assertEquals(workSet, preparedSets.last())
    }

    @Test
    fun `prescribed weight keeps fixed target and warmups while bypassing calibration`() {
        val equipment = Machine(
            id = UUID.randomUUID(),
            name = "Machine",
            availableWeights = listOf(20.0, 25.0, 30.0).map(::BaseWeight),
        )
        val target = WeightSet(UUID.randomUUID(), reps = 9, weight = 30.0, note = "Week 3 fixed target")
        val exercise = Exercise(
            id = UUID.randomUUID(), enabled = true, name = "Fixed press", notes = "",
            sets = listOf(target), exerciseType = ExerciseType.WEIGHT, minReps = 8, maxReps = 12,
            lowerBoundMaxHRPercent = null, upperBoundMaxHRPercent = null,
            equipmentId = equipment.id, bodyWeightPercentage = null,
            generateWarmUpSets = true, progressionMode = ProgressionMode.AUTO_REGULATION,
            requiresLoadCalibration = true, loadHistoryPolicy = LoadHistoryPolicy.PRESCRIBED_WEIGHT,
        )

        val prepared = WorkoutSetPreparationService().prepareExerciseSets(
            exercise = exercise, priorExercises = emptyList(), equipment = equipment,
            bodyWeightKg = 70.0, getAvailableTotals = { it.getWeightsCombinationsNoExtra() },
        )

        assertTrue(prepared.filterIsInstance<WeightSet>().any { it.subCategory == SetSubCategory.WarmupSet })
        assertEquals(target, prepared.filterIsInstance<WeightSet>().single { it.id == target.id })
        assertTrue(prepared.filterIsInstance<WeightSet>().none { it.subCategory == SetSubCategory.CalibrationSet })
    }

    @Test
    fun `generated warmup sets inherit prescribed no history reapply policy`() {
        val equipment = Machine(
            id = UUID.randomUUID(),
            name = "Machine",
            availableWeights = listOf(20.0, 40.0, 60.0, 80.0).map(::BaseWeight)
        )
        val workSet = WeightSet(
            id = UUID.randomUUID(),
            reps = 8,
            weight = 80.0,
            shouldReapplyHistoryToSet = false
        )
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Prescribed press",
            notes = "",
            sets = listOf(workSet),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 8,
            maxReps = 8,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = true,
            requiresLoadCalibration = false,
            exerciseCategory = ExerciseCategory.HEAVY_COMPOUND
        )

        val preparedSets = WorkoutSetPreparationService().prepareExerciseSets(
            exercise = exercise,
            priorExercises = emptyList(),
            equipment = equipment,
            bodyWeightKg = 70.0,
            getAvailableTotals = { it.getWeightsCombinationsNoExtra() }
        )
        val warmups = preparedSets.filterIsInstance<WeightSet>()
            .filter { it.subCategory == SetSubCategory.WarmupSet }

        assertTrue("The fixture must generate a warm-up set", warmups.isNotEmpty())
        assertTrue(warmups.all { !it.shouldReapplyHistoryToSet })
    }

    @Test
    fun `stored warmup policy does not override working set history policy`() {
        val equipment = Machine(
            id = UUID.randomUUID(),
            name = "Machine",
            availableWeights = listOf(20.0, 40.0, 60.0, 80.0).map(::BaseWeight)
        )
        val storedWarmup = WeightSet(
            id = UUID.randomUUID(), reps = 8, weight = 40.0,
            subCategory = SetSubCategory.WarmupSet,
            shouldReapplyHistoryToSet = true
        )
        val workSet = WeightSet(
            id = UUID.randomUUID(), reps = 8, weight = 80.0,
            shouldReapplyHistoryToSet = false
        )
        val exercise = Exercise(
            id = UUID.randomUUID(), enabled = true, name = "Prescribed press", notes = "",
            sets = listOf(storedWarmup, workSet), exerciseType = ExerciseType.WEIGHT,
            minReps = 8, maxReps = 8, lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null, equipmentId = equipment.id,
            bodyWeightPercentage = null, generateWarmUpSets = true,
            requiresLoadCalibration = false, exerciseCategory = ExerciseCategory.HEAVY_COMPOUND
        )

        val preparedSets = WorkoutSetPreparationService().prepareExerciseSets(
            exercise = exercise, priorExercises = emptyList(), equipment = equipment,
            bodyWeightKg = 70.0, getAvailableTotals = { it.getWeightsCombinationsNoExtra() }
        )
        val generatedWarmups = preparedSets.filterIsInstance<WeightSet>()
            .filter { it.id !in setOf(storedWarmup.id, workSet.id) && it.subCategory == SetSubCategory.WarmupSet }

        assertTrue("The fixture must generate a warm-up set", generatedWarmups.isNotEmpty())
        assertTrue(generatedWarmups.all { !it.shouldReapplyHistoryToSet })
    }

    @Test
    fun `generated warmups retain legacy history reapply default when work set flag is absent`() {
        val equipment = Machine(
            id = UUID.randomUUID(),
            name = "Machine",
            availableWeights = listOf(BaseWeight(20.0), BaseWeight(40.0), BaseWeight(60.0), BaseWeight(80.0))
        )
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Reviewed press",
            notes = "",
            sets = listOf(WeightSet(UUID.randomUUID(), reps = 8, weight = 80.0)),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 8,
            maxReps = 8,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipment.id,
            bodyWeightPercentage = null,
            generateWarmUpSets = true,
            requiresLoadCalibration = false,
            exerciseCategory = ExerciseCategory.HEAVY_COMPOUND
        )

        val preparedSets = WorkoutSetPreparationService().prepareExerciseSets(
            exercise = exercise,
            priorExercises = emptyList(),
            equipment = equipment,
            bodyWeightKg = 70.0,
            getAvailableTotals = { it.getWeightsCombinationsNoExtra() }
        )
        val warmups = preparedSets.filterIsInstance<WeightSet>()
            .filter { it.subCategory == SetSubCategory.WarmupSet }

        assertTrue("The fixture must generate a warm-up set", warmups.isNotEmpty())
        assertTrue(warmups.all { it.shouldReapplyHistoryToSet })
    }
}
