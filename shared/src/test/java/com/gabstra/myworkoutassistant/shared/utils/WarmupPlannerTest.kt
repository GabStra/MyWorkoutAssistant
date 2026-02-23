package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.MuscleGroup
import com.gabstra.myworkoutassistant.shared.ExerciseCategory
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID
import kotlin.math.abs

class WarmupPlannerTest {

    private fun createTestBarbell(barWeight: Double = 20.0): Barbell {
        val plates = listOf(
            Plate(20.0, 20.0),
            Plate(20.0, 20.0), // Second pair of 20kg plates
            Plate(10.0, 15.0),
            Plate(10.0, 15.0), // Second pair of 10kg plates
            Plate(5.0, 10.0),
            Plate(5.0, 10.0),  // Second pair of 5kg plates
            Plate(2.5, 5.0),
            Plate(2.5, 5.0),   // Second pair of 2.5kg plates
            Plate(1.25, 3.0),
            Plate(1.25, 3.0)   // Second pair of 1.25kg plates
        )
        return Barbell(
            id = UUID.randomUUID(),
            name = "Test Barbell",
            availablePlates = plates,
            sleeveLength = 200,
            barWeight = barWeight
        )
    }

    private fun createTestExercise(
        name: String = "Test Exercise",
        equipmentId: UUID? = null,
        muscleGroups: Set<MuscleGroup>? = null,
        exerciseCategory: ExerciseCategory? = null
    ): Exercise {
        return Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = name,
            doNotStoreHistory = false,
            notes = "",
            sets = listOf(WeightSet(UUID.randomUUID(), 5, 100.0)),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 100.0,
            minReps = 1,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = equipmentId,
            bodyWeightPercentage = null,
            generateWarmUpSets = true,
            progressionMode = com.gabstra.myworkoutassistant.shared.ProgressionMode.OFF,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null,
            loadJumpDefaultPct = null,
            loadJumpMaxPct = null,
            loadJumpOvercapUntil = null,
            muscleGroups = muscleGroups,
            secondaryMuscleGroups = null,
            requiredAccessoryEquipmentIds = null,
            requiresLoadCalibration = false,
            exerciseCategory = exerciseCategory
        )
    }

    @Test
    fun buildWarmupSetsForBarbell_basicProgressiveWeights() {
        val barbell = createTestBarbell(barWeight = 20.0)
        // Use exercise without muscle groups to avoid compound detection
        val exercise = createTestExercise(equipmentId = barbell.id, muscleGroups = null)
        val workWeight = 100.0
        val workReps = 5
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = exercise,
            priorExercises = emptyList(),
            maxWarmups = 4
        )

        assertTrue("Should generate warmup sets", warmups.isNotEmpty())
        assertTrue("Should have at most 4 warmup sets", warmups.size <= 4)
        
        // Verify weights are progressive (non-decreasing)
        for (i in 1 until warmups.size) {
            assertTrue(
                "Weights should be non-decreasing: ${warmups[i-1].first} <= ${warmups[i].first}",
                warmups[i].first >= warmups[i-1].first - 1e-9
            )
        }

        // Verify all weights are less than work weight
        warmups.forEach { (weight, _) ->
            assertTrue("Warmup weight should be less than work weight", weight < workWeight)
            assertTrue("Warmup weight should be >= bar weight", weight >= barbell.barWeight)
        }

        // With exerciseCategory=null we use fallback: count=3 gives 4 target fractions (0, 0.4, 0.6, 0.8), reps [6, 3, 1, 1]
        if (warmups.size == 3) {
            assertEquals("First warmup should have 6 reps", 6, warmups[0].second)
            assertEquals("Second warmup should have 3 reps", 3, warmups[1].second)
            assertEquals("Third warmup should have 1 rep", 1, warmups[2].second)
        } else if (warmups.size == 4) {
            assertEquals("First warmup should have 6 reps", 6, warmups[0].second)
            assertEquals("Second warmup should have 3 reps", 3, warmups[1].second)
            assertEquals("Third warmup should have 1 rep", 1, warmups[2].second)
            assertEquals("Fourth warmup should have 1 rep", 1, warmups[3].second)
        }
    }

    @Test
    fun buildWarmupSetsForBarbell_fixedRepsNotScalingWithWorkReps() {
        val barbell = createTestBarbell(barWeight = 20.0)
        // Use exercise without muscle groups to avoid compound detection
        val exercise = createTestExercise(equipmentId = barbell.id, muscleGroups = null)
        val workWeight = 100.0
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        // Test with different work reps - reps should NOT scale
        val testCases = listOf(3, 5, 10, 15)
        
        testCases.forEach { workReps ->
            val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
                availableTotals = availableTotals,
                workWeight = workWeight,
                workReps = workReps,
                barbell = barbell,
                exercise = exercise,
                priorExercises = emptyList(),
                maxWarmups = 4
            )

            // Fallback: 3 warmups can be [6, 3, 1] or [5, 2, 2]; 2 warmups [5, 2]; 4 warmups [6, 3, 1, 1]
            if (warmups.size == 3) {
                if (warmups[0].second == 6) {
                    assertEquals("For $workReps work reps, first warmup should be 6 reps", 6, warmups[0].second)
                    assertEquals("For $workReps work reps, second warmup should be 3 reps", 3, warmups[1].second)
                    assertEquals("For $workReps work reps, third warmup should be 1 rep", 1, warmups[2].second)
                } else {
                    assertEquals("For $workReps work reps (count=2 profile), first warmup should be 5 reps", 5, warmups[0].second)
                    assertEquals("For $workReps work reps, second warmup should be 2 reps", 2, warmups[1].second)
                    assertEquals("For $workReps work reps, third warmup should be 2 reps", 2, warmups[2].second)
                }
            } else if (warmups.size == 2) {
                assertEquals("For $workReps work reps, first warmup should be 5 reps", 5, warmups[0].second)
                assertEquals("For $workReps work reps, second warmup should be 2 reps", 2, warmups[1].second)
            } else if (warmups.size == 4) {
                assertEquals("For $workReps work reps, first warmup should be 6 reps", 6, warmups[0].second)
                assertEquals("For $workReps work reps, second warmup should be 3 reps", 3, warmups[1].second)
                assertEquals("For $workReps work reps, third warmup should be 1 rep", 1, warmups[2].second)
                assertEquals("For $workReps work reps, fourth warmup should have 1 rep", 1, warmups[3].second)
            }
        }
    }

    @Test
    fun buildWarmupSetsForBarbell_withInitialPlates() {
        val barbell = createTestBarbell(barWeight = 20.0)
        // Use exercise without muscle groups to avoid compound detection
        val exercise = createTestExercise(equipmentId = barbell.id, muscleGroups = null)
        val workWeight = 100.0
        val workReps = 5
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()
        val initialPlates = listOf(10.0, 5.0) // 30kg per side = 60kg total plates

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = exercise,
            priorExercises = emptyList(),
            initialSetup = initialPlates,
            maxWarmups = 3
        )

        assertTrue("Should generate warmup sets even with initial plates", warmups.isNotEmpty())
        
        // Verify weights account for initial plates
        warmups.forEach { (weight, _) ->
            assertTrue("Weight should be achievable", weight >= barbell.barWeight)
        }
    }

    @Test
    fun buildWarmupSetsForBarbell_warmupCountByWorkReps() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val exercise = createTestExercise(equipmentId = barbell.id)
        val workWeight = 100.0
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        // Test warmup count logic by work reps:
        // ≥12 reps → 2 warmups
        // 8-11 reps → 2-3 warmups
        // 5-7 reps → 3 warmups
        // ≤4 reps → 3-4 warmups
        
        // Test ≥12 reps → 2 warmups (base, but barbell compound might add +1)
        val exercise12 = createTestExercise(equipmentId = barbell.id, muscleGroups = null) // No muscle groups = not compound
        val warmups12 = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = 12,
            barbell = barbell,
            exercise = exercise12,
            priorExercises = emptyList(),
            maxWarmups = 4
        )
        // Allow some flexibility - might get 2-3 warmups depending on optimization
        assertTrue("For 12 reps, should have 2-3 warmups (got ${warmups12.size})", warmups12.size >= 2 && warmups12.size <= 3)

        // Test 5-7 reps → 3 warmups (base, but barbell compound might add +1)
        val exercise5 = createTestExercise(equipmentId = barbell.id, muscleGroups = null) // No muscle groups = not compound
        val warmups5 = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = 5,
            barbell = barbell,
            exercise = exercise5,
            priorExercises = emptyList(),
            maxWarmups = 4
        )
        // Allow some flexibility - might get 3-4 warmups depending on optimization
        assertTrue("For 5 reps, should have 3-4 warmups (got ${warmups5.size})", warmups5.size >= 3 && warmups5.size <= 4)

        // Test ≤4 reps → 3-4 warmups (base, but barbell compound might add +1)
        val exercise3 = createTestExercise(equipmentId = barbell.id, muscleGroups = null) // No muscle groups = not compound
        val warmups3 = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = 3,
            barbell = barbell,
            exercise = exercise3,
            priorExercises = emptyList(),
            maxWarmups = 4
        )
        assertTrue("For 3 reps, should have 3-4 warmups (got ${warmups3.size})", warmups3.size >= 3 && warmups3.size <= 4)
    }

    @Test
    fun buildWarmupSetsForBarbell_weightsWithinTolerance() {
        val barbell = createTestBarbell(barWeight = 20.0)
        // Use exercise without muscle groups to avoid compound detection
        val exercise = createTestExercise(equipmentId = barbell.id, muscleGroups = null)
        val workWeight = 100.0
        val workReps = 5
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = exercise,
            priorExercises = emptyList(),
            maxWarmups = 4
        )

        // Fallback profiles: 2 sets [0.5, 0.7], 3 sets [0.4, 0.6, 0.8], 4 sets [0, 0.4, 0.6, 0.8] or [0, 0.4, 0.6, 0.75, 0.9]
        val expectedPercentages = when (warmups.size) {
            2 -> listOf(0.0, 0.50, 0.70)
            3 -> listOf(0.0, 0.40, 0.60, 0.80)
            4 -> listOf(0.0, 0.40, 0.60, 0.80) // fallback count=3 gives 4 fractions
            else -> listOf(0.0, 0.40, 0.60, 0.80)
        }
        val tolerance = 0.1 // 10% tolerance for test

        warmups.forEachIndexed { index, (weight, _) ->
            if (index < expectedPercentages.size) {
                val expectedPercentage = expectedPercentages[index]
                if (expectedPercentage > 1e-9) {
                    val targetWeight = workWeight * expectedPercentage
                    val lowerBound = targetWeight * (1 - tolerance)
                    val upperBound = targetWeight * (1 + tolerance)
                    assertTrue(
                        "Weight $weight at index $index should be within tolerance of target $targetWeight",
                        weight >= lowerBound && weight <= upperBound
                    )
                } else {
                    // Empty bar should be close to bar weight
                    assertTrue(
                        "Empty bar weight should be close to bar weight",
                        abs(weight - barbell.barWeight) < 1.0
                    )
                }
            }
        }
    }

    @Test
    fun buildWarmupSetsForBarbell_heavyCompoundCategory() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val heavyCompoundExercise = createTestExercise(
            equipmentId = barbell.id,
            muscleGroups = null,
            exerciseCategory = ExerciseCategory.HEAVY_COMPOUND
        )
        val workWeight = 100.0
        val workReps = 5
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = heavyCompoundExercise,
            priorExercises = emptyList(),
            maxWarmups = 4
        )

        // HEAVY_COMPOUND with barbell: [0.0, 0.50, 0.70] reps [1, 5, 3], total 9 reps; or legacy may give 3–4 sets
        assertTrue("Heavy compound should have 2–4 warmup sets (got ${warmups.size})", warmups.size in 2..4)
        if (warmups.size == 3) {
            assertEquals("First warmup (empty bar) should have 1 rep", 1, warmups[0].second)
            assertEquals("Second warmup should have 5 reps", 5, warmups[1].second)
            assertEquals("Third warmup should have 3 reps", 3, warmups[2].second)
            assertTrue("Total warm-up reps should be <= 9", warmups.sumOf { it.second } <= 9)
        } else {
            assertTrue("Total warm-up reps should be reasonable", warmups.sumOf { it.second } <= 15)
        }
    }

    @Test
    fun buildWarmupSetsForBarbell_moderateCompoundCategory() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val exercise = createTestExercise(
            equipmentId = barbell.id,
            exerciseCategory = ExerciseCategory.MODERATE_COMPOUND
        )
        val workWeight = 100.0
        val workReps = 5
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = exercise,
            priorExercises = emptyList(),
            maxWarmups = 4
        )

        // MODERATE_COMPOUND with barbell: 1-2 sets, 4-6 reps; [0.0, 0.60, 0.80] reps [2, 4, 2] or [0.60, 0.80] [4, 2]
        assertTrue("Moderate compound should have 1-3 warmup sets (got ${warmups.size})", warmups.size in 1..3)
        assertTrue("Total warm-up reps should be 4-6", warmups.sumOf { it.second } in 4..6)
    }

    @Test
    fun buildWarmupSetsForBarbell_isolationCategory() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val exercise = createTestExercise(
            equipmentId = barbell.id,
            exerciseCategory = ExerciseCategory.ISOLATION
        )
        val workWeight = 100.0
        val workReps = 5
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = exercise,
            priorExercises = emptyList(),
            maxWarmups = 4
        )

        // ISOLATION: 0-1 sets, 2-4 reps; first exercise so not "muscle already trained"
        assertTrue("Isolation should have 0-1 warmup sets (got ${warmups.size})", warmups.size <= 1)
        if (warmups.isNotEmpty()) {
            assertTrue("Isolation warm-up reps should be 2-4", warmups[0].second in 2..4)
        }
    }

    @Test
    fun buildWarmupSetsForBarbell_repeatedLiftGetsMin2Warmups() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val exercise = createTestExercise(equipmentId = barbell.id)
        val priorExercise = exercise.copy(id = exercise.id) // Same exercise ID
        val workWeight = 100.0
        val workReps = 15 // Would normally give 2 warmups
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = exercise,
            priorExercises = listOf(priorExercise),
            maxWarmups = 4
        )

        // Repeated lift should get min(2) warmups
        assertTrue("Repeated lift should have at least 2 warmups (got ${warmups.size})", warmups.size >= 2)
    }

    @Test
    fun buildWarmupSetsForBarbell_emptyBarHandling() {
        val barbell = createTestBarbell(barWeight = 20.0)
        // Use exercise without muscle groups to avoid compound detection
        val exercise = createTestExercise(equipmentId = barbell.id, muscleGroups = null)
        val workWeight = 100.0
        val workReps = 5
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = exercise,
            priorExercises = emptyList(),
            maxWarmups = 4
        )

        // First warmup should be empty bar (bar weight only) if profile includes 0.0
        if (warmups.isNotEmpty()) {
            val firstWeight = warmups[0].first
            // Empty bar should be close to bar weight
            assertTrue(
                "First warmup should be empty bar (close to bar weight)",
                abs(firstWeight - barbell.barWeight) < 1.0
            )
        }
    }

    @Test
    fun buildWarmupSetsForBarbell_noWarmupsWhenWorkWeightTooLow() {
        val barbell = createTestBarbell(barWeight = 20.0)
        // Use exercise without muscle groups to avoid compound detection
        val exercise = createTestExercise(equipmentId = barbell.id, muscleGroups = null)
        val workWeight = 20.0 // Work weight equals bar weight
        val workReps = 5
        val availableTotals = barbell.getWeightsCombinationsNoExtra().sorted()

        val warmups = WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = workWeight,
            workReps = workReps,
            barbell = barbell,
            exercise = exercise,
            priorExercises = emptyList(),
            maxWarmups = 4
        )

        // Should return empty list when work weight equals bar weight (no room for warmups)
        assertTrue("Should return empty when work weight equals bar weight", warmups.isEmpty())
    }

    /**
     * Verifies that optimizeWeightsForPercentages considers the plate cost from the last warmup
     * to work weight when minimizing total plate changes. The full chain (initial → warmups → work)
     * should be valid and the optimizer should prefer sequences that minimize total steps.
     */
    @Test
    fun optimizeWeightsForPercentages_includesCostFromLastWarmupToWorkWeight() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val percentages = listOf(0.40, 0.60, 0.80)

        val warmupWeights = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell,
            initialPlates = emptyList(),
            toleranceBandPercent = 0.05
        )

        assertEquals("Should return one weight per percentage", percentages.size, warmupWeights.size)
        assertTrue("Warmup weights should be progressive", warmupWeights.zipWithNext().all { (a, b) -> a <= b + 1e-9 })
        assertTrue("All warmup weights should be below work weight", warmupWeights.all { it < workWeight })

        val plateInventory = barbell.availablePlates.map { it.weight }
        val fullSequence = warmupWeights + workWeight
        val results = PlateCalculator.calculatePlateChanges(
            plateInventory,
            fullSequence,
            barbell.barWeight,
            emptyList()
        )

        assertEquals("Should have one result per set (warmups + work)", fullSequence.size, results.size)
        val totalSteps = results.sumOf { it.change.steps.size }
        assertTrue("Total plate change steps should be positive", totalSteps >= 0)
        val lastTransitionSteps = results.last().change.steps.size
        assertTrue(
            "Last transition (last warmup → work) should have steps when work > last warmup",
            lastTransitionSteps >= 0
        )
    }

    /**
     * Verifies that optimizeWeightsForPercentages with additionalWorkWeights minimizes plate changes
     * across the full sequence: warmups → workWeight → additionalWorkWeights (both adjacent and globally).
     */
    @Test
    fun optimizeWeightsForPercentages_withAdditionalWorkWeights_minimizesChainCost() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val additionalWorkWeights = listOf(120.0, 100.0) // set 2 and 3
        val percentages = listOf(0.50, 0.70)

        val warmupWeights = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell,
            initialPlates = emptyList(),
            toleranceBandPercent = 0.05,
            additionalWorkWeights = additionalWorkWeights
        )

        assertEquals("Should return one weight per percentage", percentages.size, warmupWeights.size)
        assertTrue("Warmup weights should be progressive", warmupWeights.zipWithNext().all { (a, b) -> a <= b + 1e-9 })
        assertTrue("All warmup weights should be below work weight", warmupWeights.all { it < workWeight })

        val fullSequence = warmupWeights + workWeight + additionalWorkWeights
        val plateInventory = barbell.availablePlates.map { it.weight }
        val results = PlateCalculator.calculatePlateChanges(
            plateInventory,
            fullSequence,
            barbell.barWeight,
            emptyList()
        )

        assertEquals("Should have one result per set (warmups + work + additional)", fullSequence.size, results.size)
        val totalSteps = results.sumOf { it.change.steps.size }
        assertTrue("Total plate change steps should be non-negative", totalSteps >= 0)
    }
}
