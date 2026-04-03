package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumLighterGray
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

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
    val effectiveHoldTime = if (holdTimeInMillis > 0) holdTimeInMillis else systemLongPressTimeout
    val holdDurationMillis = effectiveHoldTime.coerceAtMost(Int.MAX_VALUE.toLong()).toInt()

    var hasBeenShownOnce by remember { mutableStateOf(false) }
    var closeDialogJob by remember { mutableStateOf<Job?>(null) }
    var confirmHoldJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberWearCoroutineScope()
    val holdProgress = remember { Animatable(0f) }
    val latestHandleYesClick by rememberUpdatedState(handleYesClick)

    var hasBeenPressedLongEnough by remember { mutableStateOf(false) }

    fun startAutomaticCloseTimer() {
        closeDialogJob?.cancel()
        closeDialogJob = coroutineScope.launch {
            delay(closeTimerInMillis)
            handleOnAutomaticClose()
        }
    }

    LaunchedEffect(show) {
        if (show) {
            hasBeenShownOnce = true
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
        closeDialogJob?.cancel()
        confirmHoldJob?.cancel()
        hasBeenPressedLongEnough = false
        confirmHoldJob = coroutineScope.launch {
            holdProgress.snapTo(0f)
            holdProgress.animateTo(
                targetValue = 1f,
                animationSpec = tween(
                    durationMillis = holdDurationMillis,
                    easing = LinearEasing
                )
            )

            if (show && !hasBeenPressedLongEnough) {
                hasBeenPressedLongEnough = true
                latestHandleYesClick()
                holdProgress.snapTo(0f)
            }
        }
    }

    fun stopConfirmHold() {
        confirmHoldJob?.cancel()
        confirmHoldJob = null
        coroutineScope.launch {
            holdProgress.snapTo(0f)
        }

        if (show && closeTimerInMillis > 0 && !hasBeenPressedLongEnough) {
            startAutomaticCloseTimer()
        }

        hasBeenPressedLongEnough = false
    }

    if (show) {
        Dialog(
            onDismissRequest = { },
            properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background)
            ) {
                val scrollState = rememberScrollState()
                ScreenScaffold(
                    modifier = Modifier
                        .fillMaxSize(),
                    scrollState = scrollState,
                    overscrollEffect = null,
                    scrollIndicator = {
                        if (holdProgress.value == 0f) {
                            ScrollIndicator(
                                state = scrollState,
                                colors = ScrollIndicatorDefaults.colors(
                                    indicatorColor = MaterialTheme.colorScheme.onBackground,
                                    trackColor = MediumDarkGray
                                )
                            )
                        }
                    }
                ) { contentPadding ->
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(top = contentPadding.calculateTopPadding())
                            .padding(horizontal = 30.dp)
                            .padding(top = 10.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(
                            text = title,
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.titleLarge,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 20.dp)
                        )
                        Spacer(modifier = Modifier.height(5.dp))

                        Column(
                            modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .verticalScroll(scrollState)
                        ){
                            Text(
                                text = message,
                                textAlign = TextAlign.Center,
                                color = MediumLighterGray,
                                style = MaterialTheme.typography.bodyLarge,
                                modifier = Modifier.fillMaxWidth()
                            )
                        }
                        Spacer(modifier = Modifier.height(2.5.dp))
                        val contentColor = MaterialTheme.colorScheme.onSurface
                        Row(
                            horizontalArrangement = Arrangement.Center,
                            modifier = Modifier.fillMaxWidth().padding(bottom = 22.5.dp)
                        ) {
                            EnhancedIconButton(
                                buttonSize = 50.dp,
                                hitBoxScale = 1.25f,
                                onClick = {
                                    closeDialogJob?.cancel()
                                    handleNoClick()
                                },
                                buttonModifier = Modifier.clip(CircleShape)
                            ) {
                                Icon(
                                    modifier = Modifier.size(30.dp),
                                    imageVector = Icons.Default.Close,
                                    contentDescription = "Close",
                                    tint = contentColor
                                )
                            }
                            Spacer(modifier = Modifier.width(20.dp))
                            Box(
                                modifier = Modifier
                                    .size(62.5.dp)
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
                                Box(
                                    modifier = Modifier
                                        .size(50.dp)
                                        .clip(CircleShape)
                                        .background(MaterialTheme.colorScheme.primary),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Icon(
                                        modifier = Modifier.size(30.dp),
                                        imageVector = Icons.Default.Check,
                                        contentDescription = "Done",
                                        tint = MaterialTheme.colorScheme.onPrimary
                                    )
                                }
                            }
                        }
                    }
                }

                if (holdProgress.value > 0f) {
                    androidx.wear.compose.material.CircularProgressIndicator(
                        progress = holdProgress.value,
                        modifier = Modifier
                            .fillMaxSize(),
                        strokeWidth = 4.dp,
                        indicatorColor = MaterialTheme.colorScheme.primary,
                        trackColor = MediumDarkGray
                    )
                }
            }
        }
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun CustomDialogYesOnLongPressHugeTextPreview() {
    MaterialTheme(
        colorScheme = darkScheme,
        typography = baseline,
    ) {
        CustomDialogYesOnLongPress(
            show = true,
            title = "Complete calibration set",
            message = "Rate your RIR after you finish this set.",
            handleNoClick = {},
            handleYesClick = {},
            closeTimerInMillis = 0L,
            holdTimeInMillis = 1200L
        )
    }
}
