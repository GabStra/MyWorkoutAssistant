package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import com.gabstra.myworkoutassistant.shared.workout.model.ownerDeviceOrDefault
import com.google.gson.GsonBuilder
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.util.UUID

class WorkoutRecordAdapterTest {

    @Test
    fun `deserialize uses PHONE fallback when ownerDevice missing`() {
        val gson = GsonBuilder()
            .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
            .registerTypeAdapter(WorkoutRecord::class.java, WorkoutRecordAdapter())
            .create()
        val json = """
            {
              "id": "${UUID.randomUUID()}",
              "workoutId": "${UUID.randomUUID()}",
              "workoutHistoryId": "${UUID.randomUUID()}",
              "setIndex": 0,
              "exerciseId": "${UUID.randomUUID()}",
              "activeSessionRevision": 1
            }
        """.trimIndent()

        val parsed = gson.fromJson(json, WorkoutRecord::class.java)

        assertEquals(SessionOwnerDevice.PHONE.name, parsed.ownerDevice)
        assertEquals(SessionOwnerDevice.PHONE, parsed.ownerDeviceOrDefault())
    }

    @Test
    fun `ownerDeviceOrDefault returns PHONE for invalid value`() {
        val record = WorkoutRecord(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            setIndex = 0u,
            exerciseId = UUID.randomUUID(),
            ownerDevice = "INVALID_OWNER",
            lastActiveSyncAt = LocalDateTime.now()
        )

        assertEquals(SessionOwnerDevice.PHONE, record.ownerDeviceOrDefault())
    }
}
