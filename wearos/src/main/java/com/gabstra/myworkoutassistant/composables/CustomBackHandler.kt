package com.gabstra.myworkoutassistant.composables

import android.os.SystemClock
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
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
    doublePressDuration: Long = 300L,
) {
    val scope = rememberCoroutineScope()

    val currentPress by rememberUpdatedState(onPress)
    val currentSingle by rememberUpdatedState(onSinglePress)
    val currentDouble by rememberUpdatedState(onDoublePress)

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

        if (state.inWindow && dt < doublePressDuration) {
            reset()
            currentDouble()
        } else {
            state.lastPress = now
            state.inWindow = true
            state.job?.cancel()
            state.job = scope.launch {
                try {
                    delay(doublePressDuration)
                    if (state.inWindow) currentSingle()
                } finally {
                    reset()
                }
            }
        }
    }
}