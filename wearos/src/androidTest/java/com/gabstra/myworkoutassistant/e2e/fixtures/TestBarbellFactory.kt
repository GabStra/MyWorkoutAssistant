package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import java.util.UUID

/**
 * Factory for creating test barbells used in E2E tests.
 */
object TestBarbellFactory {
    /**
     * Creates a test barbell with multiple plates of each weight to support higher total weights.
     * For 100.0 kg total with 20.0 kg bar, need 80.0 kg plates (40.0 kg per side).
     * With 2x 20.0 kg plates per side = 40.0 kg per side = 80.0 kg total + 20.0 kg bar = 100.0 kg
     */
    fun createTestBarbell(): Barbell {
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
            barWeight = 20.0
        )
    }
}

