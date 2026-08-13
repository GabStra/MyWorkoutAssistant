package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val MobileConfirmationIndicatorSize = 96.dp
private val MobileConfirmationButtonSize = 72.dp

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CustomDialogYesOnLongPress(
    show: Boolean = false,
    title: String = "Exit workout",
    message: String = "Do you want to leave this workout?",
    handleNoClick: () -> Unit,
    handleYesClick: () -> Unit,
    closeTimerInMillis: Long = 0,
    handleOnAutomaticClose: () -> Unit = {},
    holdTimeInMillis: Long = 0,
    onVisibilityChange: (Boolean) -> Unit = {}
) {
    val systemLongPressTimeout = LocalViewConfiguration.current.longPressTimeoutMillis

    // Use system default when holdTimeInMillis is 0, otherwise use provided value
    val effectiveHoldTime = if (holdTimeInMillis > 0) holdTimeInMillis else systemLongPressTimeout
    val holdDurationMillis = effectiveHoldTime.coerceAtMost(Int.MAX_VALUE.toLong()).toInt()

    var hasBeenShownOnce by remember { mutableStateOf(false) }

    var closeDialogJob by remember { mutableStateOf<Job?>(null) }
    var confirmHoldJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()
    val holdProgress = remember { Animatable(0f) }
    val latestHandleNoClick by rememberUpdatedState(handleNoClick)
    val latestHandleYesClick by rememberUpdatedState(handleYesClick)
    val latestHandleOnAutomaticClose by rememberUpdatedState(handleOnAutomaticClose)

    var hasBeenPressedLongEnough by remember { mutableStateOf(false) }
    var hasHandledDialogAction by remember { mutableStateOf(false) }

    fun cancelAutomaticCloseTimer() {
        closeDialogJob?.cancel()
        closeDialogJob = null
    }

    fun cancelConfirmHold() {
        confirmHoldJob?.cancel()
        confirmHoldJob = null
    }

    fun runNoClick() {
        if (hasHandledDialogAction) return
        hasHandledDialogAction = true
        cancelAutomaticCloseTimer()
        cancelConfirmHold()
        latestHandleNoClick()
    }

    fun runAutomaticClose() {
        if (hasHandledDialogAction) return
        hasHandledDialogAction = true
        cancelConfirmHold()
        latestHandleOnAutomaticClose()
    }

    fun runYesClick() {
        if (hasHandledDialogAction) return
        hasHandledDialogAction = true
        cancelAutomaticCloseTimer()
        latestHandleYesClick()
    }

    fun startAutomaticCloseTimer() {
        cancelAutomaticCloseTimer()
        closeDialogJob = coroutineScope.launch {
            delay(closeTimerInMillis)
            runAutomaticClose()
        }
    }

    LaunchedEffect(show) {
        if (show) {
            hasBeenShownOnce = true
            hasHandledDialogAction = false
        } else {
            cancelAutomaticCloseTimer()
            cancelConfirmHold()
        }

        if (hasBeenShownOnce) {
            onVisibilityChange(show)
        }

        if (show && closeTimerInMillis > 0) {
            startAutomaticCloseTimer()
        }

        confirmHoldJob?.cancel()
        hasBeenPressedLongEnough = false
        holdProgress.snapTo(0f)
    }

    fun startConfirmHold() {
        cancelAutomaticCloseTimer()
        cancelConfirmHold()
        hasBeenPressedLongEnough = false
        confirmHoldJob = coroutineScope.launch {
            holdProgress.snapTo(0f)
            holdProgress.animateTo(
                targetValue = 1f,
                animationSpec = tween(
                    durationMillis = holdDurationMillis,
                    easing = LinearEasing,
                ),
            )
            if (show && !hasBeenPressedLongEnough) {
                hasBeenPressedLongEnough = true
                runYesClick()
                holdProgress.snapTo(0f)
            }
        }
    }

    fun stopConfirmHold() {
        confirmHoldJob?.cancel()
        confirmHoldJob = null
        coroutineScope.launch { holdProgress.snapTo(0f) }
        if (show && closeTimerInMillis > 0 && !hasBeenPressedLongEnough) {
            startAutomaticCloseTimer()
        }
        hasBeenPressedLongEnough = false
    }

   if(show){
        Dialog(
            onDismissRequest = {  },
            properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false, usePlatformDefaultWidth = false)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background),
                contentAlignment = Alignment.Center
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 32.dp, vertical = 32.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Text(
                        text = title,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.headlineMedium.copy(
                            fontWeight = FontWeight.SemiBold,
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp),
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Text(
                        text = message,
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.titleLarge,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp),
                    )

                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "Hold check to confirm",
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.72f),
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.fillMaxWidth(),
                    )

                    Spacer(modifier = Modifier.height(32.dp))

                    Row(
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        FilledTonalIconButton(
                            onClick = {
                                runNoClick()
                            },
                            modifier = Modifier
                                .size(72.dp)
                                .clip(CircleShape),
                        ) {
                            Icon(
                                modifier = Modifier.size(36.dp),
                                imageVector = Icons.Default.Close,
                                contentDescription = "Close",
                                tint = MaterialTheme.colorScheme.onSurface
                            )
                        }
                        Spacer(modifier = Modifier.width(32.dp))
                        Box(
                            modifier = Modifier
                                .size(MobileConfirmationIndicatorSize)
                                .pointerInput(show, holdDurationMillis) {
                                    detectTapGestures(
                                        onPress = {
                                            startConfirmHold()
                                            try {
                                                tryAwaitRelease()
                                            } finally {
                                                stopConfirmHold()
                                            }
                                        }
                                    )
                                },
                            contentAlignment = Alignment.Center
                        ) {
                            if (holdProgress.value > 0f) {
                                CircularProgressIndicator(
                                    progress = { holdProgress.value },
                                    modifier = Modifier.size(MobileConfirmationIndicatorSize),
                                    color = MaterialTheme.colorScheme.primary,
                                    strokeWidth = 6.dp,
                                    trackColor = MediumDarkGray,
                                )
                            }
                            Box(
                                modifier = Modifier
                                    .size(MobileConfirmationButtonSize)
                                    .clip(CircleShape)
                                    .background(MaterialTheme.colorScheme.primary),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(
                                    modifier = Modifier.size(36.dp),
                                    imageVector = Icons.Default.Check,
                                    contentDescription = "Done",
                                    tint = MaterialTheme.colorScheme.onPrimary
                                )
                            }
                        }
                    }
                }
            }

        }
    }
}
