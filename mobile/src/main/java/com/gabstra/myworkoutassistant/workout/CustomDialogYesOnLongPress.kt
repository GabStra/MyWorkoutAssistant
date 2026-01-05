package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
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
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.gabstra.myworkoutassistant.repeatActionOnLongPress
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelChildren
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch


@OptIn(ExperimentalFoundationApi::class)
@Composable
fun CustomDialogYesOnLongPress(
    show: Boolean = false,
    title: String = "Confirm Exit",
    message: String = "Do you really want to exit?",
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

    var hasBeenShownOnce by remember { mutableStateOf(false) }

    var closeDialogJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()
    val longPressCoroutineScope = rememberCoroutineScope()

    var currentMillis by remember { mutableLongStateOf(0) }

    var showProgressBar by remember { mutableStateOf(false) }

    var hasBeenPressedLongEnough by remember { mutableStateOf(false) }

    val progress = if (effectiveHoldTime > 0) {
        (currentMillis.toFloat() / effectiveHoldTime.toFloat()).coerceAtMost(1f)
    } else {
        0f
    }

    var startTime by remember { mutableLongStateOf(0) }

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

        hasBeenPressedLongEnough = false
        currentMillis = 0
    }

    LaunchedEffect(currentMillis){
        // Only auto-trigger if dialog is shown, hold time is set, and threshold is reached
        if (show && currentMillis >= effectiveHoldTime && !hasBeenPressedLongEnough) {
            hasBeenPressedLongEnough = true
            longPressCoroutineScope.coroutineContext.cancelChildren()
            coroutineScope.launch {
                delay(100)
                handleYesClick()
                showProgressBar = false
                currentMillis = 0
            }
        }
    }

    fun onBeforeLongPressRepeat() {
        closeDialogJob?.cancel()
        hasBeenPressedLongEnough = false
        showProgressBar = true
        currentMillis = 0

        startTime = System.currentTimeMillis()
    }

    fun onLongPressRepeat() {
        val currentTime = System.currentTimeMillis()
        currentMillis = currentTime - startTime
    }

    fun onRelease() {

        showProgressBar = false
        currentMillis = 0
        startTime = 0
        hasBeenPressedLongEnough = false

        if (show && closeTimerInMillis > 0) {
            startAutomaticCloseTimer()
        }
    }

    val density = LocalDensity.current.density
   if(show){
        Dialog(
            onDismissRequest = {  },
            properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false, usePlatformDefaultWidth = false)
        ) {
            BoxWithConstraints(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background),
                contentAlignment = Alignment.Center
            ) {
                Box(
                    modifier = Modifier
                        .size((constraints.maxWidth/density).dp)
                ) {
                    Column(
                        modifier = Modifier.fillMaxSize().padding(10.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Text(
                            text = title,
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.titleLarge,
                            modifier = Modifier.padding(20.dp,8.dp)
                        )
                        Text(
                            text = message,
                            textAlign = TextAlign.Center,
                            style = MaterialTheme.typography.bodyLarge,
                            modifier = Modifier.padding(8.dp)
                        )

                        Spacer(modifier = Modifier.height(10.dp))

                        Row(
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier
                                .fillMaxWidth()
                        ) {
                            EnhancedIconButton(
                                buttonSize = 50.dp,
                                hitBoxScale = 2f,
                                onClick = {
                                    closeDialogJob?.cancel()
                                    handleNoClick()
                                },
                                buttonModifier = Modifier
                                    .clip(CircleShape),
                            ) {
                                Icon(modifier = Modifier.size(25.dp),imageVector = Icons.Default.Close, contentDescription = "Close",tint = MaterialTheme.colorScheme.onBackground)
                            }
                            Spacer(modifier = Modifier.width(5.dp))
                            Box(
                                modifier = Modifier
                                    .size(100.dp)
                                    .repeatActionOnLongPress(
                                        longPressCoroutineScope,
                                        thresholdMillis = 10,
                                        intervalMillis = 10,
                                        onPressStart = { },
                                        onBeforeLongPressRepeat = { onBeforeLongPressRepeat() },
                                        onLongPressRepeat = { onLongPressRepeat() },
                                        onRelease = { onRelease() }
                                    ),
                                contentAlignment = Alignment.Center
                            ) {
                                Box(
                                    modifier = Modifier
                                        .size(50.dp)
                                        .clip(CircleShape)
                                        .background(MaterialTheme.colorScheme.primary),
                                    contentAlignment = Alignment.Center
                                ){
                                    Icon(
                                        modifier = Modifier.size(25.dp),
                                        imageVector = Icons.Default.Check,
                                        contentDescription = "Done",
                                        tint = MaterialTheme.colorScheme.background
                                    )
                                }
                            }
                        }
                    }

                    if (showProgressBar) {
                        CircularProgressIndicator(
                            progress = { progress },
                            modifier = Modifier.fillMaxSize().padding(10.dp),
                            //.graphicsLayer(alpha = progressBarAlpha),
                            color = MaterialTheme.colorScheme.primary,
                            strokeWidth = 4.dp,
                            trackColor = MediumDarkGray,
                        )
                    }
                }


            }

/*            val progressBarAlpha: Float by animateFloatAsState(
                targetValue = if (showProgressBar) 1f else 0f,
                animationSpec = if (showProgressBar) {
                    tween(durationMillis = 100)
                } else {
                    snap()
                },
                label = "DialogProgressBarAlpha"
            )*/



        }
    }
}

