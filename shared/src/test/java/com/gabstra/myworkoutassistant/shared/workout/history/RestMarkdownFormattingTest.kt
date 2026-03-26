package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

class RestMarkdownFormattingTest {

    @Test
    fun formatRestLineForMarkdown_elapsedAndPlannedWhenDifferent() {
        val start = LocalDateTime.of(2025, 1, 1, 10, 0, 0)
        val end = LocalDateTime.of(2025, 1, 1, 10, 1, 32)
        val rh = RestHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            scope = RestHistoryScope.INTRA_EXERCISE,
            executionSequence = null,
            setData = RestSetData(startTimer = 90, endTimer = 0),
            startTime = start,
            endTime = end,
            workoutComponentId = null,
            exerciseId = UUID.randomUUID(),
            restSetId = UUID.randomUUID(),
            order = 0u,
            version = 0u
        )
        val line = formatRestLineForMarkdown(rh)
        assertEquals(
            "Rest: 1:32 elapsed (1:30 planned) [intra-exercise]",
            line
        )
    }

    @Test
    fun formatRestLineForMarkdown_plannedOnlyWhenNoElapsedBounds() {
        val rh = RestHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            scope = RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS,
            executionSequence = null,
            setData = RestSetData(startTimer = 120, endTimer = 0),
            startTime = null,
            endTime = null,
            workoutComponentId = UUID.randomUUID(),
            exerciseId = null,
            restSetId = UUID.randomUUID(),
            order = 0u,
            version = 0u
        )
        val line = formatRestLineForMarkdown(rh)
        assertEquals("Rest: 2:00 planned [between components]", line)
    }
}
