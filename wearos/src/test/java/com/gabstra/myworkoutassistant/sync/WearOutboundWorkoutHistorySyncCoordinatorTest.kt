package com.gabstra.myworkoutassistant.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class WearOutboundWorkoutHistorySyncCoordinatorTest {

    @Test
    fun `startup resend does not reselect ids already claimed by another send path`() {
        val state = WearOutboundWorkoutHistorySyncCoordinatorState()
        val first = UUID.randomUUID()
        val second = UUID.randomUUID()

        val completedDecision = state.requestCompletedWorkoutSync(first)
        state.completeDirectSend(
            claim = (completedDecision as WearWorkoutHistorySyncDecision.StartDirect).claim,
            success = false,
            pendingHistoryIds = setOf(first, second)
        )
        val startupDecision = state.runStartupResend(setOf(first, second))

        val startupClaim = startupDecision as WearWorkoutHistorySyncDecision.StartDirect

        assertEquals(setOf(second), startupClaim.claim.claimedHistoryIds)
    }

    @Test
    fun `reconnect resend only schedules once for the same pending state`() {
        val state = WearOutboundWorkoutHistorySyncCoordinatorState()
        val historyId = UUID.randomUUID()

        val firstDecision = state.notifyPhoneReconnect(setOf(historyId))
        val secondDecision = state.notifyPhoneReconnect(setOf(historyId))

        assertTrue(firstDecision is WearWorkoutHistorySyncDecision.StartDirect)
        assertEquals(WearWorkoutHistorySyncDecision.None, secondDecision)
    }

    @Test
    fun `completed workout request wins over debounced intermediate timing`() {
        val state = WearOutboundWorkoutHistorySyncCoordinatorState()
        val historyId = UUID.randomUUID()

        val debouncedDecision = state.requestDebouncedIntermediateSync()
        val completedDecision = state.requestCompletedWorkoutSync(historyId)

        assertTrue(debouncedDecision is WearWorkoutHistorySyncDecision.ScheduleDebounce)
        val completedClaim = completedDecision as WearWorkoutHistorySyncDecision.StartDirect
        assertEquals(WearWorkoutHistorySyncReason.CompletedWorkout, completedClaim.claim.reason)
        assertEquals(setOf(historyId), completedClaim.claim.claimedHistoryIds)
        assertEquals(WearWorkoutHistorySyncDecision.None, state.consumeDebouncedIntermediateSync())
    }

    @Test
    fun `lifecycle flush promotes completed and only one intermediate flush per pending state`() {
        val state = WearOutboundWorkoutHistorySyncCoordinatorState()
        val historyId = UUID.randomUUID()

        val completedDecision = state.requestCompletedWorkoutSync(historyId)
        state.completeDirectSend(
            claim = (completedDecision as WearWorkoutHistorySyncDecision.StartDirect).claim,
            success = true,
            pendingHistoryIds = emptySet()
        )

        state.requestDebouncedIntermediateSync()
        val pauseDecision = state.notifyLifecycleFlush(
            source = WearWorkoutLifecycleFlushSource.Pause,
            pendingHistoryIds = emptySet(),
            allowIntermediateSync = true
        )
        val stopDecision = state.notifyLifecycleFlush(
            source = WearWorkoutLifecycleFlushSource.Stop,
            pendingHistoryIds = emptySet(),
            allowIntermediateSync = false
        )

        val pauseClaim = pauseDecision as WearWorkoutHistorySyncDecision.StartDirect
        assertEquals(WearWorkoutHistorySyncReason.LifecycleFlush, pauseClaim.claim.reason)
        assertEquals(emptySet<UUID>(), pauseClaim.claim.claimedHistoryIds)
        assertEquals(WearWorkoutHistorySyncDecision.None, stopDecision)
    }

    @Test
    fun `success clears claim state correctly`() {
        val state = WearOutboundWorkoutHistorySyncCoordinatorState()
        val historyId = UUID.randomUUID()

        val startDecision = state.requestCompletedWorkoutSync(historyId)
        val claim = (startDecision as WearWorkoutHistorySyncDecision.StartDirect).claim
        val followUp = state.completeDirectSend(claim, success = true, pendingHistoryIds = setOf(historyId))

        assertTrue(followUp.isEmpty())
        val startupDecision = state.runStartupResend(setOf(historyId))
        val startupClaim = startupDecision as WearWorkoutHistorySyncDecision.StartDirect
        assertEquals(setOf(historyId), startupClaim.claim.claimedHistoryIds)
    }

    @Test
    fun `retry preserves failed ids for worker fallback without reselecting success`() {
        val state = WearOutboundWorkoutHistorySyncCoordinatorState()
        val first = UUID.randomUUID()
        val second = UUID.randomUUID()

        val initialClaim = state.claimWorkerRetryBatch(setOf(first, second))
            ?: error("expected worker claim")
        val followUp = state.completeWorkerRetryBatch(
            claim = initialClaim,
            failedHistoryIds = setOf(second)
        )

        assertTrue(followUp is WearWorkoutHistorySyncDecision.EnqueueWorker)
        val retryClaim = state.claimWorkerRetryBatch(setOf(first, second))
            ?: error("expected retry claim")
        assertEquals(setOf(second), retryClaim.claimedHistoryIds)
    }

    @Test
    fun `idle stale claims do not block persisted pending lifecycle reclaim`() {
        val state = WearOutboundWorkoutHistorySyncCoordinatorState()
        val historyId = UUID.randomUUID()

        state.requestDebouncedIntermediateSync()
        state.consumeDebouncedIntermediateSync()
        state.cancelInFlightIntermediateSync()

        val lifecycleDecision = state.notifyLifecycleFlush(
            source = WearWorkoutLifecycleFlushSource.Navigation,
            pendingHistoryIds = setOf(historyId),
            allowIntermediateSync = true
        )

        val claim = lifecycleDecision as WearWorkoutHistorySyncDecision.StartDirect
        assertEquals(setOf(historyId), claim.claim.claimedHistoryIds)
    }
}
