package com.gabstra.myworkoutassistant.healthconnect.external

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime

class ExternalHealthConnectSessionMapperTest {
    @Test
    fun buildExternalHealthConnectSessionEntities_mapsFullHrSession() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0, 0)
        val end = start.plusMinutes(2)

        val sessions = listOf(
            RawExternalExerciseSession(
                id = "external-1",
                clientRecordId = null,
                title = "Morning Run",
                startTime = start,
                endTime = end,
                exerciseType = 56,
                sourcePackageName = "com.example.tracker",
            )
        )
        val heartRateSamples = listOf(
            RawExternalHeartRateSample(start.plusSeconds(0), 120),
            RawExternalHeartRateSample(start.plusSeconds(30), 130),
            RawExternalHeartRateSample(start.plusSeconds(60), 140),
        )

        val result = buildExternalHealthConnectSessionEntities(
            sessions = sessions,
            heartRateSamples = heartRateSamples,
            appOwnedWorkoutHistoryIds = emptySet(),
            appOwnedSessionWindows = emptyList(),
            appPackageName = "com.gabstra.myworkoutassistant",
            syncedAt = end,
            resolveSourceAppLabel = { "Tracker" },
        )

        assertEquals(1, result.size)
        val session = result.single()
        assertEquals("Morning Run", session.title)
        assertEquals("Tracker", session.sourceAppLabel)
        assertEquals(3, session.heartRateSampleCount)
        assertTrue(session.hasHeartRateData)
        assertEquals(120, session.minHeartRate)
        assertEquals(140, session.maxHeartRate)
        assertTrue(session.averageHeartRate in 129..136)
    }

    @Test
    fun buildExternalHealthConnectSessionEntities_keepsSessionWithoutHr() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0, 0)
        val end = start.plusMinutes(45)

        val result = buildExternalHealthConnectSessionEntities(
            sessions = listOf(
                RawExternalExerciseSession(
                    id = "external-2",
                    clientRecordId = null,
                    title = null,
                    startTime = start,
                    endTime = end,
                    exerciseType = 2,
                    sourcePackageName = "com.example.walker",
                )
            ),
            heartRateSamples = emptyList(),
            appOwnedWorkoutHistoryIds = emptySet(),
            appOwnedSessionWindows = emptyList(),
            appPackageName = "com.gabstra.myworkoutassistant",
            syncedAt = end,
            resolveSourceAppLabel = { "Walker" },
        )

        assertEquals(1, result.size)
        val session = result.single()
        assertFalse(session.hasHeartRateData)
        assertEquals(0, session.heartRateSampleCount)
        assertNull(session.averageHeartRate)
        assertTrue(session.heartRateSamples.isEmpty())
    }

    @Test
    fun buildExternalHealthConnectSessionEntities_filtersAppOwnedSessions() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0, 0)
        val end = start.plusMinutes(30)

        val result = buildExternalHealthConnectSessionEntities(
            sessions = listOf(
                RawExternalExerciseSession(
                    id = "app-owned",
                    clientRecordId = "history-123",
                    title = "App Session",
                    startTime = start,
                    endTime = end,
                    exerciseType = 56,
                    sourcePackageName = "com.gabstra.myworkoutassistant",
                ),
                RawExternalExerciseSession(
                    id = "external-3",
                    clientRecordId = null,
                    title = "Imported Session",
                    startTime = start.plusHours(1),
                    endTime = end.plusHours(1),
                    exerciseType = 56,
                    sourcePackageName = "com.example.tracker",
                )
            ),
            heartRateSamples = emptyList(),
            appOwnedWorkoutHistoryIds = setOf("history-123"),
            appOwnedSessionWindows = emptyList(),
            appPackageName = "com.gabstra.myworkoutassistant",
            syncedAt = end,
            resolveSourceAppLabel = { "Tracker" },
        )

        assertEquals(listOf("external-3"), result.map { it.id })
    }

    @Test
    fun normalizeExternalHeartRateSamples_expandsSparseSeriesAcrossDuration() {
        val normalized = normalizeExternalHeartRateSamples(
            samples = listOf(
                ExternalHeartRateSample(offsetSeconds = 2, beatsPerMinute = 120),
                ExternalHeartRateSample(offsetSeconds = 5, beatsPerMinute = 132),
            ),
            durationSeconds = 7,
        )

        assertEquals(listOf(0, 0, 120, 120, 120, 132, 132, 132), normalized)
    }

    @Test
    fun buildExternalHealthConnectSessionEntities_filtersClearlyOverlappingInternalSessions() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0, 0)
        val end = start.plusMinutes(50)

        val result = buildExternalHealthConnectSessionEntities(
            sessions = listOf(
                RawExternalExerciseSession(
                    id = "external-overlap",
                    clientRecordId = null,
                    title = "Whoop Strength Trainer",
                    startTime = start.plusMinutes(3),
                    endTime = end.minusMinutes(2),
                    exerciseType = 56,
                    sourcePackageName = "com.example.whoop",
                )
            ),
            heartRateSamples = emptyList(),
            appOwnedWorkoutHistoryIds = emptySet(),
            appOwnedSessionWindows = listOf(
                AppOwnedSessionWindow(
                    startTime = start,
                    endTime = end,
                )
            ),
            appPackageName = "com.gabstra.myworkoutassistant",
            syncedAt = end,
            resolveSourceAppLabel = { "Whoop" },
        )

        assertTrue(result.isEmpty())
    }

    @Test
    fun buildExternalHealthConnectSessionEntities_keepsExternalSessionsThatDoNotCloselyMatchInternalOnes() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0, 0)
        val end = start.plusMinutes(50)

        val result = buildExternalHealthConnectSessionEntities(
            sessions = listOf(
                RawExternalExerciseSession(
                    id = "external-separate",
                    clientRecordId = null,
                    title = "Evening Walk",
                    startTime = start.plusMinutes(40),
                    endTime = end.plusMinutes(35),
                    exerciseType = 2,
                    sourcePackageName = "com.example.walker",
                )
            ),
            heartRateSamples = emptyList(),
            appOwnedWorkoutHistoryIds = emptySet(),
            appOwnedSessionWindows = listOf(
                AppOwnedSessionWindow(
                    startTime = start,
                    endTime = end,
                )
            ),
            appPackageName = "com.gabstra.myworkoutassistant",
            syncedAt = end,
            resolveSourceAppLabel = { "Walker" },
        )

        assertEquals(listOf("external-separate"), result.map { it.id })
    }

    @Test
    fun buildExternalHealthConnectSessionEntities_mergesOverlappingExternalSessions() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0)
        val result = buildExternalHealthConnectSessionEntities(
            sessions = listOf(
                rawSession(
                    id = "watch-session",
                    title = "Strength training",
                    start = start,
                    end = start.plusMinutes(50),
                    source = "com.example.watch",
                ),
                rawSession(
                    id = "phone-session",
                    title = null,
                    start = start.plusMinutes(3),
                    end = start.plusMinutes(55),
                    source = "com.example.phone",
                ),
            ),
            heartRateSamples = listOf(
                RawExternalHeartRateSample(start.plusMinutes(1), 120),
                RawExternalHeartRateSample(start.plusMinutes(54), 135),
            ),
            appOwnedWorkoutHistoryIds = emptySet(),
            appOwnedSessionWindows = emptyList(),
            appPackageName = "com.gabstra.myworkoutassistant",
            syncedAt = start.plusHours(1),
            resolveSourceAppLabel = { it },
        )

        val merged = result.single()
        assertTrue(merged.id.startsWith("merged:"))
        assertEquals(start, merged.startTime)
        assertEquals(start.plusMinutes(55), merged.endTime)
        assertEquals(55 * 60, merged.durationSeconds)
        assertEquals("Strength training", merged.title)
        assertNull(merged.sourcePackageName)
        assertEquals("Multiple sources", merged.sourceAppLabel)
        assertEquals(2, merged.heartRateSampleCount)
    }

    @Test
    fun buildExternalHealthConnectSessionEntities_mergesTransitiveOverlaps() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0)
        val sessions = listOf(
            rawSession("one", null, start, start.plusMinutes(20), "source"),
            rawSession("two", null, start.plusMinutes(15), start.plusMinutes(35), "source"),
            rawSession("three", null, start.plusMinutes(30), start.plusMinutes(50), "source"),
        )

        val result = buildExternalHealthConnectSessionEntities(
            sessions = sessions,
            heartRateSamples = emptyList(),
            appOwnedWorkoutHistoryIds = emptySet(),
            appOwnedSessionWindows = emptyList(),
            appPackageName = "app",
            syncedAt = start.plusHours(1),
            resolveSourceAppLabel = { "Tracker" },
        )

        assertEquals(1, result.size)
        assertEquals(start.plusMinutes(50), result.single().endTime)
    }

    @Test
    fun buildExternalHealthConnectSessionEntities_keepsTouchingSessionsSeparate() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0)
        val sessions = listOf(
            rawSession("one", null, start, start.plusMinutes(20), "source"),
            rawSession("two", null, start.plusMinutes(20), start.plusMinutes(40), "source"),
        )

        val result = buildExternalHealthConnectSessionEntities(
            sessions = sessions,
            heartRateSamples = emptyList(),
            appOwnedWorkoutHistoryIds = emptySet(),
            appOwnedSessionWindows = emptyList(),
            appPackageName = "app",
            syncedAt = start.plusHours(1),
            resolveSourceAppLabel = { "Tracker" },
        )

        assertEquals(2, result.size)
        assertEquals(setOf("one", "two"), result.map { it.id }.toSet())
    }

    @Test
    fun buildExternalHealthConnectSessionEntities_usesStableMergedId() {
        val start = LocalDateTime.of(2026, 5, 20, 10, 0)
        val sessions = listOf(
            rawSession("one", null, start, start.plusMinutes(30), "source-a"),
            rawSession("two", null, start.plusMinutes(2), start.plusMinutes(28), "source-b"),
        )
        fun map(input: List<RawExternalExerciseSession>) =
            buildExternalHealthConnectSessionEntities(
                sessions = input,
                heartRateSamples = emptyList(),
                appOwnedWorkoutHistoryIds = emptySet(),
                appOwnedSessionWindows = emptyList(),
                appPackageName = "app",
                syncedAt = start.plusHours(1),
                resolveSourceAppLabel = { it },
            ).single().id

        assertEquals(map(sessions), map(sessions.reversed()))
    }

    private fun rawSession(
        id: String,
        title: String?,
        start: LocalDateTime,
        end: LocalDateTime,
        source: String?,
    ) = RawExternalExerciseSession(
        id = id,
        clientRecordId = null,
        title = title,
        startTime = start,
        endTime = end,
        exerciseType = 56,
        sourcePackageName = source,
    )
}
