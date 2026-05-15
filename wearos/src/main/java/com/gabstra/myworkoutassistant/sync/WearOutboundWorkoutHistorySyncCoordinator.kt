package com.gabstra.myworkoutassistant.sync

import java.util.UUID

internal enum class WearWorkoutHistorySyncReason(val wireValue: String) {
    CompletedWorkout("completed_workout"),
    DebouncedIntermediate("debounced_intermediate"),
    StartupResend("startup_resend"),
    ReconnectResend("reconnect_resend"),
    WorkerRetry("worker_retry"),
    LifecycleFlush("lifecycle_flush")
}

internal enum class WearWorkoutLifecycleFlushSource {
    Pause,
    Stop,
    Navigation
}

internal data class WearDirectHistorySyncClaim(
    val reason: WearWorkoutHistorySyncReason,
    val claimedHistoryIds: Set<UUID> = emptySet()
)

internal data class WearWorkerRetryClaim(
    val reason: WearWorkoutHistorySyncReason,
    val claimedHistoryIds: Set<UUID>
)

internal sealed interface WearWorkoutHistorySyncDecision {
    data object None : WearWorkoutHistorySyncDecision
    data class ScheduleDebounce(
        val reason: WearWorkoutHistorySyncReason
    ) : WearWorkoutHistorySyncDecision
    data class StartDirect(
        val claim: WearDirectHistorySyncClaim
    ) : WearWorkoutHistorySyncDecision
    data class EnqueueWorker(
        val reason: WearWorkoutHistorySyncReason
    ) : WearWorkoutHistorySyncDecision
}

internal class WearOutboundWorkoutHistorySyncCoordinatorState {
    private var pendingIntermediateSync = false
    private val pendingCompletedHistoryIds = linkedSetOf<UUID>()
    private val claimedHistoryIds = linkedSetOf<UUID>()
    private val reservedWorkerRetryHistoryIds = linkedSetOf<UUID>()
    private var pendingReconnectResend = false
    private var lifecycleFlushConsumed = false
    private var directSendInFlight: WearDirectHistorySyncClaim? = null
    private var workerRetryInFlightIds: Set<UUID> = emptySet()

    fun hasPendingSyncWork(): Boolean {
        return pendingIntermediateSync ||
            pendingCompletedHistoryIds.isNotEmpty() ||
            pendingReconnectResend ||
            reservedWorkerRetryHistoryIds.isNotEmpty() ||
            directSendInFlight != null ||
            workerRetryInFlightIds.isNotEmpty()
    }

    fun requestDebouncedIntermediateSync(): WearWorkoutHistorySyncDecision {
        releaseStaleClaimsIfIdle()
        pendingIntermediateSync = true
        lifecycleFlushConsumed = false
        return if (directSendInFlight == null && pendingCompletedHistoryIds.isEmpty()) {
            WearWorkoutHistorySyncDecision.ScheduleDebounce(
                WearWorkoutHistorySyncReason.DebouncedIntermediate
            )
        } else {
            WearWorkoutHistorySyncDecision.None
        }
    }

    fun requestCompletedWorkoutSync(historyId: UUID?): WearWorkoutHistorySyncDecision {
        releaseStaleClaimsIfIdle()
        if (historyId != null) {
            pendingCompletedHistoryIds += historyId
        }
        pendingIntermediateSync = false
        lifecycleFlushConsumed = false
        if (directSendInFlight != null) {
            return WearWorkoutHistorySyncDecision.None
        }
        return startPendingCompletedDirect(
            reason = WearWorkoutHistorySyncReason.CompletedWorkout
        )
    }

    fun consumeDebouncedIntermediateSync(): WearWorkoutHistorySyncDecision {
        if (!pendingIntermediateSync || directSendInFlight != null) {
            return WearWorkoutHistorySyncDecision.None
        }
        pendingIntermediateSync = false
        val claim = WearDirectHistorySyncClaim(
            reason = WearWorkoutHistorySyncReason.DebouncedIntermediate
        )
        directSendInFlight = claim
        return WearWorkoutHistorySyncDecision.StartDirect(claim)
    }

    fun runStartupResend(pendingHistoryIds: Set<UUID>): WearWorkoutHistorySyncDecision {
        releaseStaleClaimsIfIdle()
        if (directSendInFlight != null || pendingCompletedHistoryIds.isNotEmpty()) {
            return WearWorkoutHistorySyncDecision.None
        }
        val claimableIds = claimPersistedPendingIds(pendingHistoryIds)
        if (claimableIds.isEmpty()) {
            return WearWorkoutHistorySyncDecision.None
        }
        val claim = WearDirectHistorySyncClaim(
            reason = WearWorkoutHistorySyncReason.StartupResend,
            claimedHistoryIds = claimableIds
        )
        directSendInFlight = claim
        return WearWorkoutHistorySyncDecision.StartDirect(claim)
    }

    fun notifyPhoneReconnect(pendingHistoryIds: Set<UUID>): WearWorkoutHistorySyncDecision {
        releaseStaleClaimsIfIdle()
        val hasClaimablePending = hasClaimablePersistedPendingIds(pendingHistoryIds)
        if (!hasClaimablePending) {
            pendingReconnectResend = false
            return WearWorkoutHistorySyncDecision.None
        }
        lifecycleFlushConsumed = false
        if (directSendInFlight != null) {
            pendingReconnectResend = true
            return WearWorkoutHistorySyncDecision.None
        }
        val claimableIds = claimPersistedPendingIds(pendingHistoryIds)
        if (claimableIds.isEmpty()) {
            pendingReconnectResend = false
            return WearWorkoutHistorySyncDecision.None
        }
        pendingReconnectResend = false
        val claim = WearDirectHistorySyncClaim(
            reason = WearWorkoutHistorySyncReason.ReconnectResend,
            claimedHistoryIds = claimableIds
        )
        directSendInFlight = claim
        return WearWorkoutHistorySyncDecision.StartDirect(claim)
    }

    fun notifyLifecycleFlush(
        source: WearWorkoutLifecycleFlushSource,
        pendingHistoryIds: Set<UUID>,
        allowIntermediateSync: Boolean
    ): WearWorkoutHistorySyncDecision {
        releaseStaleClaimsIfIdle()
        if (directSendInFlight != null || lifecycleFlushConsumed) {
            return WearWorkoutHistorySyncDecision.None
        }

        val decision = when {
            pendingCompletedHistoryIds.isNotEmpty() ->
                startPendingCompletedDirect(WearWorkoutHistorySyncReason.LifecycleFlush)
            hasClaimablePersistedPendingIds(pendingHistoryIds) -> {
                val claimableIds = claimPersistedPendingIds(pendingHistoryIds)
                if (claimableIds.isEmpty()) {
                    WearWorkoutHistorySyncDecision.None
                } else {
                    pendingReconnectResend = false
                    val claim = WearDirectHistorySyncClaim(
                        reason = WearWorkoutHistorySyncReason.LifecycleFlush,
                        claimedHistoryIds = claimableIds
                    )
                    directSendInFlight = claim
                    WearWorkoutHistorySyncDecision.StartDirect(claim)
                }
            }
            pendingReconnectResend -> {
                val claimableIds = claimPersistedPendingIds(pendingHistoryIds)
                if (claimableIds.isEmpty()) {
                    WearWorkoutHistorySyncDecision.None
                } else {
                    pendingReconnectResend = false
                    val claim = WearDirectHistorySyncClaim(
                        reason = WearWorkoutHistorySyncReason.LifecycleFlush,
                        claimedHistoryIds = claimableIds
                    )
                    directSendInFlight = claim
                    WearWorkoutHistorySyncDecision.StartDirect(claim)
                }
            }
            allowIntermediateSync && pendingIntermediateSync -> {
                pendingIntermediateSync = false
                val claim = WearDirectHistorySyncClaim(
                    reason = WearWorkoutHistorySyncReason.LifecycleFlush
                )
                directSendInFlight = claim
                WearWorkoutHistorySyncDecision.StartDirect(claim)
            }
            else -> WearWorkoutHistorySyncDecision.None
        }

        if (decision !is WearWorkoutHistorySyncDecision.None) {
            lifecycleFlushConsumed = true
        }
        return decision
    }

    fun completeDirectSend(
        claim: WearDirectHistorySyncClaim,
        success: Boolean,
        pendingHistoryIds: Set<UUID>
    ): List<WearWorkoutHistorySyncDecision> {
        if (directSendInFlight == claim) {
            directSendInFlight = null
        }

        val claimedIds = claim.claimedHistoryIds
        val decisions = mutableListOf<WearWorkoutHistorySyncDecision>()

        if (success) {
            claimedHistoryIds.removeAll(claimedIds)
            pendingCompletedHistoryIds.removeAll(claimedIds)
            reservedWorkerRetryHistoryIds.removeAll(claimedIds)
        } else if (claimedIds.isNotEmpty()) {
            claimedHistoryIds.removeAll(claimedIds)
            pendingCompletedHistoryIds.removeAll(claimedIds)
            reservedWorkerRetryHistoryIds += claimedIds
            decisions += WearWorkoutHistorySyncDecision.EnqueueWorker(
                WearWorkoutHistorySyncReason.WorkerRetry
            )
        }

        when {
            pendingCompletedHistoryIds.isNotEmpty() -> {
                decisions += startPendingCompletedDirect(
                    reason = WearWorkoutHistorySyncReason.CompletedWorkout
                )
            }
            pendingReconnectResend -> {
                val claimableIds = claimPersistedPendingIds(pendingHistoryIds)
                if (claimableIds.isNotEmpty()) {
                    pendingReconnectResend = false
                    val followUp = WearDirectHistorySyncClaim(
                        reason = WearWorkoutHistorySyncReason.ReconnectResend,
                        claimedHistoryIds = claimableIds
                    )
                    directSendInFlight = followUp
                    decisions += WearWorkoutHistorySyncDecision.StartDirect(followUp)
                }
            }
            pendingIntermediateSync -> {
                decisions += WearWorkoutHistorySyncDecision.ScheduleDebounce(
                    WearWorkoutHistorySyncReason.DebouncedIntermediate
                )
            }
        }

        return decisions
    }

    fun claimWorkerRetryBatch(pendingHistoryIds: Set<UUID>): WearWorkerRetryClaim? {
        releaseStaleClaimsIfIdle()
        val claimableIds = when {
            reservedWorkerRetryHistoryIds.isNotEmpty() ->
                reservedWorkerRetryHistoryIds.intersect(pendingHistoryIds)
            else -> claimPersistedPendingIds(pendingHistoryIds)
        }
        if (claimableIds.isEmpty()) {
            return null
        }

        reservedWorkerRetryHistoryIds.removeAll(claimableIds)
        claimedHistoryIds += claimableIds
        workerRetryInFlightIds = claimableIds
        return WearWorkerRetryClaim(
            reason = WearWorkoutHistorySyncReason.WorkerRetry,
            claimedHistoryIds = claimableIds
        )
    }

    fun completeWorkerRetryBatch(
        claim: WearWorkerRetryClaim,
        failedHistoryIds: Set<UUID>
    ): WearWorkoutHistorySyncDecision {
        workerRetryInFlightIds = emptySet()
        val succeededHistoryIds = claim.claimedHistoryIds - failedHistoryIds
        claimedHistoryIds.removeAll(succeededHistoryIds)
        claimedHistoryIds.removeAll(failedHistoryIds)
        reservedWorkerRetryHistoryIds.removeAll(succeededHistoryIds)
        if (failedHistoryIds.isEmpty()) {
            reservedWorkerRetryHistoryIds.removeAll(claim.claimedHistoryIds)
            return WearWorkoutHistorySyncDecision.None
        }
        reservedWorkerRetryHistoryIds += failedHistoryIds
        return WearWorkoutHistorySyncDecision.EnqueueWorker(
            reason = WearWorkoutHistorySyncReason.WorkerRetry
        )
    }

    fun cancelInFlightIntermediateSync(): WearDirectHistorySyncClaim? {
        val claim = directSendInFlight
        if (
            claim?.reason != WearWorkoutHistorySyncReason.DebouncedIntermediate ||
            claim.claimedHistoryIds.isNotEmpty()
        ) {
            return null
        }
        directSendInFlight = null
        return claim
    }

    private fun releaseStaleClaimsIfIdle() {
        if (directSendInFlight == null && workerRetryInFlightIds.isEmpty()) {
            claimedHistoryIds.clear()
        }
    }

    private fun startPendingCompletedDirect(
        reason: WearWorkoutHistorySyncReason
    ): WearWorkoutHistorySyncDecision {
        val idsToClaim = pendingCompletedHistoryIds
            .filterNot { it in claimedHistoryIds || it in reservedWorkerRetryHistoryIds }
            .toSet()
        if (idsToClaim.isEmpty()) {
            return WearWorkoutHistorySyncDecision.None
        }
        claimedHistoryIds += idsToClaim
        pendingCompletedHistoryIds.removeAll(idsToClaim)
        val claim = WearDirectHistorySyncClaim(reason = reason, claimedHistoryIds = idsToClaim)
        directSendInFlight = claim
        return WearWorkoutHistorySyncDecision.StartDirect(claim)
    }

    private fun claimPersistedPendingIds(pendingHistoryIds: Set<UUID>): Set<UUID> {
        val claimableIds = pendingHistoryIds
            .filterNot {
                it in claimedHistoryIds ||
                    it in reservedWorkerRetryHistoryIds ||
                    it in pendingCompletedHistoryIds
            }
            .toSet()
        if (claimableIds.isNotEmpty()) {
            claimedHistoryIds += claimableIds
        }
        return claimableIds
    }

    private fun hasClaimablePersistedPendingIds(pendingHistoryIds: Set<UUID>): Boolean {
        return pendingHistoryIds.any {
            it !in claimedHistoryIds &&
                it !in reservedWorkerRetryHistoryIds &&
                it !in pendingCompletedHistoryIds
        }
    }
}

internal object WearOutboundWorkoutHistorySyncCoordinator {
    private val state = WearOutboundWorkoutHistorySyncCoordinatorState()

    @Synchronized
    fun hasPendingSyncWork(): Boolean = state.hasPendingSyncWork()

    @Synchronized
    fun requestDebouncedIntermediateSync(): WearWorkoutHistorySyncDecision =
        state.requestDebouncedIntermediateSync()

    @Synchronized
    fun requestCompletedWorkoutSync(historyId: UUID?): WearWorkoutHistorySyncDecision =
        state.requestCompletedWorkoutSync(historyId)

    @Synchronized
    fun consumeDebouncedIntermediateSync(): WearWorkoutHistorySyncDecision =
        state.consumeDebouncedIntermediateSync()

    @Synchronized
    fun runStartupResend(pendingHistoryIds: Set<UUID>): WearWorkoutHistorySyncDecision =
        state.runStartupResend(pendingHistoryIds)

    @Synchronized
    fun notifyPhoneReconnect(pendingHistoryIds: Set<UUID>): WearWorkoutHistorySyncDecision =
        state.notifyPhoneReconnect(pendingHistoryIds)

    @Synchronized
    fun notifyLifecycleFlush(
        source: WearWorkoutLifecycleFlushSource,
        pendingHistoryIds: Set<UUID>,
        allowIntermediateSync: Boolean
    ): WearWorkoutHistorySyncDecision =
        state.notifyLifecycleFlush(source, pendingHistoryIds, allowIntermediateSync)

    @Synchronized
    fun completeDirectSend(
        claim: WearDirectHistorySyncClaim,
        success: Boolean,
        pendingHistoryIds: Set<UUID>
    ): List<WearWorkoutHistorySyncDecision> =
        state.completeDirectSend(claim, success, pendingHistoryIds)

    @Synchronized
    fun claimWorkerRetryBatch(pendingHistoryIds: Set<UUID>): WearWorkerRetryClaim? =
        state.claimWorkerRetryBatch(pendingHistoryIds)

    @Synchronized
    fun completeWorkerRetryBatch(
        claim: WearWorkerRetryClaim,
        failedHistoryIds: Set<UUID>
    ): WearWorkoutHistorySyncDecision =
        state.completeWorkerRetryBatch(claim, failedHistoryIds)

    @Synchronized
    fun cancelInFlightIntermediateSync(): WearDirectHistorySyncClaim? =
        state.cancelInFlightIntermediateSync()
}
