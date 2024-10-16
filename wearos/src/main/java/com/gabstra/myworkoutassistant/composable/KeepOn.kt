package com.gabstra.myworkoutassistant.composable

import android.util.Log
import android.view.WindowManager
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.data.findActivity
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun KeepOn(
    enableDimming: Boolean = true, // Parameter to control dimming
    dimDelay: Long = 15000L, // Delay before dimming the screen
    content: @Composable () -> Unit
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val window = activity?.window

    var isDimmed by remember { mutableStateOf(false) }
    var dimmingJob by remember { mutableStateOf<Job?>(null) }

    val scope = rememberCoroutineScope()

    fun setScreenBrightness(brightness: Float) {
        window?.attributes = window?.attributes?.apply {
            screenBrightness = brightness
        }
    }

    fun resetDimming() {
        dimmingJob?.cancel()
        if (!enableDimming) return
        dimmingJob = scope.launch {
            delay(dimDelay)
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_OFF)
            isDimmed = true
        }
    }

    fun applyKeepScreenOnFlag() {
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    LifecycleObserver(
        onStarted = {
            applyKeepScreenOnFlag()
            if(!isDimmed) resetDimming()
        },
        onResumed = {
            applyKeepScreenOnFlag()
            if(!isDimmed) resetDimming()
        },
        onPaused = {
            isDimmed = false
        },
        onStopped = {
            isDimmed = false
        }
    )

    val keepScreenOnKey = remember { Any() }

    DisposableEffect(keepScreenOnKey) {
        applyKeepScreenOnFlag()

        onDispose {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
            isDimmed = false
        }
    }

    LaunchedEffect(enableDimming) {
        if (isDimmed && !enableDimming) {
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
            isDimmed = false
            return@LaunchedEffect
        }

        if(!isDimmed) resetDimming()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Transparent) // Ensure Box handles touch events
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    while (true) {
                        val event = awaitPointerEvent()
                        // Check if any pointer is down
                        if (event.changes.any { it.pressed }) {
                            if (isDimmed) {
                                setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
                                isDimmed = false
                            }
                            resetDimming()
                        }
                    }
                }
            }
    ){
        content()
    }
}