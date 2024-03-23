package com.gabstra.myworkoutassistant.composable

import android.util.Log
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.CircularProgressIndicator
import com.gabstra.myworkoutassistant.data.repeatActionOnLongPress
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
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
            delay(closeTimerInMillis)  // wait for 10 seconds
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
            Log.d("CustomDialogYesOnLongPress", "currentMillis: $currentMillis hasBeenPressedLongEnough: $hasBeenPressedLongEnough")
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
        currentMillis = 0
        showProgressBar = false
        startTime = 0
        hasBeenPressedLongEnough = false

        if (show && closeTimerInMillis > 0) {
            startAutomaticCloseTimer()
        }
    }

    if (show) {
        Dialog(
            onDismissRequest = { handleNoClick() }
        ) {
            Box(
                modifier = Modifier
                    .background(Color.Black)
                    .fillMaxSize().padding(20.dp), contentAlignment = Alignment.Center
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Top,
                ) {
                    Text(
                        text = title,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.caption1,
                        modifier = Modifier.padding(15.dp,8.dp)
                    )
                    Text(
                        text = message,
                        textAlign = TextAlign.Center,
                        style = MaterialTheme.typography.caption1,
                        modifier = Modifier.padding(8.dp)
                    )

                    Spacer(modifier = Modifier.height(10.dp))

                    Row(
                        horizontalArrangement = Arrangement.Center,
                        modifier = Modifier
                            .fillMaxWidth()
                    ) {
                        Button(
                            onClick = {
                                closeDialogJob?.cancel()
                                handleNoClick()
                            },
                            modifier = Modifier.size(35.dp),
                            colors = ButtonDefaults.buttonColors(backgroundColor = MaterialTheme.colors.error)
                        ) {
                            Icon(imageVector = Icons.Default.Close, contentDescription = "Close")
                        }
                        Spacer(modifier = Modifier.width(20.dp))
                        Box(
                            modifier = Modifier
                                .size(35.dp)
                                .clip(CircleShape)
                                .background(MaterialTheme.colors.primary)
                                .repeatActionOnLongPress(
                                    longPressCoroutineScope,
                                    thresholdMillis = 200,
                                    intervalMillis = 100,
                                    onPressStart = { },
                                    onBeforeLongPressRepeat = { onBeforeLongPressRepeat() },
                                    onLongPressRepeat = { onLongPressRepeat() },
                                    onRelease = { onRelease() }
                                ),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(imageVector = Icons.Default.Check, contentDescription = "Done")
                        }
                    }
                }
            }

            if (showProgressBar) {
                CircularProgressIndicator(
                    progress = progress,
                    modifier = Modifier.fillMaxSize(),
                    startAngle = 290f,
                    endAngle = 250f,
                    strokeWidth = 4.dp,
                    indicatorColor = MaterialTheme.colors.primary
                )
            }
        }
    }
}