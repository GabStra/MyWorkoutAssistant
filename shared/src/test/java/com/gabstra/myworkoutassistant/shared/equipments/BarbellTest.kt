package com.gabstra.myworkoutassistant.shared.equipments

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class BarbellTest {

    @Test
    fun testGetWeightsCombinationsWithLabels_ShowsBarAndPlatesSeparately() {
        // Create a barbell with 20kg bar and some plates
        val barWeight = 20.0
        val plates = listOf(
            Plate(20.0, 10.0), // 20kg plate
            Plate(20.0, 10.0), // Another 20kg plate
            Plate(10.0, 5.0),  // 10kg plate
            Plate(10.0, 5.0),  // Another 10kg plate
            Plate(5.0, 3.0)    // 5kg plate
        )
        val barbell = Barbell(
            id = UUID.randomUUID(),
            name = "Test Barbell",
            availablePlates = plates,
            sleeveLength = 100,
            barWeight = barWeight
        )

        val labels = barbell.getWeightsCombinationsWithLabels()

        // Should have at least one entry (bar only)
        assertTrue("Should have at least one weight combination", labels.isNotEmpty())

        // Find the bar-only entry (total = barWeight, plateWeight = 0)
        val barOnly = labels.find { it.first == barWeight }
        assertTrue("Should have bar-only entry", barOnly != null)
        assertEquals("20 kg", barOnly!!.second)

        // Find an entry with plates (e.g., bar + 40kg plates = 60kg total)
        // With 2x20kg plates, we get 40kg total plates (20kg per side * 2)
        val withPlates = labels.find { it.first == 60.0 } // 20kg bar + 40kg plates
        if (withPlates != null) {
            assertTrue(
                "Label should show bar and plates in concise format",
                withPlates.second.contains("20") && withPlates.second.contains("40") && withPlates.second.contains("kg")
            )
            assertEquals("20 + 40 kg", withPlates.second)
        }
    }

    @Test
    fun testGetWeightsCombinationsWithLabels_OneEntryPerUniqueTotal() {
        val barWeight = 20.0
        val plates = listOf(
            Plate(20.0, 10.0),
            Plate(20.0, 10.0),
            Plate(10.0, 5.0)
        )
        val barbell = Barbell(
            id = UUID.randomUUID(),
            name = "Test Barbell",
            availablePlates = plates,
            sleeveLength = 100,
            barWeight = barWeight
        )

        val labels = barbell.getWeightsCombinationsWithLabels()
        val totals = labels.map { it.first }.toSet()

        // Each total should appear exactly once
        assertEquals("Each total weight should appear exactly once", totals.size, labels.size)
    }

    @Test
    fun testGetWeightsCombinationsWithLabels_FormatForZeroPlates() {
        val barWeight = 20.0
        val plates = listOf(Plate(20.0, 10.0))
        val barbell = Barbell(
            id = UUID.randomUUID(),
            name = "Test Barbell",
            availablePlates = plates,
            sleeveLength = 100,
            barWeight = barWeight
        )

        val labels = barbell.getWeightsCombinationsWithLabels()
        val barOnly = labels.find { it.first == barWeight }

        assertTrue("Should have bar-only entry", barOnly != null)
        // Should just show the weight when there are no plates
        assertEquals("20 kg", barOnly!!.second)
    }
}

