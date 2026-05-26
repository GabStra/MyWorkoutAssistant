package com.gabstra.myworkoutassistant.healthconnect.external

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime

data class ExternalHeartRateSample(
    val offsetSeconds: Int,
    val beatsPerMinute: Int,
)

@Entity(tableName = "external_health_connect_session")
data class ExternalHealthConnectSessionEntity(
    @PrimaryKey
    val id: String,
    val startTime: LocalDateTime,
    val endTime: LocalDateTime,
    val date: LocalDate,
    val time: LocalTime,
    val durationSeconds: Int,
    val exerciseType: Int,
    val exerciseTypeLabel: String,
    val title: String?,
    val sourcePackageName: String?,
    val sourceAppLabel: String?,
    val isAppOwned: Boolean,
    val lastSyncedAt: LocalDateTime,
    val averageHeartRate: Int?,
    val minHeartRate: Int?,
    val maxHeartRate: Int?,
    val heartRateSampleCount: Int,
    val hasHeartRateData: Boolean,
    val heartRateSamples: List<ExternalHeartRateSample>,
)

data class RawExternalExerciseSession(
    val id: String,
    val clientRecordId: String?,
    val title: String?,
    val startTime: LocalDateTime,
    val endTime: LocalDateTime,
    val exerciseType: Int,
    val sourcePackageName: String?,
)

data class RawExternalHeartRateSample(
    val time: LocalDateTime,
    val beatsPerMinute: Int,
)
