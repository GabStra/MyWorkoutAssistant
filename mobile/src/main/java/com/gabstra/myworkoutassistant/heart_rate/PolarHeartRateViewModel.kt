package com.gabstra.myworkoutassistant.heart_rate

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import com.gabstra.myworkoutassistant.shared.ExternalHeartRateConfig
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.PolarHeartRateConfig
import com.polar.androidcommunications.api.ble.model.DisInfo
import com.polar.sdk.api.PolarBleApi
import com.polar.sdk.api.PolarBleApiCallback
import com.polar.sdk.api.PolarBleApiDefaultImpl
import com.polar.sdk.api.model.PolarDeviceInfo
import com.polar.sdk.api.model.PolarHealthThermometerData
import io.reactivex.rxjava3.disposables.Disposable
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

class PolarHeartRateViewModel : ViewModel(), ExternalHeartRateController {
    override val source = HeartRateSource.POLAR_BLE

    private val mutableConnectionState =
        MutableStateFlow<ExternalHeartRateConnectionState>(ExternalHeartRateConnectionState.Idle)
    override val connectionState = mutableConnectionState.asStateFlow()

    private val mutableHeartRate = MutableStateFlow<Int?>(null)
    override val heartRate = mutableHeartRate.asStateFlow()

    private var applicationContext: Context? = null
    private var polarConfig: PolarHeartRateConfig? = null
    private var polarApi: PolarBleApi? = null
    private var hrStreamDisposable: Disposable? = null
    private var connectedDeviceLabel: String? = null
    private var apiGeneration = 0

    override fun initialize(context: Context, config: ExternalHeartRateConfig?) {
        disconnect()
        applicationContext = context.applicationContext
        polarConfig = config as? PolarHeartRateConfig
    }

    override fun connect() {
        val context = applicationContext ?: return
        val config = polarConfig
        if (config == null || config.deviceId.isBlank()) {
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                "Configure ${source.displayName()} in Settings first.",
            )
            return
        }
        if (!hasBluetoothPermission(context)) {
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                "Bluetooth permission is required to connect to ${source.displayName()}.",
            )
            return
        }

        releaseHrStream()
        mutableHeartRate.value = null
        mutableConnectionState.value = ExternalHeartRateConnectionState.Connecting(
            "Connecting to your Polar device…",
        )

        try {
            val api = polarApi ?: createPolarApi(context)
            api.connectToDevice(config.deviceId.trim())
        } catch (exception: Exception) {
            Log.e(Tag, "Unable to connect to Polar device ${config.deviceId}", exception)
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                "Couldn't connect to your Polar device.",
            )
        }
    }

    override fun disconnect() {
        apiGeneration += 1
        releaseHrStream()
        mutableHeartRate.value = null
        connectedDeviceLabel = null

        val api = polarApi
        val deviceId = polarConfig?.deviceId?.trim().orEmpty()
        if (api != null) {
            if (deviceId.isNotEmpty()) {
                runCatching { api.disconnectFromDevice(deviceId) }
                    .onFailure { exception ->
                        Log.w(Tag, "Unable to disconnect from Polar device $deviceId", exception)
                    }
            }
            runCatching { api.shutDown() }
                .onFailure { exception -> Log.w(Tag, "Unable to shut down Polar SDK", exception) }
        }

        polarApi = null
        mutableConnectionState.value = ExternalHeartRateConnectionState.Idle
    }

    private fun createPolarApi(context: Context): PolarBleApi {
        val generation = apiGeneration + 1
        apiGeneration = generation
        return PolarBleApiDefaultImpl.defaultImplementation(
            context,
            setOf(PolarBleApi.PolarBleSdkFeature.FEATURE_HR),
        ).also { api ->
            api.setAutomaticReconnection(true)
            api.setApiCallback(createPolarApiCallback(generation))
            polarApi = api
        }
    }

    private fun createPolarApiCallback(generation: Int) = object : PolarBleApiCallback() {
        override fun blePowerStateChanged(powered: Boolean) {
            if (!isCurrentApi(generation) || powered) return
            releaseHrStream()
            mutableHeartRate.value = null
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                "Bluetooth is unavailable.",
            )
        }

        override fun deviceConnected(polarDeviceInfo: PolarDeviceInfo) {
            if (!isCurrentApi(generation)) return
            connectedDeviceLabel = polarDeviceInfo.name.ifBlank { source.displayName() }
            mutableConnectionState.value = ExternalHeartRateConnectionState.Connecting(
                "Starting heart-rate stream from ${connectedDeviceLabel}…",
            )
            startHrStreaming(polarDeviceInfo.deviceId, generation)
        }

        override fun deviceConnecting(polarDeviceInfo: PolarDeviceInfo) {
            if (!isCurrentApi(generation)) return
            val deviceLabel = polarDeviceInfo.name.ifBlank { source.displayName() }
            mutableConnectionState.value = ExternalHeartRateConnectionState.Connecting(
                "Connecting to $deviceLabel…",
            )
        }

        override fun deviceDisconnected(polarDeviceInfo: PolarDeviceInfo) {
            if (!isCurrentApi(generation)) return
            releaseHrStream()
            mutableHeartRate.value = null
            connectedDeviceLabel = null
            val deviceLabel = polarDeviceInfo.name.ifBlank { source.displayName() }
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                "Connection to $deviceLabel was lost.",
            )
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
    }

    private fun startHrStreaming(deviceId: String, generation: Int) {
        releaseHrStream()
        val api = polarApi ?: return
        hrStreamDisposable = api.startHrStreaming(deviceId)
            .subscribe(
                { hrData ->
                    if (!isCurrentApi(generation)) return@subscribe
                    val validSamples = hrData.samples.mapNotNull { sample ->
                        val beatsPerMinute = if (sample.correctedHr > 0) sample.correctedHr else sample.hr
                        beatsPerMinute.takeIf { it > 0 }
                    }
                    if (validSamples.isEmpty()) return@subscribe

                    mutableHeartRate.value = validSamples.average().toInt()
                    mutableConnectionState.value = ExternalHeartRateConnectionState.Streaming(
                        connectedDeviceLabel ?: source.displayName(),
                    )
                },
                { exception ->
                    if (!isCurrentApi(generation)) return@subscribe
                    Log.e(Tag, "Polar heart-rate stream failed", exception)
                    releaseHrStream()
                    mutableHeartRate.value = null
                    mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                        "Couldn't stream heart rate from your Polar device.",
                    )
                },
            )
    }

    private fun releaseHrStream() {
        hrStreamDisposable?.dispose()
        hrStreamDisposable = null
    }

    private fun isCurrentApi(generation: Int): Boolean =
        generation == apiGeneration && polarApi != null

    override fun onCleared() {
        disconnect()
    }

    private companion object {
        const val Tag = "PolarHeartRateVM"
    }
}
