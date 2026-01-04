package com.gabstra.myworkoutassistant.workout

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.view.WindowManager
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

fun Context.findActivity(): Activity? {
    var currentContext = this
    while (currentContext is ContextWrapper) {
        if (currentContext is Activity) {
            return currentContext
        }
        currentContext = currentContext.baseContext
    }
    return null
}

@Composable
fun KeepOn(
    appViewModel: WorkoutViewModel,
    enableDimming: Boolean = false,
    dimDelay: Long = 15000L, // Delay before dimming the screen
    content: @Composable () -> Unit
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val window = activity?.window

    val scope = rememberCoroutineScope()

    var isDimmed by remember { mutableStateOf(false) }
    var dimmingJob by remember { mutableStateOf<Job?>(null) }

    val updatedEnableDimming by rememberUpdatedState(enableDimming)
    val updatedDimDelay by rememberUpdatedState(dimDelay)

    fun setScreenBrightness(brightness: Float) {
        window?.attributes = window?.attributes?.apply {
            screenBrightness = brightness
        }
    }

    var isCoolingDown by remember { mutableStateOf(false) }

    fun wakeUpAndResetTimer() {
        dimmingJob?.cancel()

        if (isDimmed) {
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
            isDimmed = false
        }

        if (updatedEnableDimming) {
            dimmingJob = scope.launch {
                delay(updatedDimDelay)
                setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_OFF) // Use OFF for minimal brightness
                isDimmed = true
            }
        }
    }

    LifecycleObserver(
        onPaused = {
            dimmingJob?.cancel()
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
            isDimmed = false
        },
        onStarted = {
            window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            wakeUpAndResetTimer()
        },
        onResumed = {
            window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            wakeUpAndResetTimer()
        }
    )

    DisposableEffect(Unit) {
        onDispose {
            dimmingJob?.cancel()
            // Ensure flags and brightness are reset when leaving the screen
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
        }
    }

    // Effect to handle external wake-up calls from the ViewModel
    LaunchedEffect(Unit) {
        appViewModel.lightScreenUp.collect {
            wakeUpAndResetTimer()
        }
    }

    LaunchedEffect(enableDimming) {
        if(!enableDimming){
            dimmingJob?.cancel()
            window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
            isDimmed = false
        }else{
            wakeUpAndResetTimer()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Transparent)
            .then(
                if(enableDimming){
                    Modifier.pointerInput(Unit) {
                        awaitPointerEventScope {
                            while (true) {
                                awaitPointerEvent().changes.firstOrNull { it.pressed }?.let {
                                    if (!isCoolingDown) {
                                        isCoolingDown = true

                                        scope.launch {
                                            wakeUpAndResetTimer()
                                            delay(1000L)
                                            isCoolingDown = false
                                        }
                                    }
                                }
                            }
                        }
                    }
                }else{
                    Modifier
                })
    ) {
        content()
    }
}
