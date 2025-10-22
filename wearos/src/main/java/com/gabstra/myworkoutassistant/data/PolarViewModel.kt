package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.util.Log
import android.widget.Toast
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.polar.androidcommunications.api.ble.model.DisInfo
import com.polar.sdk.api.PolarBleApi
import com.polar.sdk.api.PolarBleApiCallback
import com.polar.sdk.api.PolarBleApiDefaultImpl
import com.polar.sdk.api.model.PolarDeviceInfo
import com.polar.sdk.api.model.PolarHealthThermometerData
import io.reactivex.rxjava3.android.schedulers.AndroidSchedulers
import io.reactivex.rxjava3.core.Completable
import io.reactivex.rxjava3.core.Flowable
import io.reactivex.rxjava3.disposables.CompositeDisposable
import io.reactivex.rxjava3.schedulers.Schedulers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

class PolarViewModel : ViewModel() {
    private lateinit var deviceId: String

    private lateinit var api: PolarBleApi

    private val _deviceConnectionState = MutableStateFlow<PolarDeviceInfo?>(null)
    val deviceConnectionState = _deviceConnectionState.asStateFlow()

    private val _batteryLevelState = MutableStateFlow<Int?>(null)
    val batteryLevelState = _batteryLevelState.asStateFlow()

    private val _bluetoothEnabledState = MutableStateFlow<Boolean>(false)
    val bluetoothEnabledState = _bluetoothEnabledState.asStateFlow()

    private val disposables = CompositeDisposable()

    private val _hasBeenInitialized = MutableStateFlow<Boolean>(false)

    val hasBeenInitialized = _hasBeenInitialized.asStateFlow()

    fun initialize(applicationContext: Context, deviceId: String){
        _hasBeenInitialized.value = true

        this.deviceId = deviceId
        api = PolarBleApiDefaultImpl.defaultImplementation(applicationContext,
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

        api.setAutomaticReconnection(true);
        api.setMtu(70)

        val enableSdkLogs = false
        if(enableSdkLogs) {
            api.setApiLogger { s: String -> Log.d("MyApp", s) }
        }

        api.setApiCallback(object : PolarBleApiCallback() {
            override fun blePowerStateChanged(powered: Boolean) {
                viewModelScope.launch {
                    _bluetoothEnabledState.value = powered
                }
            }

            override fun deviceConnected(polarDeviceInfo: PolarDeviceInfo) {
                startHrStreaming(polarDeviceInfo.deviceId)
                viewModelScope.launch {
                    _deviceConnectionState.value = polarDeviceInfo
                }
            }

            override fun deviceConnecting(polarDeviceInfo: PolarDeviceInfo) {
            }

            override fun deviceDisconnected(polarDeviceInfo: PolarDeviceInfo) {
                Toast.makeText(applicationContext, "Polar device disconnected", Toast.LENGTH_SHORT).show()
                viewModelScope.launch {
                    _deviceConnectionState.value = null
                }
            }

            override fun disInformationReceived(
                identifier: String,
                disInfo: DisInfo
            ) {}

            override fun bleSdkFeatureReady(identifier: String, feature: PolarBleApi.PolarBleSdkFeature) {}

            override fun disInformationReceived(identifier: String, uuid: UUID, value: String) {}
            override fun htsNotificationReceived(
                identifier: String,
                data: PolarHealthThermometerData
            ) {
            }

            override fun batteryLevelReceived(identifier: String, level: Int) {
                Toast.makeText(applicationContext, "Polar device connected - Battery level: $level%", Toast.LENGTH_SHORT).show()
                viewModelScope.launch {
                    _batteryLevelState.value = level
                }
            }
        })
    }

    fun connectToDevice() {
        viewModelScope.launch {
            try {
                api.connectToDevice(deviceId)
            } catch (e: Exception) {
                Log.e("MyApp", "Error connecting to device ${deviceId}: $e")
            }
        }
    }

    fun disconnectFromDevice() {
        viewModelScope.launch {
            try {
                disposables.clear()
                api.disconnectFromDevice(deviceId)
                api.shutDown()
            } catch (e: Exception) {
                Log.e("MyApp", "Error disconnecting from device ${deviceId}: $e")
            }
        }
    }

    private val _hrBpm = MutableStateFlow<Int?>(null)
    val hrBpm = _hrBpm.asStateFlow()

    fun foregroundEntered() {
        api.foregroundEntered()
    }

    private fun startHrStreaming(deviceId: String) {
        val staleSec = 15L

        viewModelScope.launch {
            try {
                val disposable = api.startHrStreaming(deviceId)
                    .timeout(staleSec, TimeUnit.SECONDS)
                    .retryWhen { errors ->
                        errors.flatMap { t ->
                            if (t is TimeoutException) {
                                Log.w("MyApp", "HR stale > ${staleSec}s: reconnecting…")

                            }

                            Completable.fromAction {
                                try { api.disconnectFromDevice(deviceId) } catch (_: Exception) {}
                                api.connectToDevice(deviceId)
                            }
                            .andThen(api.waitForConnection(deviceId)
                            .timeout(20, TimeUnit.SECONDS))
                            .andThen(Flowable.timer(2, TimeUnit.SECONDS)) // small backoff
                        }
                    }
                    .subscribeOn(Schedulers.io())
                    .observeOn(AndroidSchedulers.mainThread())          // UI updates only
                    .doOnNext { hrData ->
                        _hrBpm.value = hrData.samples
                            .map { if (it.correctedHr > 0) it.correctedHr else it.hr }
                            .average().toInt()
                    }
                    .subscribe(
                        { /* handled in doOnNext */ },
                        { e -> Log.e("MyApp", "HR stream error: $e") }
                    )
                disposables.add(disposable)
            } catch (e: Exception) {
                Log.e("MyApp", "Error starting HR streaming: $e")
            }
        }
    }

    override fun onCleared() {
        super.onCleared()

        disposables.dispose()
    }
}