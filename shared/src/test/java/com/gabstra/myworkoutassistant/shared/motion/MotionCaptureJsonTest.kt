package com.gabstra.myworkoutassistant.shared.motion

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MotionCaptureJsonTest {

    @Test
    fun `sensor config round-trips with observed sensors`() {
        val config = MotionCaptureSensorConfig(
            sampleRateHz = 50,
            chunkSampleCount = 500,
            enabledSensors = listOf(MotionSensorType.ACCELEROMETER, MotionSensorType.HEART_RATE),
            observedSensors = listOf(MotionSensorType.ACCELEROMETER, MotionSensorType.HEART_RATE)
        )

        val parsed = MotionCaptureJson.sensorConfigFromJson(MotionCaptureJson.sensorConfigToJson(config))

        assertEquals(config, parsed)
    }

    @Test
    fun `sensor config written before observed sensors still parses`() {
        val legacyJson = "{\"sampleRateHz\":50,\"chunkSampleCount\":500," +
            "\"enabledSensors\":[\"ACCELEROMETER\",\"GYROSCOPE\",\"ROTATION_VECTOR\"]}"

        val parsed = MotionCaptureJson.sensorConfigFromJson(legacyJson)

        assertNull(parsed.observedSensors)
        assertEquals(
            listOf(MotionSensorType.ACCELEROMETER, MotionSensorType.GYROSCOPE, MotionSensorType.ROTATION_VECTOR),
            parsed.enabledSensors
        )
    }
}
