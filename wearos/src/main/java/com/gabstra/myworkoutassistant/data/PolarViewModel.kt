package com.gabstra.myworkoutassistant.data

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.polar.sdk.api.PolarBleApi
import com.polar.sdk.api.PolarBleApiCallback
import com.polar.sdk.api.PolarBleApiDefaultImpl
import com.polar.sdk.api.errors.PolarInvalidArgument
import com.polar.sdk.api.model.PolarDeviceInfo
import com.polar.sdk.api.model.PolarHrData
import io.reactivex.rxjava3.android.schedulers.AndroidSchedulers
import io.reactivex.rxjava3.disposables.CompositeDisposable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.UUID

class PolarViewModel(applicationContext: Context, deviceId: String) : ViewModel() {
    private val deviceId = deviceId

    private val api: PolarBleApi = PolarBleApiDefaultImpl.defaultImplementation(applicationContext,
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

    private val _deviceConnectionState = MutableStateFlow<PolarDeviceInfo?>(null)
    val deviceConnectionState = _deviceConnectionState.asStateFlow()

    private val _batteryLevelState = MutableStateFlow<Int?>(null)
    val batteryLevelState = _batteryLevelState.asStateFlow()

    private val _bluetoothEnabledState = MutableStateFlow<Boolean>(false)
    val bluetoothEnabledState = _bluetoothEnabledState.asStateFlow()

    private val disposables = CompositeDisposable()

    init {
        val enableSdkLogs = true
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
                Log.d("MyApp", "CONNECTED: ${polarDeviceInfo.deviceId}")
                startHrStreaming(polarDeviceInfo.deviceId)
                viewModelScope.launch {
                    _deviceConnectionState.value = polarDeviceInfo
                }
            }

            override fun deviceConnecting(polarDeviceInfo: PolarDeviceInfo) {}

            override fun deviceDisconnected(polarDeviceInfo: PolarDeviceInfo) {
                Log.d("MyApp", "DISCONNECTED: ${polarDeviceInfo.deviceId}")
                viewModelScope.launch {
                    _deviceConnectionState.value = null
                }
            }

            override fun bleSdkFeatureReady(identifier: String, feature: PolarBleApi.PolarBleSdkFeature) {}

            override fun disInformationReceived(identifier: String, uuid: UUID, value: String) {}

            override fun batteryLevelReceived(identifier: String, level: Int) {
                viewModelScope.launch {
                    _batteryLevelState.value = level
                }
            }
        })
    }

    fun connectToDevice() {
        viewModelScope.launch {
            try {
                Log.d("MyApp", "Connecting to device: $deviceId")
                api.connectToDevice(deviceId)
            } catch (e: Exception) {
                Log.e("MyApp", "Error connecting to device: $e")
            }
        }
    }

    private val _hrDataState = MutableStateFlow<List<Int>?>(null)
    val hrDataState = _hrDataState.asStateFlow()

    private fun startHrStreaming(deviceId: String) {
        viewModelScope.launch {
            try {
                val disposable = api.startHrStreaming(deviceId)
                    .observeOn(AndroidSchedulers.mainThread())
                    .subscribe(
                        { hrData: PolarHrData ->
                            _hrDataState.value = hrData.samples.map { it.hr }
                        },
                        { error: Throwable ->
                            Log.e("MyApp", "HR stream failed. Reason $error")
                        },
                        { Log.d("MyApp", "HR stream complete") }
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

class PolarViewModelFactory(private val applicationContext: Context, private val deviceId: String) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(PolarViewModel::class.java)) {
            @Suppress("UNCHECKED_CAST")
            return PolarViewModel(applicationContext,deviceId) as T
        }
        throw IllegalArgumentException("Unknown ViewModel class")
    }
}