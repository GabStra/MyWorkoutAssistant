package com.gabstra.myworkoutassistant.shared.workout.display

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ExerciseSetDisplayIdentifiersTest {

    @Test
    fun `toSupersetLetter maps index to A-Z then AA`() {
        assertEquals("A", toSupersetLetter(0))
        assertEquals("B", toSupersetLetter(1))
        assertEquals("Z", toSupersetLetter(25))
        assertEquals("AA", toSupersetLetter(26))
    }

    @Test
    fun `buildUnilateralSideLabel returns L and R for bilateral`() {
        assertEquals("-L", buildUnilateralSideLabel(1u, 2u))
        assertEquals("-R", buildUnilateralSideLabel(2u, 2u))
        assertNull(buildUnilateralSideLabel(1u, 3u))
        assertNull(buildUnilateralSideLabel(null, 2u))
    }

    @Test
    fun `formatWorkoutDurationSecondsForDisplay matches short and long forms`() {
        assertEquals("05:30", formatWorkoutDurationSecondsForDisplay(330))
        assertEquals("01:05:30", formatWorkoutDurationSecondsForDisplay(3930))
    }
}
