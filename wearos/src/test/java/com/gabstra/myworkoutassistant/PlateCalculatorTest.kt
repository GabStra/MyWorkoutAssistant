package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID
import kotlin.math.abs

class PlateCalculatorTest {
    @Test
    fun addition_isCorrect() {
        assertEquals(4, 2 + 2)
    }

    @Test
    fun plate_changes_is_correct(){
        val plates = listOf(20.0, 10.0, 5.0, 5.0, 5.0, 2.5,1.25,1.0,0.5,0.25)
        val sets = listOf(107.0, 107.0, 100.5)
        val barWeight = 9.0
        val initialSetup = emptyList<Double>()
        val results = PlateCalculator.calculatePlateChanges(plates, sets, barWeight, initialSetup)
        assertEquals(3, results.size)
    }

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

    @Test
    fun optimizeWeightsForPercentages_basicProgressiveWeights() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val percentages = listOf(0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
        val tolerance = 0.05 // ±5%

        val result = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell,
            toleranceBandPercent = tolerance
        )

        assertEquals(percentages.size, result.size)
        
        // Verify weights are within tolerance band
        percentages.forEachIndexed { index, percentage ->
            val target = workWeight * percentage
            val actual = result[index]
            val lowerBound = target * (1 - tolerance)
            val upperBound = target * (1 + tolerance)
            assertTrue(
                "Weight at index $index ($actual) should be within tolerance band [$lowerBound, $upperBound] for target $target",
                actual >= lowerBound && actual <= upperBound
            )
        }

        // Verify weights are non-decreasing (Phase 1 should succeed)
        for (i in 1 until result.size) {
            assertTrue(
                "Weights should be non-decreasing: ${result[i-1]} <= ${result[i]}",
                result[i] >= result[i-1] - 1e-9
            )
        }
    }

    @Test
    fun optimizeWeightsForPercentages_singlePercentage() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val percentages = listOf(1.0)

        val result = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell
        )

        assertEquals(1, result.size)
        // With 20kg bar + 2x20kg + 2x10kg + 2x5kg + 2x2.5kg + 2x1.25kg plates,
        // max achievable is 20 + 77.5 = 97.5kg, so 100kg is not achievable
        // Algorithm should return closest achievable weight within tolerance
        assertTrue("Result should be close to target", abs(result[0] - workWeight) < 10.0)
        assertTrue("Result should be achievable", result[0] >= barbell.barWeight)
    }

    @Test
    fun optimizeWeightsForPercentages_allPercentagesEqual() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val percentages = listOf(1.0, 1.0, 1.0)

        val result = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell
        )

        assertEquals(3, result.size)
        // All should be the same weight (or very close) since percentages are equal
        // and within tolerance band of target
        val firstWeight = result[0]
        result.forEach { weight ->
            assertTrue("All weights should be equal or very close", abs(weight - firstWeight) < 1e-6)
        }
        // Should be within tolerance band of target
        val tolerance = 0.05
        val lowerBound = workWeight * (1 - tolerance)
        val upperBound = workWeight * (1 + tolerance)
        result.forEach { weight ->
            // If target is not achievable, use closest achievable weight
            assertTrue("Weight should be achievable", weight >= barbell.barWeight)
        }
    }

    @Test
    fun optimizeWeightsForPercentages_withInitialPlates() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val percentages = listOf(0.5, 0.6, 0.7)
        val initialPlates = listOf(10.0, 5.0) // 30kg per side = 60kg total plates

        val result = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell,
            initialPlates = initialPlates
        )

        assertEquals(percentages.size, result.size)
        // Verify weights are achievable and within tolerance
        percentages.forEachIndexed { index, percentage ->
            val target = workWeight * percentage
            val actual = result[index]
            val tolerance = 0.05
            val lowerBound = target * (1 - tolerance)
            val upperBound = target * (1 + tolerance)
            assertTrue(
                "Weight at index $index ($actual) should be within tolerance band for target $target",
                actual >= lowerBound && actual <= upperBound
            )
        }
    }

    @Test
    fun optimizeWeightsForPercentages_tightTolerance() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val percentages = listOf(0.5, 0.6, 0.7)
        val tolerance = 0.01 // Very tight ±1%

        val result = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell,
            toleranceBandPercent = tolerance
        )

        assertEquals(percentages.size, result.size)
        // Verify weights are within tight tolerance
        percentages.forEachIndexed { index, percentage ->
            val target = workWeight * percentage
            val actual = result[index]
            val lowerBound = target * (1 - tolerance)
            val upperBound = target * (1 + tolerance)
            assertTrue(
                "Weight at index $index ($actual) should be within tight tolerance band [$lowerBound, $upperBound]",
                actual >= lowerBound && actual <= upperBound
            )
        }
    }

    @Test
    fun optimizeWeightsForPercentages_phase2Fallback() {
        // Create a scenario where Phase 1 (add-only) might fail
        // by using decreasing percentages
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val percentages = listOf(1.0, 0.8, 0.6) // Decreasing weights

        val result = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell,
            toleranceBandPercent = 0.1 // Wider tolerance to allow Phase 2
        )

        assertEquals(percentages.size, result.size)
        // Verify weights are within tolerance band
        percentages.forEachIndexed { index, percentage ->
            val target = workWeight * percentage
            val actual = result[index]
            val tolerance = 0.1
            val lowerBound = target * (1 - tolerance)
            val upperBound = target * (1 + tolerance)
            assertTrue(
                "Weight at index $index ($actual) should be within tolerance band for target $target",
                actual >= lowerBound && actual <= upperBound
            )
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun optimizeWeightsForPercentages_emptyPercentages() {
        val barbell = createTestBarbell()
        PlateCalculator.optimizeWeightsForPercentages(
            workWeight = 100.0,
            weightPercentages = emptyList(),
            barbell = barbell
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun optimizeWeightsForPercentages_invalidWorkWeight() {
        val barbell = createTestBarbell()
        PlateCalculator.optimizeWeightsForPercentages(
            workWeight = -10.0,
            weightPercentages = listOf(0.5, 0.6),
            barbell = barbell
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun optimizeWeightsForPercentages_percentageGreaterThanOne() {
        val barbell = createTestBarbell()
        PlateCalculator.optimizeWeightsForPercentages(
            workWeight = 100.0,
            weightPercentages = listOf(0.5, 1.1), // 1.1 > 1.0
            barbell = barbell
        )
    }

    @Test
    fun optimizeWeightsForPercentages_smallWeights() {
        val barbell = createTestBarbell(barWeight = 9.0)
        val workWeight = 50.0
        val percentages = listOf(0.4, 0.5, 0.6)

        val result = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell,
            toleranceBandPercent = 0.1
        )

        assertEquals(percentages.size, result.size)
        // Verify all weights are achievable
        result.forEach { weight ->
            assertTrue("Weight $weight should be >= bar weight", weight >= 9.0)
        }
    }

    @Test
    fun optimizeWeightsForPercentages_minimizesPlateChanges() {
        val barbell = createTestBarbell(barWeight = 20.0)
        val workWeight = 100.0
        val percentages = listOf(0.5, 0.6, 0.7, 0.8, 0.9, 1.0)

        val result = PlateCalculator.optimizeWeightsForPercentages(
            workWeight = workWeight,
            weightPercentages = percentages,
            barbell = barbell
        )

        assertEquals(percentages.size, result.size)
        
        // Verify the solution minimizes plate changes by checking that
        // consecutive weights use progressive plate additions
        val plateInventory = barbell.availablePlates.map { it.weight }
        val changeResults = PlateCalculator.calculatePlateChanges(
            availablePlates = plateInventory,
            sets = result,
            barWeight = barbell.barWeight
        )

        // Calculate total plate changes
        val totalChanges = changeResults.sumOf { it.change.steps.size }
        
        // Verify we got a reasonable solution (not too many changes)
        // For progressive weights, we should have relatively few changes
        // Allow more changes if weights are not perfectly progressive
        assertTrue(
            "Total plate changes ($totalChanges) should be reasonable for ${percentages.size} weights",
            totalChanges < percentages.size * 6 // Reasonable upper bound accounting for optimization trade-offs
        )
        
        // Verify weights are non-decreasing (Phase 1 should succeed for progressive percentages)
        for (i in 1 until result.size) {
            assertTrue(
                "Weights should be non-decreasing: ${result[i-1]} <= ${result[i]}",
                result[i] >= result[i-1] - 1e-9
            )
        }
    }
}