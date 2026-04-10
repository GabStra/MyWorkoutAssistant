package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.util.Log
import android.widget.Toast
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.ExternalHeartRateConfig
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.PolarHeartRateConfig
import com.polar.androidcommunications.api.ble.model.DisInfo
import com.polar.sdk.api.PolarBleApi
import com.polar.sdk.api.PolarBleApiCallback
import com.polar.sdk.api.PolarBleApiDefaultImpl
import com.polar.sdk.api.model.PolarDeviceInfo
import com.polar.sdk.api.model.PolarHealthThermometerData
import io.reactivex.rxjava3.core.Flowable
import io.reactivex.rxjava3.disposables.CompositeDisposable
import io.reactivex.rxjava3.disposables.Disposable
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class PolarHrBpmSource(private val api: PolarBleApi) : HrBpmSource {
    override fun bpmStream(deviceId: String): Flowable<Int> =
        api.startHrStreaming(deviceId)
            .map { hrData ->
                hrData.samples
                    .map { if (it.correctedHr > 0) it.correctedHr else it.hr }
                    .average()
                    .toInt()
            }
}

class PolarViewModel : BaseExternalHeartRateViewModel(HeartRateSource.POLAR_BLE) {
    private var deviceId: String? = null
    private lateinit var api: PolarBleApi

    private val _deviceConnectionState = MutableStateFlow<PolarDeviceInfo?>(null)
    val deviceConnectionState = _deviceConnectionState.asStateFlow()

    private val _batteryLevelState = MutableStateFlow<Int?>(null)
    val batteryLevelState = _batteryLevelState.asStateFlow()

    private val _bluetoothEnabledState = MutableStateFlow(false)
    val bluetoothEnabledState = _bluetoothEnabledState.asStateFlow()

    private val disposables = CompositeDisposable()
    private var hrStreamDisposable: Disposable? = null
    private val isHrStreamingActive = AtomicBoolean(false)

    override fun hasUsableConfig(config: ExternalHeartRateConfig?): Boolean =
        (config as? PolarHeartRateConfig)?.deviceId?.isNotBlank() == true

    override fun onInitialize(config: ExternalHeartRateConfig) {
        val polarConfig = config as PolarHeartRateConfig
        applicationContext?.let { initializePolarApi(it, polarConfig.deviceId) }
    }

    override fun connectToConfiguredDevice(config: ExternalHeartRateConfig) {
        val polarConfig = config as? PolarHeartRateConfig ?: run {
            publishConnectionState(
                ExternalHeartRateConnectionState.MissingConfiguration(
                    source = source,
                    message = "Configure ${source.displayName()} in Settings first."
                )
            )
            return
        }

        if (!::api.isInitialized) {
            applicationContext?.let { initializePolarApi(it, polarConfig.deviceId) }
        }

        publishConnectionState(
            ExternalHeartRateConnectionState.Connecting(
                source = source,
                message = "Connecting to your Polar device..."
            )
        )

        viewModelScope.launch(appCeh) {
            try {
                api.connectToDevice(polarConfig.deviceId)
            } catch (exception: Exception) {
                Log.e("PolarViewModel", "Error connecting to device ${polarConfig.deviceId}", exception)
                publishConnectionState(
                    ExternalHeartRateConnectionState.Error(
                        source = source,
                        message = "Couldn't connect to your Polar device."
                    )
                )
            }
        }
    }

    override fun releaseDeviceResources() {
        publishHeartRate(null)
        clearHrStreamingState()
        disposables.clear()

        if (!::api.isInitialized) {
            deviceId = null
            _deviceConnectionState.value = null
            _batteryLevelState.value = null
            return
        }

        try {
            deviceId?.let { api.disconnectFromDevice(it) }
        } catch (exception: Exception) {
            Log.w("PolarViewModel", "Error disconnecting from device during release", exception)
        }

        try {
            api.shutDown()
        } catch (exception: Exception) {
            Log.w("PolarViewModel", "Error shutting down Polar API", exception)
        } finally {
            deviceId = null
            _deviceConnectionState.value = null
            _batteryLevelState.value = null
        }
    }

    override fun foregroundEntered() {
        if (::api.isInitialized) {
            api.foregroundEntered()
        }
    }

    private fun clearHrStreamingState() {
        hrStreamDisposable?.let { disposable ->
            if (!disposable.isDisposed) {
                disposable.dispose()
                disposables.remove(disposable)
            }
        }
        hrStreamDisposable = null
        isHrStreamingActive.set(false)
    }

    private fun initializePolarApi(applicationContext: Context, deviceId: String) {
        this.deviceId = deviceId
        api = PolarBleApiDefaultImpl.defaultImplementation(
            applicationContext,
            setOf(
                PolarBleApi.PolarBleSdkFeature.FEATURE_HR,
                PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_SDK_MODE,
                PolarBleApi.PolarBleSdkFeature.FEATURE_BATTERY_INFO,
                PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_H10_EXERCISE_RECORDING,
                PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_OFFLINE_RECORDING,
                PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_ONLINE_STREAMING,
                PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_DEVICE_TIME_SETUP,
                PolarBleApi.PolarBleSdkFeature.FEATURE_DEVICE_INFO,
                PolarBleApi.PolarBleSdkFeature.FEATURE_POLAR_LED_ANIMATION
            )
        )

        api.setAutomaticReconnection(true)
        api.setMtu(70)

        api.setApiCallback(object : PolarBleApiCallback() {
            override fun blePowerStateChanged(powered: Boolean) {
                viewModelScope.launch(appCeh) {
                    _bluetoothEnabledState.value = powered
                }
            }

            override fun deviceConnected(polarDeviceInfo: PolarDeviceInfo) {
                val deviceName = polarDeviceInfo.name
                markConnectedThisSession()
                publishConnectionState(
                    ExternalHeartRateConnectionState.Connected(
                        source = source,
                        message = "Connected to $deviceName.",
                        deviceLabel = deviceName
                    )
                )
                if (!isHrStreamingActive.get()) {
                    startHrStreaming(polarDeviceInfo.deviceId)
                }
                viewModelScope.launch(appCeh) {
                    _deviceConnectionState.value = polarDeviceInfo
                }
            }

            override fun deviceConnecting(polarDeviceInfo: PolarDeviceInfo) {
                val deviceName = polarDeviceInfo.name
                publishConnectionState(
                    ExternalHeartRateConnectionState.Connecting(
                        source = source,
                        message = "Connecting to $deviceName..."
                    )
                )
            }

            override fun deviceDisconnected(polarDeviceInfo: PolarDeviceInfo) {
                val deviceName = polarDeviceInfo.name
                clearHrStreamingState()
                viewModelScope.launch(appCeh) {
                    publishHeartRate(null)
                    _deviceConnectionState.value = null
                }
                if (!isReleaseInProgress && !isSessionSkipped) {
                    publishConnectionState(
                        ExternalHeartRateConnectionState.Error(
                            source = source,
                            message = "Disconnected from $deviceName."
                        )
                    )
                }
                viewModelScope.launch(appCeh) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(
                            applicationContext,
                            "Polar device disconnected.",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }
            }

            override fun disInformationReceived(identifier: String, disInfo: DisInfo) = Unit

            override fun bleSdkFeatureReady(
                identifier: String,
                feature: PolarBleApi.PolarBleSdkFeature,
            ) = Unit

            override fun disInformationReceived(identifier: String, uuid: UUID, value: String) = Unit

            override fun htsNotificationReceived(
                identifier: String,
                data: PolarHealthThermometerData,
            ) = Unit

            override fun batteryLevelReceived(identifier: String, level: Int) {
                viewModelScope.launch(appCeh) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(
                            applicationContext,
                            "Polar connected. Battery: $level%",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                    _batteryLevelState.value = level
                }
            }
        })
    }

    private fun startHrStreaming(deviceId: String) {
        if (!isHrStreamingActive.compareAndSet(false, true)) {
            Log.d("PolarViewModel", "HR stream already active, skipping duplicate start")
            return
        }

        hrStreamDisposable?.let { disposable ->
            if (!disposable.isDisposed) {
                disposable.dispose()
                disposables.remove(disposable)
            }
        }
        hrStreamDisposable = null

        val stream = PolarHrBpmSource(api).bpmStream(deviceId)

        val disposable = stream
            .subscribeOn(io.reactivex.rxjava3.schedulers.Schedulers.io())
            .observeOn(io.reactivex.rxjava3.android.schedulers.AndroidSchedulers.mainThread())
            .doOnTerminate { isHrStreamingActive.set(false) }
            .doFinally { isHrStreamingActive.set(false) }
            .subscribe(
                { bpm ->
                    publishHeartRate(bpm)
                    publishConnectionState(
                        ExternalHeartRateConnectionState.Streaming(
                            source = source,
                            message = "Streaming from your Polar device.",
                            deviceLabel = deviceId
                        )
                    )
                },
                { exception ->
                    Log.e("PolarViewModel", "HR stream error", exception)
                    publishHeartRate(null)
                    if (!isSessionSkipped) {
                        publishConnectionState(
                            ExternalHeartRateConnectionState.Error(
                                source = source,
                                message = "Couldn't stream heart rate from your Polar device."
                            )
                        )
                    }
                    isHrStreamingActive.set(false)
                }
            )
        hrStreamDisposable = disposable
        disposables.add(disposable)
    }
}
