package com.gabstra.myworkoutassistant.data

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.shared.ExternalHeartRateConfig
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import kotlin.coroutines.EmptyCoroutineContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

internal const val HEART_RATE_RECOVERY_TICK_MS = 5_000L
internal const val HEART_RATE_STALE_AFTER_MS = 20_000L
internal const val HEART_RATE_RETRY_BASE_DELAY_MS = 5_000L
internal const val HEART_RATE_RETRY_MAX_DELAY_MS = 60_000L

internal enum class HeartRateRecoveryAction { None, DropStaleLink, RetryConnection }

/** Decides whether a paired HR link needs recovery; retries only after a first successful connect. */
internal fun planHeartRateRecovery(
    connectionState: ExternalHeartRateConnectionState,
    hasEverConnectedThisSession: Boolean,
    heartRateIdleMs: Long?,
    hasReceivedSampleSinceConnect: Boolean,
    retryDue: Boolean,
): HeartRateRecoveryAction = when {
    // Only treat a link as stale if it was streaming and then went quiet. A strap that is
    // connected but has never sent a sample (e.g. WHOOP with Broadcast HR off) would otherwise
    // be torn down and rescanned every 20 s forever.
    connectionState.isReady &&
        hasReceivedSampleSinceConnect &&
        heartRateIdleMs != null &&
        heartRateIdleMs > HEART_RATE_STALE_AFTER_MS -> HeartRateRecoveryAction.DropStaleLink

    connectionState is ExternalHeartRateConnectionState.Error &&
        hasEverConnectedThisSession &&
        retryDue -> HeartRateRecoveryAction.RetryConnection

    else -> HeartRateRecoveryAction.None
}

sealed class ExternalHeartRateConnectionState {
    data object Idle : ExternalHeartRateConnectionState()
    data class Connecting(val source: HeartRateSource, val message: String) :
        ExternalHeartRateConnectionState()

    data class Connected(
        val source: HeartRateSource,
        val message: String,
        val deviceLabel: String? = null,
    ) : ExternalHeartRateConnectionState()

    data class Streaming(
        val source: HeartRateSource,
        val message: String,
        val deviceLabel: String? = null,
    ) : ExternalHeartRateConnectionState()

    data class MissingConfiguration(val source: HeartRateSource, val message: String) :
        ExternalHeartRateConnectionState()

    data class Error(val source: HeartRateSource, val message: String) :
        ExternalHeartRateConnectionState()

    data class Skipped(val source: HeartRateSource, val message: String) :
        ExternalHeartRateConnectionState()
}

val ExternalHeartRateConnectionState.isReady: Boolean
    get() = this is ExternalHeartRateConnectionState.Connected ||
        this is ExternalHeartRateConnectionState.Streaming

interface ExternalHeartRateDeviceController {
    val source: HeartRateSource
    val connectionState: StateFlow<ExternalHeartRateConnectionState>
    val hrBpm: StateFlow<Int?>
    val hasBeenInitialized: StateFlow<Boolean>
    val isSkippedForSession: StateFlow<Boolean>
    val hasEverConnectedThisSession: StateFlow<Boolean>

    fun initialize(context: Context, config: ExternalHeartRateConfig?)
    fun connectToDevice()
    fun retryConnection()
    fun skipConnectionForSession()
    fun disconnectFromDevice()
    fun foregroundEntered() = Unit
}

abstract class BaseExternalHeartRateViewModel(
    final override val source: HeartRateSource,
) : ViewModel(), ExternalHeartRateDeviceController {
    protected var applicationContext: Context? = null
    protected var currentConfig: ExternalHeartRateConfig? = null

    private var releaseInProgress = false
    private var connectionAttemptId = 0L
    private var heartRateLastReceivedAtMs = 0L
    private var receivedSampleSinceConnect = false
    private var nextRetryAtMs = 0L
    private var retryDelayMs = HEART_RATE_RETRY_BASE_DELAY_MS

    protected val appCeh
        get() = (applicationContext as? MyApplication)?.coroutineExceptionHandler ?: EmptyCoroutineContext

    private val _connectionState =
        MutableStateFlow<ExternalHeartRateConnectionState>(ExternalHeartRateConnectionState.Idle)
    final override val connectionState = _connectionState.asStateFlow()

    private val _hrBpm = MutableStateFlow<Int?>(null)
    final override val hrBpm = _hrBpm.asStateFlow()

    private val _hasBeenInitialized = MutableStateFlow(false)
    final override val hasBeenInitialized = _hasBeenInitialized.asStateFlow()

    private val _isSkippedForSession = MutableStateFlow(false)
    final override val isSkippedForSession = _isSkippedForSession.asStateFlow()

    private val _hasEverConnectedThisSession = MutableStateFlow(false)
    final override val hasEverConnectedThisSession = _hasEverConnectedThisSession.asStateFlow()

    init {
        viewModelScope.launch(appCeh) {
            while (true) {
                delay(HEART_RATE_RECOVERY_TICK_MS)
                evaluateConnectionRecovery()
            }
        }
    }

    protected val isSessionSkipped: Boolean
        get() = _isSkippedForSession.value

    protected val isReleaseInProgress: Boolean
        get() = releaseInProgress

    final override fun initialize(context: Context, config: ExternalHeartRateConfig?) {
        connectionAttemptId++
        releaseDeviceConnection()
        applicationContext = context.applicationContext
        currentConfig = config
        _hasBeenInitialized.value = true
        _isSkippedForSession.value = false
        _hasEverConnectedThisSession.value = false
        _hrBpm.value = null
        resetRecoverySchedule()

        if (!hasUsableConfig(config)) {
            _connectionState.value = ExternalHeartRateConnectionState.MissingConfiguration(
                source = source,
                message = "Configure ${source.displayName()} in Settings first."
            )
            return
        }

        onInitialize(config!!)
        _connectionState.value = ExternalHeartRateConnectionState.Idle
    }

    protected open fun onInitialize(config: ExternalHeartRateConfig) = Unit

    final override fun connectToDevice() {
        if (isSessionSkipped) {
            return
        }

        // Already connected/connecting: re-issuing connect on a live link is what makes the
        // link drop on every screen wake.
        val state = _connectionState.value
        if (state.isReady || state is ExternalHeartRateConnectionState.Connecting) {
            return
        }

        val config = currentConfig
        if (!hasUsableConfig(config)) {
            _connectionState.value = ExternalHeartRateConnectionState.MissingConfiguration(
                source = source,
                message = "Configure ${source.displayName()} in Settings first."
            )
            return
        }

        heartRateLastReceivedAtMs = nowMs()
        receivedSampleSinceConnect = false
        val attemptId = ++connectionAttemptId
        connectToConfiguredDevice(config!!)
        viewModelScope.launch(appCeh) {
            delay(CONNECTION_TIMEOUT_MS)
            if (
                attemptId == connectionAttemptId &&
                !isSessionSkipped &&
                _connectionState.value is ExternalHeartRateConnectionState.Connecting
            ) {
                releaseDeviceConnection()
                _connectionState.value = ExternalHeartRateConnectionState.Error(
                    source = source,
                    message = "Couldn't connect to ${source.displayName()}.",
                )
            }
        }
    }

    final override fun retryConnection() {
        _isSkippedForSession.value = false
        connectToDevice()
    }

    final override fun skipConnectionForSession() {
        connectionAttemptId++
        _isSkippedForSession.value = true
        _hrBpm.value = null
        resetRecoverySchedule()
        releaseDeviceConnection()
        _connectionState.value = ExternalHeartRateConnectionState.Skipped(
            source = source,
            message = "${source.displayName()} skipped for this workout."
        )
    }

    final override fun disconnectFromDevice() {
        connectionAttemptId++
        val skipped = isSessionSkipped
        resetRecoverySchedule()
        releaseDeviceConnection()
        _hrBpm.value = null
        _connectionState.value = if (skipped) {
            ExternalHeartRateConnectionState.Skipped(
                source = source,
                message = "${source.displayName()} skipped for this workout."
            )
        } else {
            ExternalHeartRateConnectionState.Idle
        }
    }

    protected fun publishHeartRate(bpm: Int?) {
        if (bpm != null) {
            heartRateLastReceivedAtMs = nowMs()
            receivedSampleSinceConnect = true
        }
        _hrBpm.value = bpm
    }

    private fun evaluateConnectionRecovery() {
        if (isReleaseInProgress || isSessionSkipped || !hasUsableConfig(currentConfig)) {
            return
        }
        if (_connectionState.value.isReady) {
            retryDelayMs = HEART_RATE_RETRY_BASE_DELAY_MS
        }
        val now = nowMs()
        val idleMs = heartRateLastReceivedAtMs
            .takeIf { it != 0L }
            ?.let { now - it }
        when (
            planHeartRateRecovery(
                connectionState = _connectionState.value,
                hasEverConnectedThisSession = _hasEverConnectedThisSession.value,
                heartRateIdleMs = idleMs,
                hasReceivedSampleSinceConnect = receivedSampleSinceConnect,
                retryDue = now >= nextRetryAtMs,
            )
        ) {
            HeartRateRecoveryAction.None -> Unit

            HeartRateRecoveryAction.DropStaleLink -> {
                // Link is up but the device stopped producing samples: tear it down so the
                // retry below rebuilds it instead of streaming silence for the rest of the set.
                releaseDeviceConnection()
                heartRateLastReceivedAtMs = 0L
                receivedSampleSinceConnect = false
                _connectionState.value = ExternalHeartRateConnectionState.Error(
                    source = source,
                    message = "Lost the heart-rate signal from ${source.displayName()}.",
                )
                scheduleNextRetry(now)
            }

            HeartRateRecoveryAction.RetryConnection -> {
                scheduleNextRetry(now)
                connectToDevice()
            }
        }
    }

    private fun scheduleNextRetry(now: Long) {
        nextRetryAtMs = now + retryDelayMs
        retryDelayMs = minOf(retryDelayMs * 2, HEART_RATE_RETRY_MAX_DELAY_MS)
    }

    private fun resetRecoverySchedule() {
        heartRateLastReceivedAtMs = 0L
        receivedSampleSinceConnect = false
        nextRetryAtMs = 0L
        retryDelayMs = HEART_RATE_RETRY_BASE_DELAY_MS
    }

    private fun nowMs(): Long = System.nanoTime() / 1_000_000

    protected fun publishConnectionState(state: ExternalHeartRateConnectionState) {
        if (!isSessionSkipped || state is ExternalHeartRateConnectionState.Skipped) {
            _connectionState.value = state
        }
    }

    protected fun markConnectedThisSession() {
        _hasEverConnectedThisSession.value = true
    }

    private fun releaseDeviceConnection() {
        releaseInProgress = true
        try {
            releaseDeviceResources()
        } finally {
            releaseInProgress = false
        }
    }

    protected abstract fun hasUsableConfig(config: ExternalHeartRateConfig?): Boolean
    protected abstract fun connectToConfiguredDevice(config: ExternalHeartRateConfig)
    protected abstract fun releaseDeviceResources()

    override fun onCleared() {
        connectionAttemptId++
        releaseDeviceConnection()
    }

    private companion object {
        const val CONNECTION_TIMEOUT_MS = 15_000L
    }
}
