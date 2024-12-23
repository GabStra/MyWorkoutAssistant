package com.gabstra.myworkoutassistant.composable

import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.data.VibrateGentle
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun CustomBackHandler(
    enabled: Boolean = true,
    onSinglePress: () -> Unit,
    onDoublePress: () -> Unit,
    doublePressDuration: Long = 400L,
) {
    // Track the last back press time
    var lastBackPressTime by remember { mutableLongStateOf(0L) }

    // Track whether we're currently in a potential double-press window
    var isInDoublePressPeriod by remember { mutableStateOf(false) }

    // Coroutine scope for delayed operations
    val scope = rememberCoroutineScope()

    // Jobs for both single and double press handlers
    var singlePressJob by remember { mutableStateOf<Job?>(null) }
    var doublePressResetJob by remember { mutableStateOf<Job?>(null) }

    // Cleanup on disposal
    DisposableEffect(Unit) {
        onDispose {
            singlePressJob?.cancel()
            doublePressResetJob?.cancel()
        }
    }

    BackHandler(enabled = enabled) {
        val currentTime = System.currentTimeMillis()
        val timeSinceLastPress = currentTime - lastBackPressTime

        when {
            // If we receive a press during the double-press window
            timeSinceLastPress < doublePressDuration && isInDoublePressPeriod -> {
                // Cancel any pending single-press action
                singlePressJob?.cancel()
                doublePressResetJob?.cancel()

                // Reset state
                lastBackPressTime = 0
                isInDoublePressPeriod = false

                // Execute double-press action
                onDoublePress()
            }

            // First press or press after the double-press window
            else -> {
                // Update state for tracking double press
                lastBackPressTime = currentTime
                isInDoublePressPeriod = true

                // Schedule the single-press action with state reset
                singlePressJob?.cancel()
                singlePressJob = scope.launch {
                    delay(doublePressDuration)
                    onSinglePress()
                    // Reset state after single press is executed
                    isInDoublePressPeriod = false
                    lastBackPressTime = 0
                }
            }
        }
    }
}