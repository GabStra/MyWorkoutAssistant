package com.gabstra.myworkoutassistant.data

import android.Manifest
import android.annotation.SuppressLint
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
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.ContextCompat
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

    private fun hasPermission(permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    private fun hasBluetoothScanPermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            hasPermission(Manifest.permission.BLUETOOTH_SCAN)
        } else {
            hasPermission(Manifest.permission.ACCESS_FINE_LOCATION) ||
                hasPermission(Manifest.permission.ACCESS_COARSE_LOCATION)
        }
    }

    private fun hasBluetoothConnectPermission(): Boolean {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            hasPermission(Manifest.permission.BLUETOOTH_CONNECT)
    }

    private fun ensureBluetoothScanPermission(): Boolean {
        if (hasBluetoothScanPermission()) return true
        failTerminal("Bluetooth scan permission is required to find your WHOOP.")
        return false
    }

    private fun ensureBluetoothConnectPermission(): Boolean {
        if (hasBluetoothConnectPermission()) return true
        failTerminal("Bluetooth connect permission is required to connect to your WHOOP.")
        return false
    }

    private fun configuredDeviceLabel(): String {
        return config.displayName?.trim()?.takeIf { it.isNotEmpty() } ?: "your WHOOP"
    }

    @SuppressLint("MissingPermission")
    private fun bluetoothDeviceAddress(device: BluetoothDevice): String = device.address

    @SuppressLint("MissingPermission")
    private fun bluetoothDeviceName(device: BluetoothDevice): String? = device.name

    private fun deviceAddressOrUnknown(device: BluetoothDevice): String {
        val configuredAddress = config.deviceId?.trim().orEmpty()
        return if (hasBluetoothConnectPermission()) {
            bluetoothDeviceAddress(device)
        } else {
            configuredAddress.ifBlank { "<unknown>" }
        }
    }

    private fun deviceNameOrNull(device: BluetoothDevice): String? {
        return if (hasBluetoothConnectPermission()) {
            bluetoothDeviceName(device)
        } else {
            config.displayName?.trim()?.takeIf { it.isNotEmpty() }
        }
    }

    private fun deviceLabel(device: BluetoothDevice): String = deviceNameOrNull(device) ?: configuredDeviceLabel()

    @SuppressLint("MissingPermission")
    private fun gattDeviceAddress(gatt: BluetoothGatt): String = gatt.device.address

    @SuppressLint("MissingPermission")
    private fun gattDeviceName(gatt: BluetoothGatt): String? = gatt.device.name

    private fun gattAddressOrUnknown(gatt: BluetoothGatt): String {
        val configuredAddress = config.deviceId?.trim().orEmpty()
        return if (hasBluetoothConnectPermission()) {
            gattDeviceAddress(gatt)
        } else {
            configuredAddress.ifBlank { "<unknown>" }
        }
    }

    private fun gattLabel(gatt: BluetoothGatt): String {
        if (!hasBluetoothConnectPermission()) {
            return config.displayName?.trim()?.takeIf { it.isNotEmpty() }
                ?: config.deviceId?.trim()?.takeIf { it.isNotEmpty() }
                ?: "your WHOOP"
        }

        return gattDeviceName(gatt) ?: gattDeviceAddress(gatt)
    }

    @SuppressLint("MissingPermission")
    private fun disconnectGattQuietly(gatt: BluetoothGatt) {
        runCatching { gatt.disconnect() }
        runCatching { gatt.close() }
    }

    @SuppressLint("MissingPermission")
    private fun startScan(
        scanner: BluetoothLeScanner,
        settings: ScanSettings,
        callback: ScanCallback,
    ) {
        scanner.startScan(emptyList<ScanFilter>(), settings, callback)
    }

    @SuppressLint("MissingPermission")
    private fun stopScan(
        scanner: BluetoothLeScanner?,
        callback: ScanCallback,
    ) {
        scanner?.stopScan(callback)
    }

    @SuppressLint("MissingPermission")
    private fun connectGatt(device: BluetoothDevice): BluetoothGatt? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        } else {
            device.connectGatt(context, false, gattCallback)
        }
    }

    @SuppressLint("MissingPermission")
    private fun setCharacteristicNotification(
        gatt: BluetoothGatt,
        characteristic: BluetoothGattCharacteristic,
        enabled: Boolean,
    ): Boolean = gatt.setCharacteristicNotification(characteristic, enabled)

    @SuppressLint("MissingPermission")
    private fun writeDescriptor(
        gatt: BluetoothGatt,
        descriptor: BluetoothGattDescriptor,
    ) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt.writeDescriptor(
                descriptor,
                BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            )
        } else {
            @Suppress("DEPRECATION")
            descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            @Suppress("DEPRECATION")
            gatt.writeDescriptor(descriptor)
        }
    }

    @SuppressLint("MissingPermission")
    private fun discoverServices(gatt: BluetoothGatt) {
        gatt.discoverServices()
    }

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
            if (hasBluetoothConnectPermission()) {
                disconnectGattQuietly(gatt)
            }
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
                connectToGatt(device)
                return
            }
        }

        if (!ensureBluetoothScanPermission() || !ensureBluetoothConnectPermission()) {
            return
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
                if (!ensureBluetoothScanPermission() || !ensureBluetoothConnectPermission()) {
                    return
                }
                val didMatch = matchesDevice(result)
                logDiscoveredDevice(result, didMatch)
                if (!didMatch) return
                Log.d(
                    TAG,
                    "WHOOP scan matched device ${deviceAddressOrUnknown(result.device)}; " +
                        "stopping scan and connecting"
                )
                stopScan()
                connectToGatt(result.device)
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

        startScan(scanner, settings, callback)
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
        if (!hasBluetoothConnectPermission()) {
            return false
        }
        val deviceName = result.scanRecord?.deviceName ?: deviceNameOrNull(device)
        val explicitDeviceId = config.deviceId?.trim().orEmpty()
        if (explicitDeviceId.isNotEmpty()) {
            return deviceAddressOrUnknown(device).equals(explicitDeviceId, ignoreCase = true)
        }

        val preferredName = config.displayName?.trim().orEmpty()
        if (preferredName.isNotEmpty()) {
            return deviceName?.contains(preferredName, ignoreCase = true) == true
        }

        return deviceName?.contains("WHOOP", ignoreCase = true) == true
    }

    private fun logDiscoveredDevice(result: ScanResult, didMatch: Boolean) {
        val device = result.device
        val address = deviceAddressOrUnknown(device)
        if (!loggedScanDeviceAddresses.add(address)) {
            return
        }

        val advertisedName = result.scanRecord?.deviceName
        val deviceName = deviceNameOrNull(device)
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

    private fun connectToGatt(device: BluetoothDevice) {
        if (!ensureBluetoothConnectPermission()) {
            return
        }

        val address = deviceAddressOrUnknown(device)
        val name = deviceNameOrNull(device)
        val label = deviceLabel(device)
        Log.d(
            TAG,
            "Connecting to GATT device address=$address, name=${name ?: "<none>"}"
        )
        onStateChange(
            ExternalHeartRateConnectionState.Connecting(
                source = HeartRateSource.WHOOP_BLE,
                message = "Connecting to $label..."
            )
        )
        bluetoothGatt = connectGatt(device)
        if (bluetoothGatt == null) {
            failTerminal("Couldn't connect to $label.")
        }
    }

    private fun stopScan() {
        val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val adapter = bluetoothManager?.adapter
        val scanner: BluetoothLeScanner? = adapter?.bluetoothLeScanner
        scanCallback?.let { callback ->
            Log.d(TAG, "Stopping WHOOP BLE scan")
            if (hasBluetoothScanPermission()) {
                runCatching { stopScan(scanner, callback) }
            }
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
        if (!ensureBluetoothConnectPermission()) {
            return
        }

        if (!setCharacteristicNotification(gatt, characteristic, true)) {
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

        writeDescriptor(gatt, descriptor)
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
            if (!hasBluetoothConnectPermission()) {
                failTerminal("Bluetooth connect permission was removed.")
                return
            }

            Log.d(
                TAG,
                "GATT connection state changed: address=${gattAddressOrUnknown(gatt)}, " +
                    "name=${gattDeviceName(gatt) ?: "<none>"}, status=$status, newState=$newState"
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
                            message = "Connected to ${gattLabel(gatt)}.",
                            deviceLabel = gattLabel(gatt)
                        )
                    )
                    discoverServices(gatt)
                }

                BluetoothGatt.STATE_DISCONNECTED -> {
                    bluetoothGatt = null
                    disconnectGattQuietly(gatt)
                    if (!manualDisconnect) {
                        onStateChange(
                            ExternalHeartRateConnectionState.Error(
                                source = HeartRateSource.WHOOP_BLE,
                                message = "Disconnected from ${gattLabel(gatt)}."
                            )
                        )
                    }
                }
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (!hasBluetoothConnectPermission()) {
                failTerminal("Bluetooth connect permission was removed.")
                return
            }

            val discoveredServiceUuids = gatt.services.joinToString(prefix = "[", postfix = "]") {
                it.uuid.toString()
            }
            Log.d(
                TAG,
                "WHOOP services discovered: address=${gattAddressOrUnknown(gatt)}, " +
                    "status=$status, services=$discoveredServiceUuids"
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
            if (!hasBluetoothConnectPermission()) {
                failTerminal("Bluetooth connect permission was removed.")
                return
            }

            Log.d(
                TAG,
                "WHOOP descriptor write completed: address=${gattAddressOrUnknown(gatt)}, " +
                    "descriptor=${descriptor.uuid}, status=$status"
            )
            if (status != BluetoothGatt.GATT_SUCCESS) {
                failTerminal("Couldn't enable WHOOP heart-rate notifications.")
                return
            }
            onStateChange(
                ExternalHeartRateConnectionState.Streaming(
                    source = HeartRateSource.WHOOP_BLE,
                    message = "Streaming from your WHOOP.",
                    deviceLabel = gattLabel(gatt)
                )
            )
        }

        @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            if (!hasBluetoothConnectPermission()) {
                failTerminal("Bluetooth connect permission was removed.")
                return
            }

            if (characteristic.uuid != HEART_RATE_MEASUREMENT_UUID) return
            val bpm = parseHeartRate(characteristic.value) ?: return
            if (bpm > 0) {
                Log.d(
                    TAG,
                    "WHOOP heart-rate notification: address=${gattAddressOrUnknown(gatt)}, bpm=$bpm"
                )
                flowEmitter?.onNext(bpm)
                onStateChange(
                    ExternalHeartRateConnectionState.Streaming(
                        source = HeartRateSource.WHOOP_BLE,
                        message = "Streaming from your WHOOP.",
                        deviceLabel = gattLabel(gatt)
                    )
                )
            }
        }
    }
}
