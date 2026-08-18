package com.gabstra.myworkoutassistant.heart_rate

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import com.gabstra.myworkoutassistant.shared.ExternalHeartRateConfig
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.PolarHeartRateConfig
import com.gabstra.myworkoutassistant.shared.WhoopHeartRateConfig
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed interface ExternalHeartRateConnectionState {
    data object Idle : ExternalHeartRateConnectionState
    data class Connecting(val message: String) : ExternalHeartRateConnectionState
    data class Streaming(val deviceLabel: String) : ExternalHeartRateConnectionState
    data class Error(val message: String) : ExternalHeartRateConnectionState
}

interface ExternalHeartRateController {
    val source: HeartRateSource
    val connectionState: StateFlow<ExternalHeartRateConnectionState>
    val heartRate: StateFlow<Int?>

    fun initialize(context: Context, config: ExternalHeartRateConfig?)
    fun connect()
    fun disconnect()
}

abstract class StandardBleHeartRateViewModel(
    final override val source: HeartRateSource,
) : ViewModel(), ExternalHeartRateController {
    private val mutableConnectionState =
        MutableStateFlow<ExternalHeartRateConnectionState>(ExternalHeartRateConnectionState.Idle)
    override val connectionState = mutableConnectionState.asStateFlow()

    private val mutableHeartRate = MutableStateFlow<Int?>(null)
    override val heartRate = mutableHeartRate.asStateFlow()

    private var applicationContext: Context? = null
    private var config: ExternalHeartRateConfig? = null
    private var bluetoothGatt: BluetoothGatt? = null
    private var scanCallback: ScanCallback? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    final override fun initialize(context: Context, config: ExternalHeartRateConfig?) {
        disconnect()
        applicationContext = context.applicationContext
        this.config = config
    }

    @SuppressLint("MissingPermission")
    final override fun connect() {
        val context = applicationContext ?: return
        val configuredSource = config
        if (configuredSource == null || configuredSource.source != source) {
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

        val scanner = context.getSystemService(BluetoothManager::class.java)
            ?.adapter
            ?.bluetoothLeScanner
        if (scanner == null) {
            mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                "Bluetooth is unavailable.",
            )
            return
        }

        stopScan()
        bluetoothGatt?.close()
        bluetoothGatt = null
        mutableHeartRate.value = null
        mutableConnectionState.value = ExternalHeartRateConnectionState.Connecting(
            "Scanning for ${source.displayName()}…",
        )

        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                if (!matchesConfiguredDevice(result, configuredSource)) return
                stopScan()
                val label = result.scanRecord?.deviceName
                    ?: result.device.name
                    ?: source.displayName()
                mutableConnectionState.value = ExternalHeartRateConnectionState.Connecting(
                    "Connecting to $label…",
                )
                val pendingGatt = result.device.connectGatt(
                    context,
                    false,
                    createGattCallback(label),
                    BluetoothDevice.TRANSPORT_LE,
                )
                bluetoothGatt = pendingGatt
                mainHandler.postDelayed({
                    if (
                        bluetoothGatt === pendingGatt &&
                        mutableConnectionState.value is ExternalHeartRateConnectionState.Connecting
                    ) {
                        pendingGatt.disconnect()
                        pendingGatt.close()
                        bluetoothGatt = null
                        mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                            "Couldn't connect to $label.",
                        )
                    }
                }, ConnectionTimeoutMillis)
            }

            override fun onScanFailed(errorCode: Int) {
                mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                    "Bluetooth scan failed ($errorCode).",
                )
            }
        }
        scanCallback = callback
        scanner.startScan(
            null,
            ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(),
            callback,
        )
        mainHandler.postDelayed({
            if (scanCallback === callback) {
                stopScan()
                mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                    "Couldn't find ${source.displayName()}.",
                )
            }
        }, ScanTimeoutMillis)
    }

    @SuppressLint("MissingPermission")
    private fun createGattCallback(deviceLabel: String) = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> gatt.discoverServices()
                BluetoothProfile.STATE_DISCONNECTED -> {
                    mutableHeartRate.value = null
                    if (bluetoothGatt === gatt) {
                        mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                            "Connection to $deviceLabel was lost.",
                        )
                    }
                    gatt.close()
                }
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            val measurement = gatt
                .getService(HeartRateServiceUuid)
                ?.getCharacteristic(HeartRateMeasurementUuid)
            if (status != BluetoothGatt.GATT_SUCCESS || measurement == null) {
                mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                    "$deviceLabel does not expose heart-rate broadcast data.",
                )
                return
            }
            gatt.setCharacteristicNotification(measurement, true)
            val descriptor = measurement.getDescriptor(ClientCharacteristicConfigurationUuid)
            if (descriptor == null) {
                mutableConnectionState.value = ExternalHeartRateConnectionState.Error(
                    "Couldn't subscribe to $deviceLabel.",
                )
                return
            }
            gatt.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
            mutableConnectionState.value = ExternalHeartRateConnectionState.Streaming(deviceLabel)
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            if (characteristic.uuid != HeartRateMeasurementUuid || value.size < 2) return
            val isSixteenBit = value[0].toInt() and 0x01 != 0
            val bpm = if (isSixteenBit && value.size >= 3) {
                (value[1].toInt() and 0xff) or ((value[2].toInt() and 0xff) shl 8)
            } else {
                value[1].toInt() and 0xff
            }
            if (bpm > 0) mutableHeartRate.value = bpm
        }
    }

    @SuppressLint("MissingPermission")
    final override fun disconnect() {
        stopScan()
        bluetoothGatt?.disconnect()
        bluetoothGatt?.close()
        bluetoothGatt = null
        mutableHeartRate.value = null
        mutableConnectionState.value = ExternalHeartRateConnectionState.Idle
    }

    @SuppressLint("MissingPermission")
    private fun stopScan() {
        val callback = scanCallback ?: return
        val context = applicationContext
        if (context != null && hasBluetoothPermission(context)) {
            context.getSystemService(BluetoothManager::class.java)
                ?.adapter
                ?.bluetoothLeScanner
                ?.stopScan(callback)
        }
        scanCallback = null
    }

    @SuppressLint("MissingPermission")
    private fun matchesConfiguredDevice(
        result: ScanResult,
        config: ExternalHeartRateConfig,
    ): Boolean {
        val advertisedServices = result.scanRecord?.serviceUuids?.map { it.uuid }.orEmpty()
        if (HeartRateServiceUuid !in advertisedServices) return false

        val advertisedName = result.scanRecord?.deviceName.orEmpty()
        val deviceName = result.device.name.orEmpty()
        val address = result.device.address
        val names = listOf(advertisedName, deviceName)

        return when (config) {
            is PolarHeartRateConfig -> {
                val id = config.deviceId.trim()
                id.isNotEmpty() && (address.equals(id, true) || names.any { it.contains(id, true) })
            }
            is WhoopHeartRateConfig -> {
                val id = config.deviceId?.trim().orEmpty()
                val configuredName = config.displayName?.trim().orEmpty()
                (id.isNotEmpty() && address.equals(id, true)) ||
                    (configuredName.isNotEmpty() && names.any { it.contains(configuredName, true) }) ||
                    (id.isEmpty() && configuredName.isEmpty() && names.any { it.contains("WHOOP", true) })
            }
        }
    }

    override fun onCleared() {
        disconnect()
    }

    private companion object {
        const val ScanTimeoutMillis = 15_000L
        const val ConnectionTimeoutMillis = 15_000L
        val HeartRateServiceUuid: UUID = UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb")
        val HeartRateMeasurementUuid: UUID = UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb")
        val ClientCharacteristicConfigurationUuid: UUID =
            UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }
}

class WhoopHeartRateViewModel : StandardBleHeartRateViewModel(HeartRateSource.WHOOP_BLE)

fun hasBluetoothPermission(context: Context): Boolean =
    ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_SCAN) ==
        PackageManager.PERMISSION_GRANTED &&
        ContextCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) ==
        PackageManager.PERMISSION_GRANTED
