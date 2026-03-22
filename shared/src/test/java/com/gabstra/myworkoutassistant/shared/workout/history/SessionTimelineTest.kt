package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.Assert.fail

class SessionTimelineTest {

    private val whId: UUID = UUID.fromString("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    @Test
    fun mergeSessionTimeline_interleavesByExecutionSequence() {
        val s1 = sampleSetHistory(id = 1, seq = 1u, start = t("2026-03-22T10:00:00"))
        val s2 = sampleSetHistory(id = 2, seq = 3u, start = t("2026-03-22T10:05:00"))
        val r1 = sampleRestHistory(id = 10, seq = 2u, start = t("2026-03-22T10:02:00"))

        val merged = mergeSessionTimeline(listOf(s1, s2), listOf(r1))
        assertEquals(
            listOf(
                SessionTimelineItem.SetStep(s1),
                SessionTimelineItem.RestStep(r1),
                SessionTimelineItem.SetStep(s2)
            ),
            merged
        )
    }

    @Test
    fun mergeSessionTimeline_tieBreaksByStartTimeThenId() {
        val idLow = UUID.fromString("00000000-0000-0000-0000-000000000001")
        val idHigh = UUID.fromString("00000000-0000-0000-0000-000000000002")
        val sameSeq = 1u
        val sameStart = t("2026-03-22T10:00:00")
        val a = sampleSetHistory(id = 1, uuid = idLow, seq = sameSeq, start = sameStart)
        val b = sampleRestHistory(id = 2, uuid = idHigh, seq = sameSeq, start = sameStart)

        val merged = mergeSessionTimeline(listOf(a), listOf(b))
        assertTrue(merged[0] is SessionTimelineItem.SetStep)
        assertTrue(merged[1] is SessionTimelineItem.RestStep)
    }

    @Test
    fun mergeSessionTimeline_emptyInputs() {
        assertEquals(emptyList<SessionTimelineItem>(), mergeSessionTimeline(emptyList(), emptyList()))
    }

    @Test
    fun orderedBetweenWorkoutComponentRestHistories_followsWorkoutComponentOrderNotInputListOrder() {
        val restA = UUID.fromString("10000000-0000-0000-0000-0000000000a1")
        val restB = UUID.fromString("10000000-0000-0000-0000-0000000000b2")
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "t",
            description = "",
            workoutComponents = listOf(
                Rest(restB, true, 60),
                Rest(restA, true, 90)
            ),
            order = 0,
            creationDate = LocalDate.of(2026, 3, 22),
            globalId = UUID.randomUUID(),
            type = 0
        )
        val hA = betweenRestHistory(componentId = restA, seq = 2u, start = t("2026-03-22T10:02:00")) // executed second
        val hB = betweenRestHistory(componentId = restB, seq = 1u, start = t("2026-03-22T10:00:00")) // executed first
        val ordered = orderedBetweenWorkoutComponentRestHistories(listOf(hA, hB), workout)
        assertEquals(listOf(hB.id, hA.id), ordered.map { it.id })
    }

    @Test
    fun orderedBetweenWorkoutComponentRestHistories_throwsWhenDuplicateWorkoutComponentId() {
        val compId = UUID.fromString("20000000-0000-0000-0000-000000000001")
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "t",
            description = "",
            workoutComponents = listOf(Rest(compId, true, 60)),
            order = 0,
            creationDate = LocalDate.of(2026, 3, 22),
            globalId = UUID.randomUUID(),
            type = 0
        )
        val later = betweenRestHistory(
            componentId = compId,
            seq = 2u,
            start = t("2026-03-22T10:05:00"),
            uuid = UUID.fromString("30000000-0000-0000-0000-000000000001")
        )
        val earlier = betweenRestHistory(
            componentId = compId,
            seq = 1u,
            start = t("2026-03-22T10:02:00"),
            uuid = UUID.fromString("30000000-0000-0000-0000-000000000002")
        )
        try {
            orderedBetweenWorkoutComponentRestHistories(listOf(later, earlier), workout)
            fail("expected IllegalStateException")
        } catch (e: IllegalStateException) {
            assertTrue(e.message!!.contains(compId.toString()))
        }
    }

    private fun t(s: String): LocalDateTime = LocalDateTime.parse(s)

    private fun sampleSetHistory(
        id: Int,
        uuid: UUID = UUID.nameUUIDFromBytes("set-$id".toByteArray()),
        seq: UInt?,
        start: LocalDateTime
    ): SetHistory = SetHistory(
        id = uuid,
        workoutHistoryId = whId,
        exerciseId = UUID.randomUUID(),
        equipmentIdSnapshot = null,
        equipmentNameSnapshot = null,
        equipmentTypeSnapshot = null,
        setId = UUID.randomUUID(),
        order = id.toUInt(),
        startTime = start,
        endTime = start.plusMinutes(1),
        setData = WeightSetData(10, 50.0, 50.0, SetSubCategory.WorkSet),
        skipped = false,
        executionSequence = seq
    )

    private fun sampleRestHistory(
        id: Int,
        uuid: UUID = UUID.nameUUIDFromBytes("rest-$id".toByteArray()),
        seq: UInt?,
        start: LocalDateTime
    ): RestHistory = RestHistory(
        id = uuid,
        workoutHistoryId = whId,
        scope = RestHistoryScope.INTRA_EXERCISE,
        executionSequence = seq,
        setData = RestSetData(60, 60, SetSubCategory.WorkSet),
        startTime = start,
        endTime = start.plusSeconds(60),
        workoutComponentId = null,
        exerciseId = UUID.randomUUID(),
        restSetId = UUID.randomUUID(),
        order = id.toUInt()
    )

    private fun betweenRestHistory(
        componentId: UUID,
        seq: UInt?,
        start: LocalDateTime,
        uuid: UUID = UUID.nameUUIDFromBytes("${componentId}-$seq".toByteArray())
    ): RestHistory = RestHistory(
        id = uuid,
        workoutHistoryId = whId,
        scope = RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS,
        executionSequence = seq,
        setData = RestSetData(60, 60, SetSubCategory.WorkSet),
        startTime = start,
        endTime = start.plusSeconds(60),
        workoutComponentId = componentId,
        exerciseId = UUID.randomUUID(),
        restSetId = UUID.randomUUID(),
        order = 0u
    )
}
