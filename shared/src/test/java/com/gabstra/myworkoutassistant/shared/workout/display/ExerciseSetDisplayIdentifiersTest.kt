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
    fun `buildSupersetAwareRowLabel prefixes every centered superset row category`() {
        assertEquals("B · SET LOAD", buildSupersetAwareRowLabel("B", "SET LOAD"))
        assertEquals("AA · SET RIR", buildSupersetAwareRowLabel("AA", "SET RIR"))
        assertEquals("SET LOAD", buildSupersetAwareRowLabel(null, "SET LOAD"))
    }

    @Test
    fun `set identifiers keep superset letter first for every counter kind`() {
        assertEquals("A1", buildSetDisplayIdentifier(1, "A", SetDisplayCounterKind.Work))
        assertEquals("B · W2", buildSetDisplayIdentifier(2, "B", SetDisplayCounterKind.Warmup))
        assertEquals("C · CAL", buildSetDisplayIdentifier(1, "C", SetDisplayCounterKind.Calibration))
        assertEquals("W2", buildSetDisplayIdentifier(2, null, SetDisplayCounterKind.Warmup))
        assertEquals("CAL", buildSetDisplayIdentifier(1, null, SetDisplayCounterKind.Calibration))
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
