package com.gabstra.myworkoutassistant.data

import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.lifecycle.viewModelScope
import com.gabstra.myworkoutassistant.shared.ExternalHeartRateConfig
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.WhoopHeartRateConfig
import io.reactivex.rxjava3.core.BackpressureStrategy
import io.reactivex.rxjava3.core.Completable
import io.reactivex.rxjava3.core.Flowable
import io.reactivex.rxjava3.core.FlowableEmitter
import io.reactivex.rxjava3.disposables.Disposable
import io.reactivex.rxjava3.schedulers.Schedulers
import java.util.UUID
import kotlinx.coroutines.launch

class WhoopHeartRateViewModel : BaseExternalHeartRateViewModel(HeartRateSource.WHOOP_BLE) {
    private var whoopStreamDisposable: Disposable? = null
    private var whoopClient: WhoopBleClient? = null

    override fun hasUsableConfig(config: ExternalHeartRateConfig?): Boolean =
        config is WhoopHeartRateConfig &&
            (!config.deviceId.isNullOrBlank() || !config.displayName.isNullOrBlank())

    override fun connectToConfiguredDevice(config: ExternalHeartRateConfig) {
        val whoopConfig = config as? WhoopHeartRateConfig ?: run {
            publishConnectionState(
                ExternalHeartRateConnectionState.MissingConfiguration(
                    source = source,
                    message = "Configure ${source.displayName()} in Settings first."
                )
            )
            return
        }

        val context = applicationContext ?: return
        stopWhoopStreaming()
        publishConnectionState(
            ExternalHeartRateConnectionState.Connecting(
                source = source,
                message = "Connecting to your WHOOP..."
            )
        )

        val client = WhoopBleClient(
            context = context,
            config = whoopConfig,
            onStateChange = { state ->
                if (!isSessionSkipped) {
                    publishConnectionState(state)
                    if (state is ExternalHeartRateConnectionState.Connected ||
                        state is ExternalHeartRateConnectionState.Streaming
                    ) {
                        markConnectedThisSession()
                    }
                }
            }
        )
        whoopClient = client
        whoopStreamDisposable = StaleRetryingBpmStream(
            deviceId = whoopConfig.deviceId.orEmpty(),
            source = client,
            reconnection = client,
            staleTimeoutSec = 15,
            backoffSec = 2,
            onReconnecting = {
                viewModelScope.launch(appCeh) {
                    publishHeartRate(null)
                    if (!isSessionSkipped) {
                        publishConnectionState(
                            ExternalHeartRateConnectionState.Connecting(
                                source = source,
                                message = "Reconnecting to your WHOOP..."
                            )
                        )
                    }
                }
            }
        ).stream()
            .subscribeOn(Schedulers.io())
            .observeOn(io.reactivex.rxjava3.android.schedulers.AndroidSchedulers.mainThread())
            .subscribe(
                { bpm ->
                    publishHeartRate(bpm)
                    publishConnectionState(
                        ExternalHeartRateConnectionState.Streaming(
                            source = source,
                            message = "Streaming from your WHOOP.",
                            deviceLabel = whoopConfig.displayName ?: whoopConfig.deviceId
                        )
                    )
                    markConnectedThisSession()
                },
                { error ->
                    Log.e("WhoopHeartRateViewModel", "WHOOP streaming error", error)
                    publishHeartRate(null)
                    if (!isSessionSkipped) {
                        publishConnectionState(
                            ExternalHeartRateConnectionState.Error(
                                source = source,
                                message = error.message ?: "Couldn't connect to your WHOOP."
                            )
                        )
                    }
                }
            )
    }

    override fun releaseDeviceResources() {
        publishHeartRate(null)
        stopWhoopStreaming()
    }

    private fun stopWhoopStreaming() {
        whoopStreamDisposable?.dispose()
        whoopStreamDisposable = null
        whoopClient?.cleanup()
        whoopClient = null
    }
}

private class WhoopBleClient(
    private val context: Context,
    private val config: WhoopHeartRateConfig,
    private val onStateChange: (ExternalHeartRateConnectionState) -> Unit,
) : HrBpmSource, ReconnectionActions {
    companion object {
        private const val TAG = "WhoopBleClient"
        private val HEART_RATE_SERVICE_UUID =
            UUID.fromString("0000180D-0000-1000-8000-00805F9B34FB")
        private val HEART_RATE_MEASUREMENT_UUID =
            UUID.fromString("00002A37-0000-1000-8000-00805F9B34FB")
        private val CLIENT_CHARACTERISTIC_CONFIG_UUID =
            UUID.fromString("00002902-0000-1000-8000-00805F9B34FB")
        private const val SCAN_TIMEOUT_MS = 10_000L
    }

    private val handler = Handler(Looper.getMainLooper())
    private var scanCallback: ScanCallback? = null
    private var bluetoothGatt: BluetoothGatt? = null
    private var flowEmitter: FlowableEmitter<Int>? = null
    private var manualDisconnect = false
    private val loggedScanDeviceAddresses = mutableSetOf<String>()

    override fun bpmStream(deviceId: String): Flowable<Int> {
        return Flowable.create({ emitter ->
            flowEmitter = emitter
            manualDisconnect = false
            emitter.setCancellable { cleanup() }
            connectOrScan()
        }, BackpressureStrategy.LATEST)
    }

    override fun onStale(deviceId: String, onReconnecting: (() -> Unit)?): Completable {
        onReconnecting?.invoke()
        return Completable.fromAction {
            manualDisconnect = true
            cleanup()
            manualDisconnect = false
        }
    }

    fun cleanup() {
        stopScan()
        handler.removeCallbacksAndMessages(null)
        bluetoothGatt?.let { gatt ->
            runCatching { gatt.disconnect() }
            runCatching { gatt.close() }
        }
        bluetoothGatt = null
        flowEmitter = null
    }

    private fun connectOrScan() {
        val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val adapter = bluetoothManager?.adapter
        if (adapter == null) {
            failTerminal("Bluetooth is unavailable on this watch.")
            return
        }
        if (!adapter.isEnabled) {
            failTerminal("Bluetooth is turned off.")
            return
        }

        val explicitDeviceId = config.deviceId?.trim().orEmpty()
        if (explicitDeviceId.isNotEmpty()) {
            val device = runCatching { adapter.getRemoteDevice(explicitDeviceId) }.getOrNull()
            if (device != null) {
                connectGatt(device)
                return
            }
        }

        val scanner = adapter.bluetoothLeScanner
        if (scanner == null) {
            failTerminal("BLE scanning is unavailable on this watch.")
            return
        }

        loggedScanDeviceAddresses.clear()
        Log.d(
            TAG,
            "Starting WHOOP scan. expectedAddress=${config.deviceId?.trim().orEmpty().ifBlank { "<none>" }}, " +
                "expectedName=${config.displayName?.trim().orEmpty().ifBlank { "<none>" }}, " +
                "timeoutMs=$SCAN_TIMEOUT_MS"
        )

        onStateChange(
            ExternalHeartRateConnectionState.Connecting(
                source = HeartRateSource.WHOOP_BLE,
                message = "Scanning for your WHOOP..."
            )
        )

        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                val didMatch = matchesDevice(result)
                logDiscoveredDevice(result, didMatch)
                if (!didMatch) return
                Log.d(TAG, "WHOOP scan matched device ${result.device.address}; stopping scan and connecting")
                stopScan()
                connectGatt(result.device)
            }

            override fun onScanFailed(errorCode: Int) {
                Log.e(TAG, "WHOOP scan failed with errorCode=$errorCode")
                failTerminal("WHOOP scan failed ($errorCode).")
            }
        }
        scanCallback = callback

        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()

        scanner.startScan(emptyList<ScanFilter>(), settings, callback)
        handler.postDelayed({
            if (scanCallback === callback) {
                Log.d(TAG, "WHOOP scan timed out after ${SCAN_TIMEOUT_MS}ms without a match")
                stopScan()
                failTerminal("Couldn't find your WHOOP.")
            }
        }, SCAN_TIMEOUT_MS)
    }

    private fun matchesDevice(result: ScanResult): Boolean {
        val device = result.device
        val deviceName = result.scanRecord?.deviceName ?: device.name
        val explicitDeviceId = config.deviceId?.trim().orEmpty()
        if (explicitDeviceId.isNotEmpty()) {
            return device.address.equals(explicitDeviceId, ignoreCase = true)
        }

        val preferredName = config.displayName?.trim().orEmpty()
        if (preferredName.isNotEmpty()) {
            return deviceName?.contains(preferredName, ignoreCase = true) == true
        }

        return deviceName?.contains("WHOOP", ignoreCase = true) == true
    }

    private fun logDiscoveredDevice(result: ScanResult, didMatch: Boolean) {
        val device = result.device
        val address = device.address ?: "<unknown>"
        if (!loggedScanDeviceAddresses.add(address)) {
            return
        }

        val advertisedName = result.scanRecord?.deviceName
        val deviceName = device.name
        val serviceUuids = result.scanRecord?.serviceUuids
            ?.joinToString(prefix = "[", postfix = "]") { it.uuid.toString() }
            ?: "[]"
        val manufacturerDataKeys = result.scanRecord?.manufacturerSpecificData
            ?.let { data -> (0 until data.size()).joinToString(prefix = "[", postfix = "]") { index -> data.keyAt(index).toString() } }
            ?: "[]"
        val configuredAddress = config.deviceId?.trim().orEmpty()
        val configuredName = config.displayName?.trim().orEmpty()
        val addressMatches = configuredAddress.isNotEmpty() &&
            address.equals(configuredAddress, ignoreCase = true)
        val advertisedNameMatches = configuredName.isNotEmpty() &&
            (advertisedName?.contains(configuredName, ignoreCase = true) == true)
        val deviceNameMatches = configuredName.isNotEmpty() &&
            (deviceName?.contains(configuredName, ignoreCase = true) == true)
        val defaultWhoopNameMatch = configuredName.isBlank() &&
            configuredAddress.isBlank() &&
            listOfNotNull(advertisedName, deviceName).any { it.contains("WHOOP", ignoreCase = true) }
        val advertisesHeartRateService = result.scanRecord?.serviceUuids?.any {
            it.uuid == HEART_RATE_SERVICE_UUID
        } == true

        Log.d(
            TAG,
            "WHOOP scan saw device: address=$address, advertisedName=${advertisedName ?: "<none>"}, " +
                "deviceName=${deviceName ?: "<none>"}, rssi=${result.rssi}, " +
                "advertisesHeartRateService=$advertisesHeartRateService, serviceUuids=$serviceUuids, " +
                "manufacturerIds=$manufacturerDataKeys, addressMatches=$addressMatches, " +
                "advertisedNameMatches=$advertisedNameMatches, deviceNameMatches=$deviceNameMatches, " +
                "defaultWhoopNameMatch=$defaultWhoopNameMatch, matched=$didMatch"
        )
    }

    private fun connectGatt(device: BluetoothDevice) {
        Log.d(
            TAG,
            "Connecting to GATT device address=${device.address}, name=${device.name ?: "<none>"}"
        )
        onStateChange(
            ExternalHeartRateConnectionState.Connecting(
                source = HeartRateSource.WHOOP_BLE,
                message = "Connecting to ${device.name ?: "your WHOOP"}..."
            )
        )
        bluetoothGatt = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        } else {
            device.connectGatt(context, false, gattCallback)
        }
        if (bluetoothGatt == null) {
            failTerminal("Couldn't connect to ${device.name ?: "your WHOOP"}.")
        }
    }

    private fun stopScan() {
        val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val adapter = bluetoothManager?.adapter
        val scanner: BluetoothLeScanner? = adapter?.bluetoothLeScanner
        scanCallback?.let { callback ->
            Log.d(TAG, "Stopping WHOOP BLE scan")
            runCatching { scanner?.stopScan(callback) }
        }
        scanCallback = null
    }

    private fun failTerminal(message: String) {
        Log.e(TAG, "WHOOP terminal failure: $message")
        onStateChange(
            ExternalHeartRateConnectionState.Error(
                source = HeartRateSource.WHOOP_BLE,
                message = message
            )
        )
        flowEmitter?.tryOnError(IllegalStateException(message))
        cleanup()
    }

    private fun enableNotifications(
        gatt: BluetoothGatt,
        characteristic: BluetoothGattCharacteristic,
    ) {
        if (!gatt.setCharacteristicNotification(characteristic, true)) {
            failTerminal("Couldn't subscribe to WHOOP heart-rate notifications.")
            return
        }

        val descriptor = characteristic.getDescriptor(CLIENT_CHARACTERISTIC_CONFIG_UUID)
        if (descriptor == null) {
            onStateChange(
                ExternalHeartRateConnectionState.Streaming(
                    source = HeartRateSource.WHOOP_BLE,
                    message = "Streaming from your WHOOP.",
                    deviceLabel = config.displayName ?: config.deviceId
                )
            )
            return
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
        } else {
            @Suppress("DEPRECATION")
            descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            @Suppress("DEPRECATION")
            gatt.writeDescriptor(descriptor)
        }
    }

    private fun parseHeartRate(value: ByteArray): Int? {
        if (value.size < 2) return null
        val flags = value[0].toInt() and 0xFF
        val isUInt16 = flags and 0x01 != 0
        return if (isUInt16) {
            if (value.size < 3) null
            else (value[1].toInt() and 0xFF) or ((value[2].toInt() and 0xFF) shl 8)
        } else {
            value[1].toInt() and 0xFF
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            Log.d(
                TAG,
                "GATT connection state changed: address=${gatt.device.address}, name=${gatt.device.name ?: "<none>"}, status=$status, newState=$newState"
            )
            if (status != BluetoothGatt.GATT_SUCCESS && newState != BluetoothGatt.STATE_CONNECTED) {
                if (!manualDisconnect) {
                    failTerminal("WHOOP connection failed ($status).")
                }
                return
            }

            when (newState) {
                BluetoothGatt.STATE_CONNECTED -> {
                    onStateChange(
                        ExternalHeartRateConnectionState.Connected(
                            source = HeartRateSource.WHOOP_BLE,
                            message = "Connected to ${gatt.device.name ?: "your WHOOP"}.",
                            deviceLabel = gatt.device.name ?: gatt.device.address
                        )
                    )
                    gatt.discoverServices()
                }

                BluetoothGatt.STATE_DISCONNECTED -> {
                    bluetoothGatt = null
                    runCatching { gatt.close() }
                    if (!manualDisconnect) {
                        onStateChange(
                            ExternalHeartRateConnectionState.Error(
                                source = HeartRateSource.WHOOP_BLE,
                                message = "Disconnected from ${gatt.device.name ?: "your WHOOP"}."
                            )
                        )
                    }
                }
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            val discoveredServiceUuids = gatt.services.joinToString(prefix = "[", postfix = "]") {
                it.uuid.toString()
            }
            Log.d(
                TAG,
                "WHOOP services discovered: address=${gatt.device.address}, status=$status, services=$discoveredServiceUuids"
            )
            if (status != BluetoothGatt.GATT_SUCCESS) {
                failTerminal("Couldn't discover WHOOP heart-rate services.")
                return
            }
            val service: BluetoothGattService? = gatt.getService(HEART_RATE_SERVICE_UUID)
            val characteristic = service?.getCharacteristic(HEART_RATE_MEASUREMENT_UUID)
            if (characteristic == null) {
                failTerminal("WHOOP heart-rate service is unavailable.")
                return
            }
            enableNotifications(gatt, characteristic)
        }

        override fun onDescriptorWrite(
            gatt: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int,
        ) {
            Log.d(
                TAG,
                "WHOOP descriptor write completed: address=${gatt.device.address}, descriptor=${descriptor.uuid}, status=$status"
            )
            if (status != BluetoothGatt.GATT_SUCCESS) {
                failTerminal("Couldn't enable WHOOP heart-rate notifications.")
                return
            }
            onStateChange(
                ExternalHeartRateConnectionState.Streaming(
                    source = HeartRateSource.WHOOP_BLE,
                    message = "Streaming from your WHOOP.",
                    deviceLabel = gatt.device.name ?: gatt.device.address
                )
            )
        }

        @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            if (characteristic.uuid != HEART_RATE_MEASUREMENT_UUID) return
            val bpm = parseHeartRate(characteristic.value) ?: return
            if (bpm > 0) {
                Log.d(
                    TAG,
                    "WHOOP heart-rate notification: address=${gatt.device.address}, bpm=$bpm"
                )
                flowEmitter?.onNext(bpm)
                onStateChange(
                    ExternalHeartRateConnectionState.Streaming(
                        source = HeartRateSource.WHOOP_BLE,
                        message = "Streaming from your WHOOP.",
                        deviceLabel = gatt.device.name ?: gatt.device.address
                    )
                )
            }
        }
    }
}
