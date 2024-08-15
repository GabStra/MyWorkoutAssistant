package com.gabstra.myworkoutassistant.composable

import android.view.WindowManager
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.data.findActivity
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun KeepOn() {
    val context = LocalContext.current
    val activity = context.findActivity()
    val window = activity?.window
    val dimDelay = 10000L

    var isDimmed by remember { mutableStateOf(false) }
    var dimmingJob by remember { mutableStateOf<Job?>(null) }

    val scope = rememberCoroutineScope()

    fun resetDimming() {
        // Cancel any existing dimming job
        dimmingJob?.cancel()

        // Start a new dimming job
        dimmingJob = scope.launch {
            delay(dimDelay)
            window?.attributes = window?.attributes?.apply {
                screenBrightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_OFF
            }
            isDimmed = true
        }
    }

    DisposableEffect(Unit) {
        window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        onDispose {
            window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            window?.attributes = window?.attributes?.apply {
                screenBrightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
            }
        }
    }

    LaunchedEffect(Unit) {
        resetDimming() // Start the initial dimming timer
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Transparent) // Ensure Box handles touch events
            .pointerInput(Unit) {
                awaitPointerEventScope {
                    while (true) {
                        // Wait for any touch event
                        val event = awaitPointerEvent()

                        // Handle the press
                        if (event.changes.any { it.pressed }) {
                            if (isDimmed) {
                                window?.attributes = window?.attributes?.apply {
                                    screenBrightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
                                }
                                isDimmed = false
                            }
                            // Reset the dimming timer on any press
                            resetDimming()
                        }
                    }
                }
            }
            .pointerInteropFilter { true } // Allow event propagation
    )
}