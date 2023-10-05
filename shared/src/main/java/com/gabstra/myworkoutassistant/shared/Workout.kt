package com.gabstra.myworkoutassistant.shared

data class Workout(
    val name: String,
    val description: String,
    val exerciseGroups: List<ExerciseGroup>,
    val restTimeInSec: Int,
    val enabled: Boolean = true
)
