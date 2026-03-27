package com.gabstra.myworkoutassistant.data

import android.content.Context
import androidx.lifecycle.ViewModel
import com.gabstra.myworkoutassistant.MyApplication
import com.gabstra.myworkoutassistant.shared.ExternalHeartRateConfig
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import kotlin.coroutines.EmptyCoroutineContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

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

    protected val isSessionSkipped: Boolean
        get() = _isSkippedForSession.value

    protected val isReleaseInProgress: Boolean
        get() = releaseInProgress

    final override fun initialize(context: Context, config: ExternalHeartRateConfig?) {
        releaseDeviceConnection()
        applicationContext = context.applicationContext
        currentConfig = config
        _hasBeenInitialized.value = true
        _isSkippedForSession.value = false
        _hasEverConnectedThisSession.value = false
        _hrBpm.value = null

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

        val config = currentConfig
        if (!hasUsableConfig(config)) {
            _connectionState.value = ExternalHeartRateConnectionState.MissingConfiguration(
                source = source,
                message = "Configure ${source.displayName()} in Settings first."
            )
            return
        }

        connectToConfiguredDevice(config!!)
    }

    final override fun retryConnection() {
        _isSkippedForSession.value = false
        connectToDevice()
    }

    final override fun skipConnectionForSession() {
        _isSkippedForSession.value = true
        _hrBpm.value = null
        releaseDeviceConnection()
        _connectionState.value = ExternalHeartRateConnectionState.Skipped(
            source = source,
            message = "${source.displayName()} skipped for this workout."
        )
    }

    final override fun disconnectFromDevice() {
        val skipped = isSessionSkipped
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
        _hrBpm.value = bpm
    }

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
        releaseDeviceConnection()
        super.onCleared()
    }
}
