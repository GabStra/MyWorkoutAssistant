package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.text.TextStyle

private const val ExerciseSetValueFontScale = 0.8f
private const val ExerciseTimerValueFontScale = 1.0f

internal fun TextStyle.compactExerciseSetValueStyle(): TextStyle =
    copy(fontSize = fontSize * ExerciseSetValueFontScale)

internal fun TextStyle.exerciseTimerValueStyle(): TextStyle =
    copy(fontSize = fontSize * ExerciseTimerValueFontScale)
