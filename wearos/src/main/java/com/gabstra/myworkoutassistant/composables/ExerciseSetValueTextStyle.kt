package com.gabstra.myworkoutassistant.composables

import androidx.compose.ui.text.TextStyle

private const val ExerciseSetValueFontScale = 0.8f

internal fun TextStyle.compactExerciseSetValueStyle(): TextStyle =
    copy(fontSize = fontSize * ExerciseSetValueFontScale)
