package com.gabstra.myworkoutassistant.composables

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun CustomBackHandler(
    enabled: Boolean = true,
    onSinglePress: () -> Unit,
    onDoublePress: () -> Unit,
    doublePressDuration: Long = 300L,
) {
    var lastBackPressTime by remember { mutableLongStateOf(0L) }
    var isInDoublePressPeriod by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    var pendingJob by remember { mutableStateOf<Job?>(null) }

    val resetState = {
        lastBackPressTime = 0L
        isInDoublePressPeriod = false
        pendingJob?.cancel()
        pendingJob = null
    }

    DisposableEffect(scope) {
        onDispose {
            pendingJob?.cancel()
        }
    }

    BackHandler(enabled = enabled) {
        val currentTime = System.currentTimeMillis()
        val timeSinceLastPress = currentTime - lastBackPressTime

        when {
            // Check for double press
            isInDoublePressPeriod && timeSinceLastPress < doublePressDuration -> {
                pendingJob?.cancel()
                resetState()
                scope.launch {
                    onDoublePress()
                }
            }
            // Handle first press or press after double press duration
            else -> {
                lastBackPressTime = currentTime
                isInDoublePressPeriod = true

                pendingJob?.cancel()
                pendingJob = scope.launch {
                    try {
                        delay(doublePressDuration)
                        if (isInDoublePressPeriod) {
                            onSinglePress()
                        }
                    } finally {
                        resetState()
                    }
                }
            }
        }
    }
}