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

    @Test
    fun `SetRowIdentifierCounter starts work rows at one after warmups`() {
        val counter = SetRowIdentifierCounter()

        assertEquals("W1", counter.nextIdentifier(SetSubCategory.WarmupSet))
        assertEquals("W2", counter.nextIdentifier(SetSubCategory.WarmupSet))
        assertEquals("1", counter.nextIdentifier(SetSubCategory.WorkSet))
        assertEquals("2", counter.nextIdentifier(SetSubCategory.WorkSet))
    }
}
