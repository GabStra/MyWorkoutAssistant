package com.gabstra.myworkoutassistant.data

import com.gabstra.myworkoutassistant.shared.HeartRateSource
import org.junit.Assert.assertEquals
import org.junit.Test

class HeartRateRecoveryPlanTest {

    private val streaming = ExternalHeartRateConnectionState.Streaming(
        source = HeartRateSource.POLAR_BLE,
        message = "Streaming from your Polar device.",
    )
    private val error = ExternalHeartRateConnectionState.Error(
        source = HeartRateSource.POLAR_BLE,
        message = "Disconnected.",
    )

    @Test
    fun `fresh stream needs no recovery`() {
        assertEquals(
            HeartRateRecoveryAction.None,
            planHeartRateRecovery(
                connectionState = streaming,
                hasEverConnectedThisSession = true,
                heartRateIdleMs = 1_000L,
                hasReceivedSampleSinceConnect = true,
                retryDue = true,
            )
        )
    }

    @Test
    fun `silent stream past the stale threshold is dropped`() {
        assertEquals(
            HeartRateRecoveryAction.DropStaleLink,
            planHeartRateRecovery(
                connectionState = streaming,
                hasEverConnectedThisSession = true,
                heartRateIdleMs = HEART_RATE_STALE_AFTER_MS + 1,
                hasReceivedSampleSinceConnect = true,
                retryDue = false,
            )
        )
    }

    @Test
    fun `stream exactly at the threshold is still alive`() {
        assertEquals(
            HeartRateRecoveryAction.None,
            planHeartRateRecovery(
                connectionState = streaming,
                hasEverConnectedThisSession = true,
                heartRateIdleMs = HEART_RATE_STALE_AFTER_MS,
                hasReceivedSampleSinceConnect = true,
                retryDue = true,
            )
        )
    }

    @Test
    fun `ready link with no sample yet is not treated as stale`() {
        assertEquals(
            HeartRateRecoveryAction.None,
            planHeartRateRecovery(
                connectionState = streaming,
                hasEverConnectedThisSession = true,
                heartRateIdleMs = null,
                hasReceivedSampleSinceConnect = false,
                retryDue = true,
            )
        )
    }

    @Test
    fun `connected but never streaming is not recycled`() {
        // WHOOP with Broadcast HR off: GATT is up, no samples ever. Rescanning forever is worse
        // than staying connected and telling the user.
        listOf(
            ExternalHeartRateConnectionState.Connected(HeartRateSource.WHOOP_BLE, "Connected."),
            streaming,
        ).forEach { state ->
            assertEquals(
                state.toString(),
                HeartRateRecoveryAction.None,
                planHeartRateRecovery(
                    connectionState = state,
                    hasEverConnectedThisSession = true,
                    heartRateIdleMs = HEART_RATE_STALE_AFTER_MS * 10,
                    hasReceivedSampleSinceConnect = false,
                    retryDue = true,
                )
            )
        }
    }

    @Test
    fun `error after a successful connect is retried once due`() {
        assertEquals(
            HeartRateRecoveryAction.RetryConnection,
            planHeartRateRecovery(
                connectionState = error,
                hasEverConnectedThisSession = true,
                heartRateIdleMs = null,
                hasReceivedSampleSinceConnect = false,
                retryDue = true,
            )
        )
    }

    @Test
    fun `error before any successful connect is not retried`() {
        assertEquals(
            HeartRateRecoveryAction.None,
            planHeartRateRecovery(
                connectionState = error,
                hasEverConnectedThisSession = false,
                heartRateIdleMs = null,
                hasReceivedSampleSinceConnect = false,
                retryDue = true,
            )
        )
    }

    @Test
    fun `error waits for its backoff slot`() {
        assertEquals(
            HeartRateRecoveryAction.None,
            planHeartRateRecovery(
                connectionState = error,
                hasEverConnectedThisSession = true,
                heartRateIdleMs = null,
                hasReceivedSampleSinceConnect = false,
                retryDue = false,
            )
        )
    }

    @Test
    fun `idle and connecting states need no recovery`() {
        listOf(
            ExternalHeartRateConnectionState.Idle,
            ExternalHeartRateConnectionState.Connecting(HeartRateSource.POLAR_BLE, "Connecting..."),
        ).forEach { state ->
            assertEquals(
                state.toString(),
                HeartRateRecoveryAction.None,
                planHeartRateRecovery(
                    connectionState = state,
                    hasEverConnectedThisSession = true,
                    heartRateIdleMs = HEART_RATE_STALE_AFTER_MS * 10,
                    hasReceivedSampleSinceConnect = false,
                    retryDue = true,
                )
            )
        }
    }
}
