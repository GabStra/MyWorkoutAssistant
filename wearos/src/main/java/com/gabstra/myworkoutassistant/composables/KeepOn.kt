package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
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
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.getSystemService
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.findActivity
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Window brightness in 0..1 from [Settings.System.SCREEN_BRIGHTNESS] (user/slider value),
 * or [WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE] if unavailable.
 */
private fun readSystemBrightnessAsWindowOverride(context: Context): Float {
    return try {
        val raw = Settings.System.getInt(
            context.contentResolver,
            Settings.System.SCREEN_BRIGHTNESS
        )
        raw.coerceIn(0, 255) / 255f
    } catch (_: Settings.SettingNotFoundException) {
        WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
    } catch (_: SecurityException) {
        WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
    }
}

@Composable
@SuppressLint("WakelockTimeout")
fun KeepOn(
    appViewModel: AppViewModel,
    keepInteractive: Boolean = true,
    enableDimming: Boolean = false,
    dimDelay: Long = 30000L, // Delay before dimming the screen
    content: @Composable () -> Unit
) {
    val context = LocalContext.current
    val activity = context.findActivity()
    val window = activity?.window
    val powerManager = context.getSystemService<PowerManager>()
    val wakeLock = remember(powerManager) {
        powerManager?.newWakeLock(
            PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
            "MyWorkoutAssistant:ScreenOn"
        )?.apply { setReferenceCounted(false) }
    }

    val scope = rememberWearCoroutineScope()

    var isDimmed by remember { mutableStateOf(false) }
    var dimmingJob by remember { mutableStateOf<Job?>(null) }

    val updatedEnableDimming by rememberUpdatedState(enableDimming)
    val updatedDimDelay by rememberUpdatedState(dimDelay)
    val updatedKeepInteractive by rememberUpdatedState(keepInteractive)

    fun setScreenBrightness(brightness: Float) {
        window?.attributes = window?.attributes?.apply {
            screenBrightness = brightness
        }
    }

    /** Lock brightness to the current system slider level until in-app dim kicks in. */
    fun applyAwakeBrightness() {
        setScreenBrightness(readSystemBrightnessAsWindowOverride(context))
    }

    fun applyWindowFlags() {
        window?.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            activity?.setShowWhenLocked(true)
            activity?.setTurnScreenOn(true)
        }
    }

    fun clearWindowFlags() {
        window?.clearFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            activity?.setShowWhenLocked(false)
            activity?.setTurnScreenOn(false)
        }
    }

    fun acquireWakeLock() {
        if (wakeLock?.isHeld == false) {
            wakeLock.acquire()
        }
    }

    fun releaseWakeLock() {
        if (wakeLock?.isHeld == true) {
            wakeLock.release()
        }
    }

    var isCoolingDown by remember { mutableStateOf(false) }

    fun deactivateInteractiveMode() {
        dimmingJob?.cancel()
        clearWindowFlags()
        setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
        isDimmed = false
        releaseWakeLock()
    }

    fun wakeUpAndResetTimer() {
        dimmingJob?.cancel()

        if (isDimmed) {
            isDimmed = false
        }

        if (!updatedKeepInteractive) {
            setScreenBrightness(WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE)
            return
        }

        if (updatedEnableDimming) {
            applyAwakeBrightness()
            dimmingJob = scope.launch {
                delay(updatedDimDelay)
                // Keep the display alive but visibly dimmed instead of completely off
                setScreenBrightness(0.05f)
                isDimmed = true
            }
        } else {
            applyAwakeBrightness()
        }
    }

    fun applyInteractiveMode() {
        if (!updatedKeepInteractive) {
            deactivateInteractiveMode()
            return
        }

        applyWindowFlags()
        acquireWakeLock()
        wakeUpAndResetTimer()
    }

    LifecycleObserver(
        onPaused = {
            if (!updatedKeepInteractive) {
                deactivateInteractiveMode()
            }
        },
        onStarted = {
            applyInteractiveMode()
        },
        onResumed = {
            applyInteractiveMode()
        },
        onStopped = {
            deactivateInteractiveMode()
        }
    )

    DisposableEffect(Unit) {
        applyInteractiveMode()
        onDispose {
            // Ensure flags and brightness are reset when leaving the screen.
            deactivateInteractiveMode()
        }
    }

    // Effect to handle external wake-up calls from the ViewModel
    LaunchedEffect(Unit) {
        appViewModel.lightScreenUp.collect {
            wakeUpAndResetTimer()
        }
    }

    LaunchedEffect(keepInteractive, enableDimming) {
        applyInteractiveMode()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Transparent)
            .then(
                if(enableDimming && keepInteractive){
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
