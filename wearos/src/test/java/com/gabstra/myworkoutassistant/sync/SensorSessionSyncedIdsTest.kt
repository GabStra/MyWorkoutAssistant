package com.gabstra.myworkoutassistant.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class SensorSessionSyncedIdsTest {

    @Test
    fun `parse keeps valid uuid strings and drops invalid entries`() {
        val first = UUID.randomUUID()
        val second = UUID.randomUUID()

        val parsed = SensorSessionSyncedIds.parse(
            listOf(first.toString(), "not-a-uuid", second.toString())
        )

        assertEquals(setOf(first, second), parsed)
    }

    @Test
    fun `encode and parse round trip preserves ids`() {
        val ids = setOf(UUID.randomUUID(), UUID.randomUUID())

        assertEquals(ids, SensorSessionSyncedIds.parse(SensorSessionSyncedIds.encode(ids)))
    }

    @Test
    fun `add appends id to existing set without mutating the input`() {
        val existing = listOf(UUID.randomUUID().toString())
        val newId = UUID.randomUUID()

        val updated = SensorSessionSyncedIds.add(existing, newId)

        assertTrue(updated.contains(newId.toString()))
        assertEquals(2, updated.size)
        assertEquals(1, existing.size)
    }
}
