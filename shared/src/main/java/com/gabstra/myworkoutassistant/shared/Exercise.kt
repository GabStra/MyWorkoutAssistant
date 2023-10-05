package com.gabstra.myworkoutassistant.shared

import androidx.compose.runtime.MutableState

data class Exercise(
    val name: String,
    val reps: Int,
    val weight: Float?=null,
    val enabled: Boolean = true
)