package com.gabstra.myworkoutassistant.heart_rate

import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.colorsByZone
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.getMaxHeartRate
import com.gabstra.myworkoutassistant.shared.zoneRanges
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianChartModel
import com.patrykandpatrick.vico.compose.cartesian.data.LineCartesianLayerModel
import kotlin.math.roundToLong

data class HeartRateSessionAnalysis(
    val chartModel: CartesianChartModel,
    /** Seconds spent per zone, weighted by each sample's real duration. */
    val zoneCounts: Map<Int, Double>,
    val validHeartRateCount: Int,
    val averageHeartRate: Int,
    val minHeartRate: Int,
    val maxHeartRate: Int,
    val minChartY: Double,
    val durationSeconds: Int,
    /** Every other source recorded alongside the of-record stream, in display order. */
    val extraSources: List<HeartRateSourceSeries> = emptyList(),
    /** Coverage figures for each extra source. */
    val extraSummaries: List<HeartRateSourceSummary> = emptyList(),
)

data class HeartRateSourceSeries(
    val label: String,
    val samples: List<Int>,
    /** Sample offsets in ms; empty falls back to one sample per second. */
    val timesMs: List<Long> = emptyList(),
)

data class HeartRateSourceSummary(
    val label: String,
    val averageHeartRate: Int,
    val minHeartRate: Int,
    val maxHeartRate: Int,
)

/**
 * Turns a persisted per-source stream map into the extra series plotted beside the of-record one.
 * Ordering is deterministic (watch, then the enum's device order) so legend colours stay stable.
 */
fun buildExtraHeartRateSeries(
    streams: Map<String, List<Int>>,
    times: Map<String, List<Long>> = emptyMap(),
    activeSource: HeartRateSource?,
    labelForSource: (HeartRateSource) -> String = HeartRateSource::displayName,
): List<HeartRateSourceSeries> = streams
    .mapNotNull { (rawName, samples) ->
        val source = HeartRateSource.fromName(rawName) ?: return@mapNotNull null
        if (source == activeSource || samples.isEmpty()) return@mapNotNull null
        Triple(source, samples, times[rawName].orEmpty())
    }
    .sortedBy { (source, _, _) ->
        if (source == HeartRateSource.WATCH_SENSOR) -1 else source.ordinal
    }
    .map { (source, samples, streamTimes) ->
        HeartRateSourceSeries(labelForSource(source), samples, streamTimes)
    }

/** Real sample times for the stream of record, or null for records without timestamps. */
fun com.gabstra.myworkoutassistant.shared.WorkoutHistory.heartRateTimesForOfRecord(): List<Long>? =
    heartRateSource?.let { heartRateStreamTimes[it] }

/**
 * Sample times aligned with [samples]. Records captured before timestamps existed fall back to
 * the old one-sample-per-second interpretation instead of pretending to have real times.
 */
fun alignedHeartRateTimes(timesMs: List<Long>?, samples: Int): List<Long> =
    if (timesMs != null && timesMs.size == samples) timesMs
    else List(samples) { it * 1000L }

/** Seconds this sample represents; a long dropout is capped so it cannot inflate zone time. */
fun heartRateSampleSeconds(timesMs: List<Long>, index: Int, maxGapMs: Long = 5_000L): Double {
    val start = timesMs[index]
    val end = if (index < timesMs.lastIndex) timesMs[index + 1] else start + 1_000L
    return ((end - start).coerceIn(0L, maxGapMs)).toDouble() / 1000.0
}

/** Mean heart rate weighted by how long each sample was current. */
fun timeWeightedAverage(samples: List<Int>, timesMs: List<Long>): Int? {
    if (samples.isEmpty() || timesMs.size != samples.size) return null
    var sum = 0.0
    var seconds = 0.0
    samples.forEachIndexed { index, bpm ->
        if (bpm <= 0) return@forEachIndexed
        val weight = heartRateSampleSeconds(timesMs, index)
        sum += bpm * weight
        seconds += weight
    }
    return if (seconds > 0.0) (sum / seconds).toInt() else null
}

/** Seconds spent inside [lowHr]..[highHr] between two offsets, using real sample times. */
fun secondsInHeartRateRange(
    samples: List<Int>,
    timesMs: List<Long>,
    fromMs: Long,
    toMs: Long,
    lowHr: Int,
    highHr: Int,
): Double {
    if (timesMs.size != samples.size || toMs <= fromMs) return 0.0
    var seconds = 0.0
    samples.forEachIndexed { index, bpm ->
        val start = timesMs[index]
        if (start < fromMs || start >= toMs || bpm !in lowHr..highHr) return@forEachIndexed
        val end = minOf(
            if (index < timesMs.lastIndex) timesMs[index + 1] else start + 1_000L,
            toMs,
        )
        seconds += ((end - start).coerceAtLeast(0L).coerceAtMost(5_000L)).toDouble() / 1000.0
    }
    return seconds
}

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
    heartRateTimesMs: List<Long>? = null,
    extraSeries: List<HeartRateSourceSeries> = emptyList(),
): HeartRateSessionAnalysis? {
    val validHeartRates = heartRateSeries.filter { it > 0 }
    if (validHeartRates.isEmpty()) {
        return null
    }

    val times = alignedHeartRateTimes(heartRateTimesMs, heartRateSeries.size)
    val minHeartRate = validHeartRates.min()
    val zoneCounts = mutableMapOf<Int, Double>().apply {
        colorsByZone.indices.forEach { put(it, 0.0) }
    }
    heartRateSeries.forEachIndexed { index, heartRate ->
        if (heartRate <= 0) return@forEachIndexed
        val seconds = heartRateSampleSeconds(times, index)
        val zone = getZoneFromHeartRate(
            heartRate = heartRate.toDouble(),
            userAge = userAge,
            measuredMaxHeartRate = measuredMaxHeartRate,
            restingHeartRate = restingHeartRate,
        )
        zoneCounts[zone] = (zoneCounts[zone] ?: 0.0) + seconds
    }

    val chartSeries = heartRateSeries.map {
        if (it == 0) {
            minHeartRate.toDouble()
        } else {
            it.toDouble()
        }
    }
    // Only sources with usable samples get a line; their summaries drive the legend.
    val plottedSources = extraSeries.filter { source -> source.samples.any { it > 0 } }
    val extraSummaries = plottedSources.mapNotNull { source ->
        val rates = source.samples.filter { it > 0 }
        if (rates.isEmpty()) return@mapNotNull null
        HeartRateSourceSummary(
            label = source.label,
            averageHeartRate = timeWeightedAverage(
                samples = source.samples,
                timesMs = alignedHeartRateTimes(source.timesMs, source.samples.size),
            ) ?: rates.average().toInt(),
            minHeartRate = rates.min(),
            maxHeartRate = rates.max(),
        )
    }

    val chartModel = CartesianChartModel(
        LineCartesianLayerModel.build {
            series(
                x = times.map { it / 1000.0 },
                y = chartSeries,
            )
            plottedSources.forEach { source ->
                val minimum = source.samples.filter { it > 0 }.min()
                series(
                    x = alignedHeartRateTimes(source.timesMs, source.samples.size)
                        .map { it / 1000.0 },
                    y = source.samples.map { rate ->
                        if (rate == 0) minimum.toDouble() else rate.toDouble()
                    },
                )
            }
        }
    )

    return HeartRateSessionAnalysis(
        chartModel = chartModel,
        zoneCounts = zoneCounts,
        validHeartRateCount = validHeartRates.size,
        averageHeartRate = timeWeightedAverage(heartRateSeries, times)
            ?: validHeartRates.average().toInt(),
        minHeartRate = minHeartRate,
        maxHeartRate = validHeartRates.max(),
        minChartY = minOf(
            minHeartRate,
            extraSummaries.minOfOrNull { it.minHeartRate } ?: minHeartRate,
        ).toDouble(),
        durationSeconds = durationSeconds.coerceAtLeast((times.last() / 1000L).toInt()),
        extraSources = plottedSources,
        extraSummaries = extraSummaries,
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
