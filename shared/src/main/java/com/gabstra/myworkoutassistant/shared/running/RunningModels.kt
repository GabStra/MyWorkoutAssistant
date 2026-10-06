package com.gabstra.myworkoutassistant.shared.running

import java.util.Locale

enum class RunningEnvironment { OUTDOOR, TREADMILL }
enum class RunningTargetType { TIME, DISTANCE }
enum class DistanceUnit { KILOMETERS, MILES }

data class RunningPrescription(
    val environment: RunningEnvironment,
    val targetType: RunningTargetType,
    /** Target seconds for TIME, target meters for DISTANCE. */
    val targetValue: Double,
)

data class RunningRoutePoint(
    val latitude: Double,
    val longitude: Double,
    val elapsedTimeMillis: Long,
    val altitudeMeters: Double? = null,
)

data class RunningResult(
    val exerciseId: String,
    val elapsedTimeMillis: Long,
    val distanceMeters: Double?,
    val averagePaceSecondsPerKilometer: Double?,
    val averageHeartRateBpm: Int?,
    val minHeartRateBpm: Int?,
    val maxHeartRateBpm: Int?,
    val route: List<RunningRoutePoint> = emptyList(),
)

fun defaultDistanceUnit(locale: Locale = Locale.getDefault()): DistanceUnit =
    if (locale.country.uppercase(Locale.ROOT) in setOf("US", "LR", "MM")) {
        DistanceUnit.MILES
    } else {
        DistanceUnit.KILOMETERS
    }
