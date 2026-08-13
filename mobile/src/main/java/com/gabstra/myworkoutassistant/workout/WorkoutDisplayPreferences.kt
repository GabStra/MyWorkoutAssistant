package com.gabstra.myworkoutassistant.workout

import android.content.Context
import androidx.core.content.edit
import kotlin.math.roundToInt

const val DefaultDimmedScreenBrightness = 0.15f
const val MinimumDimmedScreenBrightness = 0.05f
const val MaximumDimmedScreenBrightness = 0.50f
const val DimmedScreenBrightnessStep = 0.025f

fun snapDimmedScreenBrightness(brightness: Float): Float =
    (
        MinimumDimmedScreenBrightness +
            ((brightness - MinimumDimmedScreenBrightness) / DimmedScreenBrightnessStep).roundToInt() *
            DimmedScreenBrightnessStep
        )
        .coerceIn(MinimumDimmedScreenBrightness, MaximumDimmedScreenBrightness)

fun formatDimmedScreenBrightnessPercent(brightness: Float): String {
    val halfPercentUnits = (snapDimmedScreenBrightness(brightness) * 200f).roundToInt()
    return if (halfPercentUnits % 2 == 0) {
        "${halfPercentUnits / 2}%"
    } else {
        "${halfPercentUnits / 2}.5%"
    }
}

private const val PreferencesName = "workout_display_preferences"
private const val DimmedScreenBrightnessKey = "dimmed_screen_brightness"

object WorkoutDisplayPreferences {
    fun getDimmedScreenBrightness(context: Context): Float =
        context.getSharedPreferences(PreferencesName, Context.MODE_PRIVATE)
            .getFloat(DimmedScreenBrightnessKey, DefaultDimmedScreenBrightness)
            .let(::snapDimmedScreenBrightness)

    fun setDimmedScreenBrightness(context: Context, brightness: Float) {
        context.getSharedPreferences(PreferencesName, Context.MODE_PRIVATE).edit {
            putFloat(
                DimmedScreenBrightnessKey,
                snapDimmedScreenBrightness(brightness),
            )
        }
    }
}
