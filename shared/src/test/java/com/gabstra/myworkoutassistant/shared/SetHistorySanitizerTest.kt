package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

class SetHistorySanitizerTest {

    @Test
    fun sanitizeRestPlacementInSetHistories_removesLeadingTrailingAndConsecutiveRest() {
        val workoutHistoryId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()

        val leadingRest = restHistory(workoutHistoryId, exerciseId, 0u)
        val work1 = workHistory(workoutHistoryId, exerciseId, 1u)
        val middleRest1 = restHistory(workoutHistoryId, exerciseId, 2u)
        val middleRest2 = restHistory(workoutHistoryId, exerciseId, 3u)
        val work2 = workHistory(workoutHistoryId, exerciseId, 4u)
        val trailingRest = restHistory(workoutHistoryId, exerciseId, 5u)

        val result = sanitizeRestPlacementInSetHistories(
            listOf(leadingRest, work1, middleRest1, middleRest2, work2, trailingRest)
        )

        assertEquals(listOf(work1.id, middleRest1.id, work2.id), result.map { it.id })
    }

    private fun workHistory(workoutHistoryId: UUID, exerciseId: UUID, order: UInt): SetHistory =
        SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = workoutHistoryId,
            exerciseId = exerciseId,
            setId = UUID.randomUUID(),
            order = order,
            startTime = LocalDateTime.now(),
            endTime = LocalDateTime.now(),
            setData = WeightSetData(actualReps = 8, actualWeight = 100.0, volume = 800.0),
            skipped = false
        )

    private fun restHistory(workoutHistoryId: UUID, exerciseId: UUID, order: UInt): SetHistory =
        SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = workoutHistoryId,
            exerciseId = exerciseId,
            setId = UUID.randomUUID(),
            order = order,
            startTime = LocalDateTime.now(),
            endTime = LocalDateTime.now(),
            setData = RestSetData(startTimer = 90, endTimer = 90),
            skipped = false
        )
}
