package com.gabstra.myworkoutassistant.composables

import android.os.SystemClock
import android.view.ViewConfiguration
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch


@Composable
fun CustomBackHandler(
    enabled: Boolean = true,
    onPress: () -> Unit,
    onSinglePress: () -> Unit,
    onDoublePress: () -> Unit,
) {
    val scope = rememberWearCoroutineScope()

    val currentPress by rememberUpdatedState(onPress)
    val currentSingle by rememberUpdatedState(onSinglePress)
    val currentDouble by rememberUpdatedState(onDoublePress)

    // Get platform double tap timeout once and cache it
    val doubleTapTimeout = remember { 
        ViewConfiguration.getDoubleTapTimeout().toLong() 
    }

    // Non-UI state holder to avoid recompositions
    val state = remember { object {
        var lastPress = 0L
        var inWindow = false
        var job: Job? = null
    }}

    fun reset() {
        state.lastPress = 0L
        state.inWindow = false
        state.job?.cancel()
        state.job = null
    }

    BackHandler(enabled) {
        val now = SystemClock.elapsedRealtime()
        val dt = now - state.lastPress

        currentPress()

        // Defensive check: ensure time delta is non-negative
        if (dt < 0) {
            reset()
            return@BackHandler
        }

        // Changed < to <= for inclusive boundary (matches platform behavior)
        if (state.inWindow && dt <= doubleTapTimeout) {
            reset()
            currentDouble()
        } else {
            state.lastPress = now
            state.inWindow = true
            state.job?.cancel()
            state.job = scope.launch {
                try {
                    delay(doubleTapTimeout)
                    if (state.inWindow) currentSingle()
                } finally {
                    reset()
                }
            }
        }
    }
}