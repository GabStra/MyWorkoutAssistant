package com.gabstra.myworkoutassistant.shared

import androidx.compose.runtime.MutableState

data class ExerciseGroup(
    val name:  String,
    val sets: Int,
    val exercises: List<Exercise>,
    val restTimeInSec: Int,
    val enabled: Boolean = true
)