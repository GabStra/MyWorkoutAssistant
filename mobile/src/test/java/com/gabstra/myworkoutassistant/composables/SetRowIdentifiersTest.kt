package com.gabstra.myworkoutassistant.composables

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import org.junit.Assert.assertEquals
import org.junit.Test

class SetRowIdentifiersTest {

    @Test
    fun `buildSetRowIdentifier prefixes warmup rows with W`() {
        assertEquals("W1", buildSetRowIdentifier(1, SetSubCategory.WarmupSet))
    }

    @Test
    fun `buildSetRowIdentifier keeps calibration rows labeled as Cal`() {
        assertEquals("Cal", buildSetRowIdentifier(2, SetSubCategory.CalibrationSet))
    }

    @Test
    fun `buildSetRowIdentifier keeps work rows numeric`() {
        assertEquals("3", buildSetRowIdentifier(3, SetSubCategory.WorkSet))
        assertEquals("4", buildSetRowIdentifier(4, null))
    }
}
