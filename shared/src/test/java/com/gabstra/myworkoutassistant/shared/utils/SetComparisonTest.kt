package com.gabstra.myworkoutassistant.shared.utils

import org.junit.Assert.assertEquals
import org.junit.Test

class SetComparisonTest {

    @Test
    fun `compareSetListsUnordered returns above when one of two sets improves and the other is unchanged`() {
        val previousSession = listOf(
            SimpleSet(weight = 100.0, reps = 10),
            SimpleSet(weight = 100.0, reps = 12)
        )
        val currentSession = listOf(
            SimpleSet(weight = 100.0, reps = 11),
            SimpleSet(weight = 100.0, reps = 12)
        )

        val result = compareSetListsUnordered(currentSession, previousSession)

        assertEquals(Ternary.ABOVE, result)
    }
}
