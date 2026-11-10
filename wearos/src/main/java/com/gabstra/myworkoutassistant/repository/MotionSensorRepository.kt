package com.gabstra.myworkoutassistant.repository

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.util.Log
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSensorConfig
import com.gabstra.myworkoutassistant.shared.motion.MotionSensorSample
import com.gabstra.myworkoutassistant.shared.motion.MotionSensorType
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.callbackFlow

/** One sensor as the watch exposes it to a third-party app. */
data class SensorInventoryEntry(
    val name: String,
    val vendor: String,
    val type: Int,
    val stringType: String,
    val minDelayUs: Int,
    val maxDelayUs: Int,
    val maxRange: Float,
    val resolution: Float,
    val powerMa: Float,
    val fifoMaxEventCount: Int,
    val fifoReservedEventCount: Int,
    val isWakeUp: Boolean,
    val highestDirectReportRateLevel: Int,
) {
    val maxRateHz: Int get() = if (minDelayUs > 0) 1_000_000 / minDelayUs else 0
}

class MotionSensorRepository(
    context: Context
) {
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private val androidSensorTypeByMotionType = mapOf(
        MotionSensorType.ACCELEROMETER to Sensor.TYPE_ACCELEROMETER,
        MotionSensorType.GYROSCOPE to Sensor.TYPE_GYROSCOPE,
        MotionSensorType.ROTATION_VECTOR to Sensor.TYPE_ROTATION_VECTOR,
        MotionSensorType.HEART_RATE to Sensor.TYPE_HEART_RATE,
        MotionSensorType.STEP_COUNTER to Sensor.TYPE_STEP_COUNTER,
        MotionSensorType.GRAVITY to Sensor.TYPE_GRAVITY,
        MotionSensorType.LINEAR_ACCELERATION to Sensor.TYPE_LINEAR_ACCELERATION,
        MotionSensorType.PRESSURE to Sensor.TYPE_PRESSURE
    )

    fun availableSensors(): Set<MotionSensorType> =
        androidSensorTypeByMotionType
            .filterValues { sensorManager.getDefaultSensor(it) != null }
            .keys

    /** Sensors rep/phase analysis depends on; capture without them produces no usable motion data. */
    fun hasCoreSensors(): Boolean = CORE_SENSOR_TYPES.all {
        sensorManager.getDefaultSensor(androidSensorTypeByMotionType.getValue(it)) != null
    }

    fun observedSensors(config: MotionCaptureSensorConfig): Set<MotionSensorType> =
        config.enabledSensors.toSet() intersect availableSensors()

    /**
     * Everything the watch exposes through the public SensorManager, including Samsung vendor
     * sensors and their required permissions. Logged once per process so the gated set is visible.
     */
    fun inventory(): List<SensorInventoryEntry> =
        sensorManager.getSensorList(Sensor.TYPE_ALL)
            .map { sensor ->
                SensorInventoryEntry(
                    name = sensor.name,
                    vendor = sensor.vendor,
                    type = sensor.type,
                    stringType = runCatching { sensor.stringType }.getOrDefault(""),
                    minDelayUs = sensor.minDelay,
                    maxDelayUs = sensor.maxDelay,
                    maxRange = sensor.maximumRange,
                    resolution = sensor.resolution,
                    powerMa = sensor.power,
                    fifoMaxEventCount = sensor.fifoMaxEventCount,
                    fifoReservedEventCount = sensor.fifoReservedEventCount,
                    isWakeUp = sensor.isWakeUpSensor,
                    highestDirectReportRateLevel = runCatching {
                        sensor.highestDirectReportRateLevel
                    }.getOrDefault(0),
                )
            }
            .sortedBy { it.type }

    fun logInventory(tag: String = "MotionSensors") {
        val entries = inventory()
        Log.i(tag, "sensor inventory: ${entries.size} sensors")
        entries.forEach { entry ->
            val rate = if (entry.maxRateHz > 0) "${entry.maxRateHz}Hz" else "on-change"
            Log.i(
                tag,
                "  type=${entry.type} ${entry.stringType} \"${entry.name}\" vendor=${entry.vendor} " +
                    "maxRate=$rate fifo=${entry.fifoMaxEventCount} " +
                    "wakeUp=${entry.isWakeUp} direct=${entry.highestDirectReportRateLevel}"
            )
        }
    }

    fun sampleFlow(config: MotionCaptureSensorConfig) = callbackFlow {
        val sensors = observedSensors(config).mapNotNull { type ->
            sensorManager.getDefaultSensor(androidSensorTypeByMotionType.getValue(type))?.let { type to it }
        }
        if (sensors.isEmpty()) {
            close()
            return@callbackFlow
        }

        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent?) {
                event ?: return
                val sensorType = androidSensorTypeByMotionType.entries
                    .firstOrNull { it.value == event.sensor.type }
                    ?.key
                    ?: return
                val values = event.values
                val w = if (sensorType == MotionSensorType.ROTATION_VECTOR && values.size >= 4) {
                    values[3]
                } else {
                    null
                }
                trySend(
                    MotionSensorSample(
                        sensorType = sensorType,
                        epochTimeMs = System.currentTimeMillis(),
                        // event.timestamp is the sensor sample clock; with FIFO batching the
                        // callback can arrive later, so the callback clock would skew motion timing.
                        elapsedRealtimeNanos = event.timestamp,
                        accuracy = event.accuracy,
                        x = values.getOrElse(0) { 0f },
                        y = values.getOrElse(1) { 0f },
                        z = values.getOrElse(2) { 0f },
                        w = w
                    )
                )
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit
        }

        val requestedPeriodUs = if (config.sampleRateHz > 0) 1_000_000 / config.sampleRateHz else 0
        val batchLatencyUs = config.maxBatchLatencyMs.coerceAtLeast(0) * 1_000
        sensors.forEach { (type, sensor) ->
            // Never ask for faster than the sensor supports; 0 means "its fastest".
            val periodUs = maxOf(requestedPeriodUs, sensor.minDelay)
            Log.i(
                "MotionSensors",
                "register ${type.name}: period=${if (periodUs > 0) "${periodUs}us" else "max"} " +
                    "batch=${batchLatencyUs}us sensorMax=${if (sensor.minDelay > 0) "${1_000_000 / sensor.minDelay}Hz" else "on-change"}"
            )
            sensorManager.registerListener(listener, sensor, periodUs, batchLatencyUs)
        }

        awaitClose {
            sensors.forEach { (_, sensor) ->
                sensorManager.unregisterListener(listener, sensor)
            }
        }
    }

    companion object {
        private val CORE_SENSOR_TYPES = setOf(
            MotionSensorType.ACCELEROMETER,
            MotionSensorType.GYROSCOPE,
            MotionSensorType.ROTATION_VECTOR
        )
    }
}
