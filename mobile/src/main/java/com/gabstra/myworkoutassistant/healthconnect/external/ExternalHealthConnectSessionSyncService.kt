package com.gabstra.myworkoutassistant.healthconnect.external

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId

private const val DEFAULT_EXTERNAL_SESSION_LOOKBACK_DAYS = 365L

class ExternalHealthConnectSessionSyncService(
    private val context: Context,
    private val healthConnectClient: HealthConnectClient,
    private val externalDatabase: ExternalHealthConnectSessionDatabase,
    private val appDatabase: AppDatabase,
) {
    suspend fun refreshRecentSessions(
        lookbackDays: Long = DEFAULT_EXTERNAL_SESSION_LOOKBACK_DAYS,
    ) = withContext(Dispatchers.IO) {
        val zoneId = ZoneId.systemDefault()
        val endInstant = Instant.now()
        val startInstant = endInstant.minusSeconds(lookbackDays.coerceAtLeast(1) * 24 * 60 * 60)
        val syncTimestamp = LocalDateTime.now()

        val rawSessions = readExerciseSessions(startInstant, endInstant, zoneId)
        val rawHeartRateSamples = readHeartRateSamples(startInstant, endInstant, zoneId)
        val workoutHistoriesInRange = appDatabase.workoutHistoryDao()
            .getCompletedWorkoutHistoriesBetweenInclusive(
                startInclusive = LocalDateTime.ofInstant(startInstant, zoneId).toLocalDate(),
                endInclusive = LocalDateTime.ofInstant(endInstant, zoneId).toLocalDate(),
            )
        val localWorkoutHistoryIds = workoutHistoriesInRange
            .map { it.id.toString() }
            .toSet()
        val appOwnedSessionWindows = workoutHistoriesInRange.map { history ->
            AppOwnedSessionWindow(
                startTime = history.startTime,
                endTime = history.startTime.plusSeconds(history.duration.toLong().coerceAtLeast(0L)),
            )
        }

        val importedSessions = buildExternalHealthConnectSessionEntities(
            sessions = rawSessions,
            heartRateSamples = rawHeartRateSamples,
            appOwnedWorkoutHistoryIds = localWorkoutHistoryIds,
            appOwnedSessionWindows = appOwnedSessionWindows,
            appPackageName = context.packageName,
            syncedAt = syncTimestamp,
            resolveSourceAppLabel = ::resolveSourceAppLabel,
        )

        val dao = externalDatabase.externalHealthConnectSessionDao()
        dao.upsertAll(importedSessions)

        val existingIdsInRange = dao.getIdsInRange(
            startInclusive = LocalDateTime.ofInstant(startInstant, zoneId),
            endInclusive = LocalDateTime.ofInstant(endInstant, zoneId),
        )
        val importedIds = importedSessions.map { it.id }.toSet()
        val idsToDelete = existingIdsInRange.filterNot(importedIds::contains)
        if (idsToDelete.isNotEmpty()) {
            dao.deleteByIds(idsToDelete)
        }
    }

    private suspend fun readExerciseSessions(
        startInstant: Instant,
        endInstant: Instant,
        zoneId: ZoneId,
    ): List<RawExternalExerciseSession> {
        val sessions = mutableListOf<RawExternalExerciseSession>()
        var pageToken: String? = null

        do {
            val response = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = ExerciseSessionRecord::class,
                    timeRangeFilter = TimeRangeFilter.between(startInstant, endInstant),
                    pageToken = pageToken,
                )
            )

            sessions += response.records.map { record ->
                RawExternalExerciseSession(
                    id = record.metadata.id,
                    clientRecordId = record.metadata.clientRecordId,
                    title = record.title,
                    startTime = LocalDateTime.ofInstant(record.startTime, zoneId),
                    endTime = LocalDateTime.ofInstant(record.endTime, zoneId),
                    exerciseType = record.exerciseType,
                    sourcePackageName = record.metadata.dataOrigin.packageName,
                )
            }

            pageToken = response.pageToken
        } while (pageToken != null)

        return sessions
    }

    private suspend fun readHeartRateSamples(
        startInstant: Instant,
        endInstant: Instant,
        zoneId: ZoneId,
    ): List<RawExternalHeartRateSample> {
        val samples = mutableListOf<RawExternalHeartRateSample>()
        var pageToken: String? = null

        do {
            val response = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = HeartRateRecord::class,
                    timeRangeFilter = TimeRangeFilter.between(startInstant, endInstant),
                    pageToken = pageToken,
                )
            )

            response.records.forEach { record ->
                record.samples.forEach { sample ->
                    if (sample.beatsPerMinute > 0) {
                        samples += RawExternalHeartRateSample(
                            time = LocalDateTime.ofInstant(sample.time, zoneId),
                            beatsPerMinute = sample.beatsPerMinute.toInt(),
                        )
                    }
                }
            }

            pageToken = response.pageToken
        } while (pageToken != null)

        return samples
    }

    private fun resolveSourceAppLabel(packageName: String?): String? {
        if (packageName.isNullOrBlank()) {
            return null
        }

        return runCatching {
            val applicationInfo = context.packageManager.getApplicationInfo(packageName, 0)
            context.packageManager.getApplicationLabel(applicationInfo).toString()
        }.getOrNull()
    }
}
