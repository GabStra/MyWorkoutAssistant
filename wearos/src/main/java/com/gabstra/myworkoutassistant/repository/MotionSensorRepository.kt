package com.gabstra.myworkoutassistant.repository

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.SystemClock
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSensorConfig
import com.gabstra.myworkoutassistant.shared.motion.MotionSensorSample
import com.gabstra.myworkoutassistant.shared.motion.MotionSensorType
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.callbackFlow

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
                        elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos(),
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

        val samplingPeriodUs = 1_000_000 / config.sampleRateHz
        sensors.forEach { (_, sensor) ->
            sensorManager.registerListener(listener, sensor, samplingPeriodUs)
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
