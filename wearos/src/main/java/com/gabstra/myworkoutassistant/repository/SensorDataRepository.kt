package com.gabstra.myworkoutassistant.repository

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.util.Log
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.channels.trySendBlocking
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.runBlocking
import kotlin.math.roundToInt

/**
 * Entry point for accessing heart rate data using Android's Sensor API.
 */
class SensorDataRepository(
    context: Context
) {
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val heartBeatSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_HEART_RATE) // ?: sensorManager.getDefaultSensor(Sensor.TYPE_HEART_BEAT)

    //private var lastBeatTimestamp: Long? = null

    /**
     * Checks if the device has a heart rate sensor.
     */
    fun hasHeartRateCapability(): Boolean {
        return heartBeatSensor != null
    }

    /**
     * Returns a cold flow that registers a listener for heart beat data.
     * The flow will start to emit heart beat data when activated, and stop when cancelled.
     *
     * [callbackFlow] is used to bridge between a callback-based API and Kotlin flows.
     */
    @ExperimentalCoroutinesApi
    fun heartBeatMeasureFlow() = callbackFlow {
        if (heartBeatSensor == null) {
            Log.e("SensorDataRepository", "Heart beat sensor not available")
            close()
            return@callbackFlow
        }

        val sensorEventListener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent?) {
                if (event?.sensor == heartBeatSensor) {
                    val value = event.values[0]

                    if (event.sensor.type == Sensor.TYPE_HEART_RATE) {
                        // Handle heart rate sensor data (assume value is in bpm)
                        val bpm = value.roundToInt()
                        trySendBlocking(MeasureMessageSensor.MeasureData(bpm))
                    }

                  /*  if (event.sensor.type == Sensor.TYPE_HEART_BEAT) {
                        val confidence = value
                        if (confidence == 1.0f) {
                            val currentTimestamp = event.timestamp

                            lastBeatTimestamp?.let { lastTimestamp ->
                                val timeDifference = (currentTimestamp - lastTimestamp) / 1_000_000_000.0 // convert nanoseconds to seconds
                                val bpm = (60.0 / timeDifference).roundToInt() // calculate BPM and round to nearest integer
                                trySendBlocking(MeasureMessageSensor.MeasureData(bpm))
                            }

                            lastBeatTimestamp = currentTimestamp
                        }
                    } */
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
                // Handle accuracy changes if necessary
            }
        }

        // Register the listener with maximum frequency
        sensorManager.registerListener(
            sensorEventListener,
            heartBeatSensor,
            SensorManager.SENSOR_DELAY_FASTEST
        )

        awaitClose {
            runBlocking {
                sensorManager.unregisterListener(sensorEventListener, heartBeatSensor)
            }
        }
    }
}

sealed class MeasureMessageSensor {
    class MeasureData(val bpm: Int) : MeasureMessageSensor()
}
