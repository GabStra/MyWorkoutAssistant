package com.gabstra.myworkoutassistant.heart_rate

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.screens.localizedLabel
import com.gabstra.myworkoutassistant.shared.ExternalHeartRateConfig
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.PolarHeartRateConfig
import com.polar.androidcommunications.api.ble.model.DisInfo
import com.polar.sdk.api.PolarBleApi
import com.polar.sdk.api.PolarBleApiCallback
import com.polar.sdk.api.PolarBleApiDefaultImpl
import com.polar.sdk.api.model.PolarDeviceInfo
import com.polar.sdk.api.model.PolarHealthThermometerData
import java.util.UUID
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

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
    private var hrStreamJob: Job? = null
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
                context.getString(
                    R.string.loc_configure_source_first,
                    source.localizedLabel(context),
                ),
            )
            return
        }
        if (!hasBluetoothPermission(context)) {
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                context.getString(
                    R.string.loc_bluetooth_permission_required,
                    source.localizedLabel(context),
                ),
            )
            return
        }

        releaseHrStream()
        mutableHeartRate.value = null
        mutableConnectionState.value = ExternalHeartRateConnectionState.Connecting(
            context.getString(R.string.loc_connecting_polar),
        )

        try {
            val api = polarApi ?: createPolarApi(context)
            api.connectToDevice(config.deviceId.trim())
        } catch (exception: Exception) {
            Log.e(Tag, "Unable to connect to Polar device ${config.deviceId}", exception)
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                context.getString(R.string.loc_couldnt_connect_polar),
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
            api.setApiCallback(createPolarApiCallback(generation, context))
            polarApi = api
        }
    }

    private fun createPolarApiCallback(
        generation: Int,
        context: Context,
    ) = object : PolarBleApiCallback() {
        override fun blePowerStateChanged(powered: Boolean) {
            if (!isCurrentApi(generation) || powered) return
            releaseHrStream()
            mutableHeartRate.value = null
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                context.getString(R.string.loc_bluetooth_unavailable),
            )
        }

        override fun deviceConnected(polarDeviceInfo: PolarDeviceInfo) {
            if (!isCurrentApi(generation)) return
            connectedDeviceLabel = polarDeviceInfo.name.ifBlank {
                source.localizedLabel(context)
            }
            mutableConnectionState.value = ExternalHeartRateConnectionState.Connecting(
                context.getString(
                    R.string.loc_starting_hr_stream,
                    connectedDeviceLabel,
                ),
            )
            startHrStreaming(polarDeviceInfo.deviceId, generation, context)
        }

        override fun deviceConnecting(polarDeviceInfo: PolarDeviceInfo) {
            if (!isCurrentApi(generation)) return
            val deviceLabel = polarDeviceInfo.name.ifBlank {
                source.localizedLabel(context)
            }
            mutableConnectionState.value = ExternalHeartRateConnectionState.Connecting(
                context.getString(R.string.loc_connecting_to_label, deviceLabel),
            )
        }

        override fun deviceDisconnected(polarDeviceInfo: PolarDeviceInfo) {
            if (!isCurrentApi(generation)) return
            releaseHrStream()
            mutableHeartRate.value = null
            connectedDeviceLabel = null
            val deviceLabel = polarDeviceInfo.name.ifBlank {
                source.localizedLabel(context)
            }
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                context.getString(R.string.loc_connection_lost_label, deviceLabel),
            )
        }

        override fun bleSdkFeatureReady(
            identifier: String,
            feature: PolarBleApi.PolarBleSdkFeature,
        ) = Unit

        override fun disInformationReceived(identifier: String, disInfo: DisInfo) = Unit

        override fun disInformationReceived(identifier: String, uuid: UUID, value: String) = Unit

        override fun htsNotificationReceived(
            identifier: String,
            data: PolarHealthThermometerData,
        ) = Unit
    }

    private fun startHrStreaming(
        deviceId: String,
        generation: Int,
        context: Context,
    ) {
        releaseHrStream()
        val api = polarApi ?: return
        // Polar SDK 8 exposes startHrStreaming as a coroutines Flow instead of a Flowable.
        hrStreamJob = viewModelScope.launch {
            try {
                api.startHrStreaming(deviceId).collect { hrData ->
                    if (!isCurrentApi(generation)) return@collect
                    val validSamples = hrData.samples.mapNotNull { sample ->
                        val beatsPerMinute = if (sample.correctedHr > 0) sample.correctedHr else sample.hr
                        beatsPerMinute.takeIf { it > 0 }
                    }
                    if (validSamples.isEmpty()) return@collect

                    mutableHeartRate.value = validSamples.average().toInt()
                    mutableConnectionState.value = ExternalHeartRateConnectionState.Streaming(
                        connectedDeviceLabel ?: source.localizedLabel(context),
                    )
                }
            } catch (exception: Exception) {
                if (!isCurrentApi(generation)) return@launch
                Log.e(Tag, "Polar heart-rate stream failed", exception)
                releaseHrStream()
                mutableHeartRate.value = null
                mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                    context.getString(R.string.loc_couldnt_stream_polar),
                )
            }
        }
    }

    private fun releaseHrStream() {
        hrStreamJob?.cancel()
        hrStreamJob = null
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
