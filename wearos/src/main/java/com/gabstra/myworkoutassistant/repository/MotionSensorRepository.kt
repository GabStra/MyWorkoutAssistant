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
    private val sensorByType = mapOf(
        MotionSensorType.ACCELEROMETER to sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER),
        MotionSensorType.GYROSCOPE to sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE),
        MotionSensorType.ROTATION_VECTOR to sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
    )

    fun hasRequiredSensors(config: MotionCaptureSensorConfig = MotionCaptureSensorConfig()): Boolean =
        config.enabledSensors.all { sensorByType[it] != null }

    fun sampleFlow(config: MotionCaptureSensorConfig) = callbackFlow {
        val sensors = config.enabledSensors.mapNotNull { type ->
            sensorByType[type]?.let { type to it }
        }
        if (sensors.size != config.enabledSensors.size) {
            close()
            return@callbackFlow
        }

        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent?) {
                event ?: return
                val sensorType = when (event.sensor.type) {
                    Sensor.TYPE_ACCELEROMETER -> MotionSensorType.ACCELEROMETER
                    Sensor.TYPE_GYROSCOPE -> MotionSensorType.GYROSCOPE
                    Sensor.TYPE_ROTATION_VECTOR -> MotionSensorType.ROTATION_VECTOR
                    else -> return
                }
                val w = if (sensorType == MotionSensorType.ROTATION_VECTOR && event.values.size >= 4) {
                    event.values[3]
                } else {
                    null
                }
                trySend(
                    MotionSensorSample(
                        sensorType = sensorType,
                        epochTimeMs = System.currentTimeMillis(),
                        elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos(),
                        accuracy = event.accuracy,
                        x = event.values.getOrElse(0) { 0f },
                        y = event.values.getOrElse(1) { 0f },
                        z = event.values.getOrElse(2) { 0f },
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
}
