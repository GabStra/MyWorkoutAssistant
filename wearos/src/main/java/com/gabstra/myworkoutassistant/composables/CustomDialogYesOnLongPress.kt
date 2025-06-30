package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.repeatActionOnLongPress
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import com.gabstra.myworkoutassistant.shared.Orange
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
) {
    var closeDialogJob by remember { mutableStateOf<Job?>(null) }
    val coroutineScope = rememberCoroutineScope()
    val longPressCoroutineScope = rememberCoroutineScope()

    var currentMillis by remember { mutableLongStateOf(0) }

    var showProgressBar by remember { mutableStateOf(false) }

    var hasBeenPressedLongEnough by remember { mutableStateOf(false) }

    val progress = 1 - (currentMillis.toFloat() / holdTimeInMillis.toFloat()).coerceAtMost(1f)

    var startTime by remember { mutableLongStateOf(0) }

    fun startAutomaticCloseTimer() {
        closeDialogJob?.cancel()
        closeDialogJob = coroutineScope.launch {
            delay(closeTimerInMillis)
            handleOnAutomaticClose()
        }
    }

    LaunchedEffect(show) {
        if (show && closeTimerInMillis > 0) {
            startAutomaticCloseTimer()
        }

        hasBeenPressedLongEnough = false
        currentMillis = 0
    }

    LaunchedEffect(currentMillis){
        if (currentMillis >= holdTimeInMillis && !hasBeenPressedLongEnough) {
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

   if(show){
        Dialog(
            onDismissRequest = {  },
            properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false)
        ) {
            Box(
                modifier = Modifier
                    .background(MaterialTheme.colors.background)
                    .fillMaxSize()
                    .padding(25.dp), contentAlignment = Alignment.Center
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Top,
                ) {
                    Text(
                        text = title,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.title3.copy(fontWeight = FontWeight.Bold),
                        modifier = Modifier.padding(15.dp,8.dp)
                    )
                    Text(
                        text = message,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.body1,
                        modifier = Modifier.padding(8.dp)
                    )

                    Spacer(modifier = Modifier.height(10.dp))

                    Row(
                        horizontalArrangement = Arrangement.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                    ) {
                        EnhancedButton(
                            buttonSize = 35.dp,
                            hitBoxScale = 2f,
                            onClick = {
                                closeDialogJob?.cancel()
                                handleNoClick()
                            },
                            buttonModifier = Modifier
                                .size(35.dp)
                                .clip(CircleShape),
                            colors = ButtonDefaults.buttonColors(backgroundColor = MediumDarkGray)
                        ) {
                            Icon(imageVector = Icons.Default.Close, contentDescription = "Close")
                        }
                        Spacer(modifier = Modifier.width(5.dp))
                        Box(
                            modifier = Modifier
                                .size(70.dp)
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
                                    .size(35.dp)
                                    .clip(CircleShape)
                                    .background(Orange),
                                contentAlignment = Alignment.Center
                            ){
                                Icon(imageVector = Icons.Default.Check, contentDescription = "Done", tint = MaterialTheme.colors.background)
                            }
                        }
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

            if (showProgressBar) {
                CircularProgressIndicator(
                    progress = progress,
                    modifier = Modifier
                        .fillMaxSize(),
                        //.graphicsLayer(alpha = progressBarAlpha),
                    strokeWidth = 4.dp,
                    indicatorColor = MaterialTheme.colors.primary,
                    trackColor = MediumDarkGray
                )
            }
        }
    }
}