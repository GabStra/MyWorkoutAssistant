package com.gabstra.myworkoutassistant.shared.running

import java.util.Locale
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.roundToInt

/** Returns a readable 1, 2, or 5 based distance at or below the requested map width. */
fun niceRunningMapScaleDistance(targetMeters: Double): Double {
    if (!targetMeters.isFinite() || targetMeters <= 0.0) return 1.0
    val magnitude = 10.0.pow(floor(log10(targetMeters)))
    return listOf(1.0, 2.0, 5.0, 10.0)
        .map { it * magnitude }
        .lastOrNull { it <= targetMeters }
        ?: magnitude
}

fun formatRunningMapScaleDistance(distanceMeters: Double): String = when {
    distanceMeters >= 1_000.0 -> {
        val kilometers = distanceMeters / 1_000.0
        val value = if (kilometers % 1.0 == 0.0) kilometers.roundToInt().toString()
        else String.format(Locale.getDefault(), "%.1f", kilometers)
        "$value km"
    }
    distanceMeters >= 10.0 -> "${distanceMeters.roundToInt()} m"
    distanceMeters >= 1.0 -> "${String.format(Locale.getDefault(), "%.1f", distanceMeters)} m"
    else -> "${String.format(Locale.getDefault(), "%.2f", distanceMeters)} m"
}
