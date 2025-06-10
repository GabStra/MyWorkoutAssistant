package com.gabstra.myworkoutassistant.composable

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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.findActivity
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun KeepOn(
    appViewModel: AppViewModel,
    enableDimming: Boolean = false,
    dimDelay: Long = 30000L, // Delay before dimming the screen
    content: @Composable () -> Unit
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val window = activity?.window
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()

    var isDimmed by remember { mutableStateOf(false) }
    var dimmingJob by remember { mutableStateOf<Job?>(null) }

    // Helper to set screen brightness
    fun setScreenBrightness(brightness: Float) {
        window?.attributes = window?.attributes?.apply {
            screenBrightness = brightness
        }
    }

    // Centralized function to wake the screen and reset the dimming timer
    fun wakeUpAndResetTimer() {
        // Cancel any pending dimming job
        dimmingJob?.cancel()

        // If the screen was dimmed, brighten it
        if (isDimmed) {
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
            isDimmed = false
        }

        // If dimming is enabled, start a new timer
        if (enableDimming) {
            dimmingJob = scope.launch {
                delay(dimDelay)
                setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_OFF) // Use OFF for minimal brightness
                isDimmed = true
            }
        }
    }

    // This effect manages adding/clearing the KEEP_SCREEN_ON flag and timers
    // It's tied to the lifecycle of the composable and the app state (resume/pause)
    DisposableEffect(lifecycleOwner, enableDimming) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> {
                    window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    // When the app resumes, reset the timer
                    wakeUpAndResetTimer()
                }
                Lifecycle.Event.ON_PAUSE -> {
                    // When the app is paused, release the lock to allow the screen to turn off
                    dimmingJob?.cancel()
                    window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                    setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
                    isDimmed = false
                }
                else -> {} // Handle other events if needed
            }
        }

        lifecycleOwner.lifecycle.addObserver(observer)

        // onDispose is called when the composable leaves the composition OR a key changes
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
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

    // When enableDimming is switched to false while the screen is dimmed, wake it up.
    // The main timer logic is already handled by re-triggering the DisposableEffect.
    LaunchedEffect(enableDimming) {
        wakeUpAndResetTimer()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Transparent)
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    while (true) {
                        // Wait for any pointer down event
                        awaitPointerEvent().changes.firstOrNull { it.pressed }?.let {
                            // On user interaction, wake the screen up
                            scope.launch {
                                wakeUpAndResetTimer()
                            }
                        }
                    }
                }
            }
    ) {
        content()
    }
}