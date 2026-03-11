package com.gabstra.myworkoutassistant.shared.setdata

import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.google.gson.GsonBuilder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Regression tests for BodyWeightSetData serialization: round-trip with
 * bodyWeightPercentageSnapshot and legacy JSON without it.
 */
class BodyWeightSetDataSerializationTest {

    private val gson = GsonBuilder()
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .create()

    @Test
    fun roundTrip_withBodyWeightPercentageSnapshot_preservesSnapshotAndLoad() {
        val data = BodyWeightSetData(
            actualReps = 10,
            additionalWeight = 5.0,
            relativeBodyWeightInKg = 57.75,
            volume = 627.5,
            subCategory = SetSubCategory.WorkSet,
            bodyWeightPercentageSnapshot = 70.0
        )
        val json = gson.toJson(data)
        val deserialized = gson.fromJson(json, SetData::class.java) as BodyWeightSetData

        assertEquals(70.0, deserialized.bodyWeightPercentageSnapshot!!, 1e-9)
        assertEquals(data.getWeight(), deserialized.getWeight(), 1e-9)
        assertEquals(data.calculateVolume(), deserialized.calculateVolume(), 1e-9)
        assertEquals(data.relativeBodyWeightInKg, deserialized.relativeBodyWeightInKg, 1e-9)
        assertEquals(data.additionalWeight, deserialized.additionalWeight, 1e-9)
    }

    @Test
    fun legacyJson_withoutBodyWeightPercentageSnapshot_deserializesWithNullSnapshot() {
        val legacyJson = """
            {"type":"BodyWeightSetData","actualReps":8,"additionalWeight":10.0,
            "relativeBodyWeightInKg":52.5,"volume":500.0,"subCategory":"WorkSet"}
        """.trimIndent()
        val deserialized = gson.fromJson(legacyJson, SetData::class.java) as BodyWeightSetData

        assertNull(deserialized.bodyWeightPercentageSnapshot)
        assertEquals(52.5 + 10.0, deserialized.getWeight(), 1e-9)
        assertEquals(500.0, deserialized.calculateVolume(), 1e-9)
    }

    @Test
    fun roundTrip_withoutSnapshot_preservesLoadAndVolume() {
        val data = BodyWeightSetData(
            actualReps = 12,
            additionalWeight = 0.0,
            relativeBodyWeightInKg = 60.0,
            volume = 720.0,
            subCategory = SetSubCategory.WorkSet,
            bodyWeightPercentageSnapshot = null
        )
        val json = gson.toJson(data)
        val deserialized = gson.fromJson(json, SetData::class.java) as BodyWeightSetData

        assertNull(deserialized.bodyWeightPercentageSnapshot)
        assertEquals(60.0, deserialized.getWeight(), 1e-9)
        assertEquals(720.0, deserialized.calculateVolume(), 1e-9)
    }
}
