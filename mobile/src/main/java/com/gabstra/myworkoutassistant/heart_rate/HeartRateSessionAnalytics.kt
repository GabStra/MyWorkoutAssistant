package com.gabstra.myworkoutassistant.heart_rate

import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.getMaxHeartRate
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.compose.cartesian.data.LineCartesianLayerModel
import kotlin.math.roundToLong

data class HeartRateSessionAnalysis(
    val chartModel: CartesianChartModel,
    val zoneCounts: Map<Int, Int>,
    val validHeartRateCount: Int,
    val averageHeartRate: Int,
    val minHeartRate: Int,
    val maxHeartRate: Int,
    val minChartY: Double,
    val durationSeconds: Int,
)

data class HeartRateZoneSegment(
    val zoneIndex: Int,
    val xValues: List<Double>,
    val yValues: List<Double>,
)

fun analyzeHeartRateSession(
    heartRateSeries: List<Int>,
    durationSeconds: Int,
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
): HeartRateSessionAnalysis? {
    val validHeartRates = heartRateSeries.filter { it > 0 }
    if (validHeartRates.isEmpty()) {
        return null
    }

    val minHeartRate = validHeartRates.min()
    val zoneCounts = mutableMapOf<Int, Int>().apply {
        colorsByZone.indices.forEach { put(it, 0) }
    }
    validHeartRates.forEach { heartRate ->
        val zone = getZoneFromHeartRate(
            heartRate = heartRate.toDouble(),
            userAge = userAge,
            measuredMaxHeartRate = measuredMaxHeartRate,
            restingHeartRate = restingHeartRate,
        )
        zoneCounts[zone] = (zoneCounts[zone] ?: 0) + 1
    }

    val chartSeries = heartRateSeries.map {
        if (it == 0) {
            minHeartRate.toDouble()
        } else {
            it.toDouble()
        }
    }

    return HeartRateSessionAnalysis(
        chartModel = CartesianChartModel(
            LineCartesianLayerModel.build {
                series(chartSeries)
            }
        ),
        zoneCounts = zoneCounts,
        validHeartRateCount = validHeartRates.size,
        averageHeartRate = validHeartRates.average().toInt(),
        minHeartRate = minHeartRate,
        maxHeartRate = validHeartRates.max(),
        minChartY = minHeartRate.toDouble(),
        durationSeconds = durationSeconds.coerceAtLeast(heartRateSeries.lastIndex),
    )
}

fun getHeartRateZoneGuideValues(
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
): List<Double> {
    val zoneBounds = getHeartRateZoneBounds(userAge, measuredMaxHeartRate, restingHeartRate)
    return (zoneBounds.drop(1).map { it.first.toDouble() } + getMaxHeartRate(userAge).toDouble())
        .distinct()
        .sorted()
}

fun getHeartRateZoneBounds(
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
): List<IntRange> {
    val zoneStarts = zoneRanges.map { (lowerBoundPercent, _) ->
        getHeartRateFromPercentage(
            lowerBoundPercent,
            userAge,
            measuredMaxHeartRate,
            restingHeartRate,
        )
    }
    val absoluteMax = getHeartRateFromPercentage(
        zoneRanges.last().second,
        userAge,
        measuredMaxHeartRate,
        restingHeartRate,
    )

    return zoneStarts.indices.map { zoneIndex ->
        val lowerBound = zoneStarts[zoneIndex]
        val upperBound = if (zoneIndex < zoneStarts.lastIndex) {
            zoneStarts[zoneIndex + 1] - 1
        } else {
            absoluteMax
        }
        lowerBound..maxOf(lowerBound, upperBound)
    }
}

fun getZoneFromHeartRate(
    heartRate: Double,
    userAge: Int,
    measuredMaxHeartRate: Int? = null,
    restingHeartRate: Int? = null,
): Int {
    val zoneBounds = getHeartRateZoneBounds(userAge, measuredMaxHeartRate, restingHeartRate)
    for (zoneIndex in zoneBounds.indices.reversed()) {
        val zoneRange = zoneBounds[zoneIndex]
        if (heartRate in zoneRange.first.toDouble()..zoneRange.last.toDouble()) {
            return zoneIndex
        }
    }

    return when {
        heartRate < zoneBounds.first().first.toDouble() -> 0
        heartRate > zoneBounds.last().last.toDouble() -> zoneBounds.lastIndex
        else -> 0
    }
}

private fun roundXToSupportedPrecision(value: Double): Double {
    return (value * 10_000.0).roundToLong() / 10_000.0
}

fun buildHeartRateZoneSegments(
    values: List<Double>,
    thresholds: List<Double>,
    zoneFromValue: (Double) -> Int,
): List<HeartRateZoneSegment> {
    if (values.size < 2) return emptyList()

    val segments = mutableListOf<HeartRateZoneSegment>()
    var currentX = mutableListOf(0.0)
    var currentY = mutableListOf(values.first())
    var currentZone = zoneFromValue(values.first())

    fun closeCurrentSegment() {
        if (currentX.size >= 2 && currentY.size >= 2) {
            segments += HeartRateZoneSegment(
                zoneIndex = currentZone,
                xValues = currentX.toList(),
                yValues = currentY.toList(),
            )
        }
    }

    for (index in 0 until values.lastIndex) {
        val x1 = index.toDouble()
        val x2 = (index + 1).toDouble()
        val y1 = values[index]
        val y2 = values[index + 1]

        if (kotlin.math.abs(y2 - y1) < 1e-9) {
            currentX.add(x2)
            currentY.add(y2)
            continue
        }

        val minY = minOf(y1, y2)
        val maxY = maxOf(y1, y2)
        val isAscending = y2 > y1
        val crossings = thresholds
            .filter { it > minY && it < maxY }
            .sortedBy { if (isAscending) it else -it }

        if (crossings.isEmpty()) {
            currentX.add(x2)
            currentY.add(y2)
            continue
        }

        for (threshold in crossings) {
            val t = (threshold - y1) / (y2 - y1)
            val crossingX = roundXToSupportedPrecision(x1 + (x2 - x1) * t)

            currentX.add(crossingX)
            currentY.add(threshold)
            closeCurrentSegment()

            val epsilon = if (isAscending) 1e-4 else -1e-4
            currentZone = zoneFromValue(threshold + epsilon)
            currentX = mutableListOf(crossingX)
            currentY = mutableListOf(threshold)
        }

        currentX.add(x2)
        currentY.add(y2)
    }

    closeCurrentSegment()
    return segments
}
