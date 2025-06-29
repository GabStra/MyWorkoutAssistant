package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import com.gabstra.myworkoutassistant.data.findActivity

@Composable
fun LifecycleObserver(
    onStarted: () -> Unit = {},
    onPaused: () -> Unit = {},
    onStopped: () -> Unit = {},
    onResumed: () -> Unit = {}
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val lifecycleOwner = activity as LifecycleOwner
    val onStartedState = rememberUpdatedState(onStarted)
    val onPausedState = rememberUpdatedState(onPaused)
    val onStoppedState = rememberUpdatedState(onStopped)
    val onResumedState = rememberUpdatedState(onResumed)

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> onStartedState.value()
                Lifecycle.Event.ON_PAUSE -> onPausedState.value()
                Lifecycle.Event.ON_STOP -> onStoppedState.value()
                Lifecycle.Event.ON_RESUME -> onResumedState.value()
                else -> Unit
            }
        }

        lifecycleOwner.lifecycle.addObserver(observer)

        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }
}